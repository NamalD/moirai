"""Lachesis — deterministic scheduler (SPEC.md §7.4, §9).

Scope note: loop steps (LoopDef) are delegated to LoopExecutor per §4.7 /
§7.4, which is Phase 5 — not yet implemented. Lachesis here handles the
plain-task DAG scheduling loop only; a StateMachine containing loop_tasks
is rejected up front with a clear NotImplementedError rather than silently
mishandled.
"""

import os
import signal as signal_module
from typing import Optional, Protocol

from moirai.protocols import HumanNotifier, PersistenceBackend, ProcessManager, TimeProvider
from moirai.types import (
    AgentDef,
    CleanupResult,
    ExecutionLog,
    ExecutionState,
    FailureReason,
    ProcessInfo,
    SchedulerConfig,
    StateMachine,
    TaskEvent,
    TaskState,
    TaskStatus,
)

_TERMINAL_STATUSES = (
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.SKIPPED,
)
_DEP_SATISFIED_STATUSES = (TaskStatus.COMPLETED, TaskStatus.SKIPPED)


class HangCleaner(Protocol):
    """The slice of Atropos's contract Lachesis depends on (SPEC.md §7.6).

    Kept as a narrow local protocol (rather than added to protocols.py's
    canonical list) so Phase 3 is independently testable with a fake before
    Phase 4's real Atropos exists — Atropos's public method is written to
    satisfy this shape exactly.
    """

    def cleanup(
        self, task_id: str, process_info: ProcessInfo, failure_reason: FailureReason
    ) -> CleanupResult: ...


class Lachesis:
    """The core scheduling engine — polls tasks, dispatches ready work."""

    def __init__(
        self,
        state_machine: StateMachine,
        persistence: PersistenceBackend,
        process_manager: ProcessManager,
        atropos: HangCleaner,
        human_notifier: HumanNotifier,
        time_provider: TimeProvider,
        agents: dict[str, AgentDef],
        config: Optional[SchedulerConfig] = None,
        default_work_dir: str = ".",
        log_dir: str = "/tmp/moirai-logs",
    ) -> None:
        if state_machine.loop_tasks:
            raise NotImplementedError(
                "Lachesis (Phase 3) does not yet support loop steps — "
                "that's LoopExecutor's job (Phase 5), not implemented yet."
            )
        self._sm = state_machine
        self._persistence = persistence
        self._process_manager = process_manager
        self._atropos = atropos
        self._human_notifier = human_notifier
        self._time_provider = time_provider
        self._agents = agents
        self._config = config or SchedulerConfig()
        self._default_work_dir = default_work_dir
        self._log_dir = os.path.join(log_dir, state_machine.workflow_id)

        self._running: dict[str, ProcessInfo] = {}
        self._events: list[TaskEvent] = []
        self._shutdown_requested = False
        self._cancelled = False

    # ─── External control surface ───────────────────────────────────

    def request_shutdown(self) -> None:
        """Graceful shutdown trigger (SPEC.md §7.4) — e.g. from a SIGTERM handler."""
        self._shutdown_requested = True

    def cancel(self) -> None:
        """User-initiated abort (SPEC.md §17)."""
        self._cancelled = True

    def install_signal_handlers(self) -> None:
        """Register a real SIGTERM handler. Opt-in — not called by run()
        automatically, since signal.signal() only works on the main thread
        and would get in the way of test harnesses driving the loop directly.
        """
        signal_module.signal(signal_module.SIGTERM, lambda *_: self.request_shutdown())

    # ─── Main loop (SPEC.md §7.4 polling model) ─────────────────────

    def run(self) -> ExecutionLog:
        self._initialize_state()
        start_time = self._time_provider.now()
        shutdown_deadline: Optional[float] = None

        while True:
            self._poll_running()

            if self._cancelled:
                self._do_cancel()
                break

            if not self._shutdown_requested:
                self._dispatch_ready()

            self._check_hangs()

            if self._shutdown_requested:
                if shutdown_deadline is None:
                    shutdown_deadline = (
                        self._time_provider.now() + self._config.graceful_shutdown_timeout
                    )
                if not self._running or self._time_provider.now() >= shutdown_deadline:
                    break
            elif not self._running and not self._ready_tasks():
                break  # everything terminal, or blocked with nothing left to run

            self._time_provider.sleep(self._config.poll_interval_seconds)

        return self._finalize_execution_log(start_time)

    # ─── Internals ───────────────────────────────────────────────────

    def _initialize_state(self) -> None:
        for task_id in self._sm.tasks:
            if self._persistence.get_task(self._sm.workflow_id, task_id) is None:
                self._persistence.set_task(
                    self._sm.workflow_id, task_id, TaskState(task_id=task_id)
                )

    def _ready_tasks(self) -> list[str]:
        ready = []
        for task_id in self._sm.tasks:
            state = self._persistence.get_task(self._sm.workflow_id, task_id)
            if state.status != TaskStatus.PENDING:
                continue
            deps = self._sm.dependencies.get(task_id, [])
            if all(
                self._persistence.get_task(self._sm.workflow_id, dep).status
                in _DEP_SATISFIED_STATUSES
                for dep in deps
            ):
                ready.append(task_id)
        return ready

    def _dispatch_ready(self) -> None:
        ready = self._ready_tasks()
        while ready and len(self._running) < self._config.max_concurrent_tasks:
            self._dispatch(ready.pop(0))

    def _dispatch(self, task_id: str) -> None:
        task_def = self._sm.tasks[task_id]
        agent_def = self._agents[task_def.agent]
        work_dir = agent_def.work_dir or self._default_work_dir

        process_info = self._process_manager.spawn(
            task_def, agent_def, work_dir=work_dir, log_dir=self._log_dir
        )
        state = self._persistence.get_task(self._sm.workflow_id, task_id)
        state.status = TaskStatus.RUNNING
        state.attempts += 1
        state.started_at = self._time_provider.now()
        self._persistence.set_task(self._sm.workflow_id, task_id, state)
        self._running[task_id] = process_info
        self._emit_event(task_id, TaskStatus.PENDING, TaskStatus.RUNNING)

    def _poll_running(self) -> None:
        for task_id, process_info in list(self._running.items()):
            exit_code = self._process_manager.poll(process_info)
            if exit_code is not None:
                self._handle_completion(task_id, exit_code)

    def _handle_completion(self, task_id: str, exit_code: int) -> None:
        process_info = self._running.pop(task_id)
        state = self._persistence.get_task(self._sm.workflow_id, task_id)
        state.completed_at = self._time_provider.now()
        state.exit_code = exit_code
        state.stdout_path = process_info.stdout_path
        state.stderr_path = process_info.stderr_path

        if exit_code == 0:
            state.status = TaskStatus.COMPLETED
            self._persistence.set_task(self._sm.workflow_id, task_id, state)
            self._emit_event(task_id, TaskStatus.RUNNING, TaskStatus.COMPLETED)
            return

        task_def = self._sm.tasks[task_id]
        if state.attempts < task_def.max_retries:
            state.status = TaskStatus.PENDING
            self._persistence.set_task(self._sm.workflow_id, task_id, state)
            self._emit_event(
                task_id, TaskStatus.RUNNING, TaskStatus.PENDING, details="crash, re-queued"
            )
        else:
            self._persistence.set_task(self._sm.workflow_id, task_id, state)
            self._invoke_atropos(task_id, process_info, FailureReason.CRASH_LIMIT_EXCEEDED)

    def _check_hangs(self) -> None:
        now = self._time_provider.now()
        for task_id, process_info in list(self._running.items()):
            state = self._persistence.get_task(self._sm.workflow_id, task_id)
            task_def = self._sm.tasks[task_id]
            if state.started_at is not None and now - state.started_at > task_def.timeout:
                self._invoke_atropos(task_id, process_info, FailureReason.TIMEOUT_EXCEEDED)

    def _invoke_atropos(
        self, task_id: str, process_info: ProcessInfo, failure_reason: FailureReason
    ) -> None:
        self._running.pop(task_id, None)
        result = self._atropos.cleanup(task_id, process_info, failure_reason)
        state = self._persistence.get_task(self._sm.workflow_id, task_id)
        state.status = TaskStatus.FAILED
        state.failure_reason = failure_reason
        state.completed_at = self._time_provider.now()
        state.error_message = result.details
        self._persistence.set_task(self._sm.workflow_id, task_id, state)
        self._emit_event(
            task_id, TaskStatus.RUNNING, TaskStatus.FAILED, details=result.details
        )

    def _do_cancel(self) -> None:
        for task_id in self._sm.tasks:
            state = self._persistence.get_task(self._sm.workflow_id, task_id)
            if state.status in (TaskStatus.PENDING, TaskStatus.READY):
                state.status = TaskStatus.CANCELLED
                self._persistence.set_task(self._sm.workflow_id, task_id, state)
                self._emit_event(task_id, TaskStatus.PENDING, TaskStatus.CANCELLED)
        for task_id, process_info in list(self._running.items()):
            self._invoke_atropos(task_id, process_info, FailureReason.USER_ABORT)

    def _emit_event(
        self,
        task_id: str,
        from_status: TaskStatus,
        to_status: TaskStatus,
        details: Optional[str] = None,
    ) -> None:
        self._events.append(
            TaskEvent(
                task_id=task_id,
                from_status=from_status,
                to_status=to_status,
                timestamp=self._time_provider.now(),
                details=details,
            )
        )

    def _finalize_execution_log(self, start_time: float) -> ExecutionLog:
        tasks = {
            task_id: self._persistence.get_task(self._sm.workflow_id, task_id)
            for task_id in self._sm.tasks
        }
        if self._cancelled:
            outcome = "cancelled"
        elif any(t.status == TaskStatus.FAILED for t in tasks.values()):
            outcome = "failed"
        elif all(t.status == TaskStatus.COMPLETED for t in tasks.values()):
            outcome = "success"
        else:
            outcome = "incomplete"

        self._persistence.set_execution_state(
            ExecutionState(
                workflow_id=self._sm.workflow_id,
                tasks=tasks,
                current_sm_version=self._sm.version,
            )
        )
        return ExecutionLog(
            workflow_id=self._sm.workflow_id,
            start_time=start_time,
            end_time=self._time_provider.now(),
            tasks=tasks,
            events=self._events,
            outcome=outcome,
        )
