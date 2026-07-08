"""Lachesis — deterministic scheduler (SPEC.md §7.4, §9).

Loop steps (LoopDef) are opaque single nodes in the outer DAG — Lachesis
delegates all inner iteration management to LoopExecutor (§4.7) and only
tracks the loop step's outer TaskState (RUNNING/COMPLETED/FAILED) plus its
LoopTaskState (§7.4 items 1-9).
"""

import os
import signal as signal_module
from typing import Optional, Protocol

from moirai.loop_executor import LoopExecutor
from moirai.protocols import HumanNotifier, PersistenceBackend, ProcessManager, TimeProvider
from moirai.types import (
    AgentDef,
    CleanupResult,
    ExecutionLog,
    ExecutionState,
    FailureReason,
    LoopIterationResult,
    LoopStatus,
    LoopTaskState,
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
        loop_executor: Optional[LoopExecutor] = None,
    ) -> None:
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
        self._loop_executor = loop_executor or LoopExecutor(
            agents=agents, atropos=atropos, default_work_dir=default_work_dir, log_dir=self._log_dir
        )

        self._running: dict[str, ProcessInfo] = {}
        self._loop_states: dict[str, LoopTaskState] = {}
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
        for task_id in list(self._sm.tasks) + list(self._sm.loop_tasks):
            if self._persistence.get_task(self._sm.workflow_id, task_id) is None:
                self._persistence.set_task(
                    self._sm.workflow_id, task_id, TaskState(task_id=task_id)
                )
        for task_id, loop_def in self._sm.loop_tasks.items():
            if task_id not in self._loop_states:
                self._loop_states[task_id] = LoopTaskState(
                    task_id=task_id,
                    max_iterations=loop_def.max_iterations,
                    terminate_on=loop_def.terminate_on,
                )

    def _ready_tasks(self) -> list[str]:
        ready = []
        for task_id in list(self._sm.tasks) + list(self._sm.loop_tasks):
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
        if task_id in self._sm.loop_tasks:
            self._dispatch_loop(task_id)
            return

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

    # ─── Loop step dispatch (SPEC.md §7.4 items 1-9) ────────────────

    def _dispatch_loop(self, task_id: str) -> None:
        """Run a loop step to completion, delegating iteration-by-iteration
        to LoopExecutor. Loop steps are opaque single nodes to the outer
        DAG, so this blocks until the loop step reaches a terminal state.

        Known limitation (tracked in issue #11): this blocks Lachesis's
        entire outer polling loop for as long as the loop step runs — other
        ready tasks cannot dispatch, and other running tasks aren't polled,
        until this returns. Harmless for the one real workflow this system
        runs today (dev-workflow.yaml's implement -> review-loop chain has
        nothing to parallelize), but violates §7.4's non-blocking polling
        model for a DAG with independent parallel branches.
        """
        loop_def = self._sm.loop_tasks[task_id]
        loop_state = self._loop_states[task_id]

        state = self._persistence.get_task(self._sm.workflow_id, task_id)
        state.status = TaskStatus.RUNNING
        state.attempts += 1
        state.started_at = self._time_provider.now()
        self._persistence.set_task(self._sm.workflow_id, task_id, state)
        self._emit_event(task_id, TaskStatus.PENDING, TaskStatus.RUNNING)

        while True:
            result = self._loop_executor.execute_iteration(
                loop_state, loop_def, self._process_manager, self._time_provider
            )
            if result.failure_reason is not None:
                self._finish_loop_failed(task_id, result)
                return
            if result.terminate_on_met:
                loop_state.loop_status = LoopStatus.COMPLETED
                self._finish_loop_completed(task_id)
                return
            if loop_state.current_iteration >= loop_def.max_iterations:
                if not loop_def.terminate_on:
                    loop_state.loop_status = LoopStatus.COMPLETED
                    self._finish_loop_completed(task_id)
                else:
                    loop_state.loop_status = LoopStatus.EXHAUSTED
                    self._finish_loop_exhausted(task_id, loop_state)
                return
            # terminate_on not met and iterations remain -> loop back for the next one.

    def _finish_loop_completed(self, task_id: str) -> None:
        state = self._persistence.get_task(self._sm.workflow_id, task_id)
        state.status = TaskStatus.COMPLETED
        state.completed_at = self._time_provider.now()
        self._persistence.set_task(self._sm.workflow_id, task_id, state)
        self._emit_event(task_id, TaskStatus.RUNNING, TaskStatus.COMPLETED)

    def _finish_loop_failed(self, task_id: str, result: LoopIterationResult) -> None:
        state = self._persistence.get_task(self._sm.workflow_id, task_id)
        state.status = TaskStatus.FAILED
        state.failure_reason = result.failure_reason
        state.completed_at = self._time_provider.now()
        state.error_message = (
            f"loop step failed: {result.failure_reason.name}; failed_steps={result.failed_steps}"
        )
        self._persistence.set_task(self._sm.workflow_id, task_id, state)
        self._emit_event(task_id, TaskStatus.RUNNING, TaskStatus.FAILED, details=state.error_message)
        self._human_notifier.request_intervention(
            workflow_id=self._sm.workflow_id,
            task_id=task_id,
            reason=f"Loop step '{task_id}' failed: {result.failure_reason.name}",
        )

    def _finish_loop_exhausted(self, task_id: str, loop_state: LoopTaskState) -> None:
        state = self._persistence.get_task(self._sm.workflow_id, task_id)
        state.status = TaskStatus.FAILED
        state.failure_reason = FailureReason.LOOP_EXHAUSTED
        state.completed_at = self._time_provider.now()
        state.error_message = f"loop exhausted after {loop_state.current_iteration} iterations"
        self._persistence.set_task(self._sm.workflow_id, task_id, state)
        self._emit_event(task_id, TaskStatus.RUNNING, TaskStatus.FAILED, details=state.error_message)
        self._human_notifier.request_intervention(
            workflow_id=self._sm.workflow_id,
            task_id=task_id,
            reason=(
                f"Loop step '{task_id}' exhausted max_iterations={loop_state.max_iterations} "
                f"without meeting terminate_on={loop_state.terminate_on!r}"
            ),
        )

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
        for task_id in list(self._sm.tasks) + list(self._sm.loop_tasks):
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
            for task_id in list(self._sm.tasks) + list(self._sm.loop_tasks)
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
                loop_tasks=self._loop_states,
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
