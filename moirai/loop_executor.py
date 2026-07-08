"""LoopExecutor — loop-step iteration manager (SPEC.md §4.7, §7.4 items 1-9).

Extracted from Lachesis for testability. A loop step is a single opaque
node in the outer DAG; LoopExecutor owns everything that happens inside
it — dispatching inner steps, polling them to completion, detecting inner
hangs/crashes, checking `terminate_on`, and building the env-var context
passed between iterations. Lachesis calls `execute_iteration()` once per
iteration and decides (based on the returned `LoopIterationResult`) whether
to iterate again, declare the loop step COMPLETED, or declare it FAILED.
"""

import dataclasses
import os
import re
from typing import Optional, Protocol

from moirai.protocols import ProcessManager, TimeProvider
from moirai.types import (
    FailureReason,
    LoopDef,
    LoopIterationResult,
    LoopStatus,
    LoopTaskState,
    ProcessInfo,
    TaskDef,
    TaskState,
    TaskStatus,
)

_DEFAULT_LOOP_TIMEOUT_SECONDS = 3600
_ITERATION_LOG_TRUNCATE_CHARS = 500


class HangCleaner(Protocol):
    """The slice of Atropos's contract LoopExecutor depends on.

    Same shape as Lachesis's local `HangCleaner` protocol — duplicated here
    (rather than imported from lachesis.py) to avoid a circular import,
    since Lachesis imports LoopExecutor.
    """

    def cleanup(
        self, task_id: str, process_info: ProcessInfo, failure_reason: FailureReason
    ) -> object: ...


class LoopExecutor:
    """Manages the inner iteration lifecycle of a single loop step."""

    def __init__(
        self,
        agents: dict,
        atropos: HangCleaner,
        default_work_dir: str = ".",
        log_dir: str = "/tmp/moirai-logs",
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self._agents = agents
        self._atropos = atropos
        self._default_work_dir = default_work_dir
        self._log_dir = log_dir
        self._poll_interval_seconds = poll_interval_seconds

    # ─── Pure helpers (SPEC §4.7) ────────────────────────────────────

    def check_terminate_on(self, output: str, condition: str) -> bool:
        """Whole-word match — \\bcondition\\b — never bare substring match."""
        if not condition:
            return False
        pattern = r"\b" + re.escape(condition) + r"\b"
        return re.search(pattern, output) is not None

    def build_iteration_context(
        self, previous_outputs: dict[str, str], current_iteration: int
    ) -> dict[str, str]:
        context = {"MOIRAI_LOOP_ITERATION": str(current_iteration)}
        if previous_outputs:
            context["MOIRAI_PREV_OUTPUT"] = "\n".join(previous_outputs.values())
            for step_id, output in previous_outputs.items():
                context[f"MOIRAI_PREV_OUTPUTS_{step_id.upper()}"] = output
        return context

    # ─── Iteration execution (SPEC §7.4 items 1-9) ──────────────────

    def execute_iteration(
        self,
        loop_state: LoopTaskState,
        loop_def: LoopDef,
        process_manager: ProcessManager,
        time_provider: TimeProvider,
    ) -> LoopIterationResult:
        now = time_provider.now()
        if loop_state.loop_timeout is not None and now > loop_state.loop_timeout:
            return LoopIterationResult(
                completed=False,
                terminate_on_met=False,
                inner_outputs={},
                final_output="",
                failed_steps=[],
                failure_reason=FailureReason.TIMEOUT_EXCEEDED,
            )

        loop_state.current_iteration += 1
        iteration_number = loop_state.current_iteration
        if iteration_number == 1:
            loop_state.loop_status = LoopStatus.ITERATING
            loop_state.loop_started_at = now
            if loop_state.loop_timeout is None:
                loop_state.loop_timeout = now + (
                    loop_def.loop_timeout
                    if loop_def.loop_timeout is not None
                    else self._default_loop_timeout(loop_def)
                )

        step_defs: dict[str, TaskDef] = {step.id: step for step in loop_def.inner_steps}
        deps: dict[str, list[str]] = {step.id: list(step.deps) for step in loop_def.inner_steps}
        dependents: dict[str, list[str]] = {step_id: [] for step_id in step_defs}
        for step_id, step_deps in deps.items():
            for dep in step_deps:
                dependents[dep].append(step_id)
        leaf_ids = [step_id for step_id, deps_of in dependents.items() if not deps_of]

        context_env = self.build_iteration_context(loop_state.last_inner_outputs, iteration_number)

        inner_states: dict[str, TaskState] = {
            step_id: TaskState(task_id=step_id) for step_id in step_defs
        }
        running: dict[str, ProcessInfo] = {}
        outputs: dict[str, str] = {}
        failed_step_ids: list[str] = []
        failure_reason: Optional[FailureReason] = None
        max_concurrent = max(1, loop_def.max_concurrent_inner)
        iter_log_dir = os.path.join(self._log_dir, loop_state.task_id, f"iter_{iteration_number}")

        def ready_ids() -> list[str]:
            return [
                step_id
                for step_id, st in inner_states.items()
                if st.status == TaskStatus.PENDING
                and all(inner_states[dep].status == TaskStatus.COMPLETED for dep in deps[step_id])
            ]

        def dispatch(step_id: str) -> None:
            step_def = step_defs[step_id]
            agent_def = self._agents[step_def.agent]
            work_dir = agent_def.work_dir or self._default_work_dir
            env = dict(step_def.env)
            env.update(context_env)
            spawn_def = dataclasses.replace(step_def, env=env)
            process_info = process_manager.spawn(
                spawn_def, agent_def, work_dir=work_dir, log_dir=iter_log_dir
            )
            st = inner_states[step_id]
            st.status = TaskStatus.RUNNING
            st.attempts += 1
            st.started_at = time_provider.now()
            running[step_id] = process_info

        while True:
            for step_id in ready_ids():
                if len(running) >= max_concurrent:
                    break
                dispatch(step_id)

            for step_id, process_info in list(running.items()):
                exit_code = process_manager.poll(process_info)
                if exit_code is None:
                    continue
                st = inner_states[step_id]
                st.completed_at = time_provider.now()
                st.exit_code = exit_code
                if exit_code == 0:
                    st.status = TaskStatus.COMPLETED
                    stdout, _ = process_manager.read_output(process_info)
                    outputs[step_id] = stdout
                    running.pop(step_id)
                else:
                    step_def = step_defs[step_id]
                    if st.attempts < step_def.max_retries:
                        st.status = TaskStatus.PENDING
                        running.pop(step_id)
                    else:
                        failure_reason = FailureReason.CRASH_LIMIT_EXCEEDED
                        failed_step_ids.append(step_id)
                        running.pop(step_id)

            if failure_reason is None:
                for step_id, process_info in list(running.items()):
                    st = inner_states[step_id]
                    step_def = step_defs[step_id]
                    if st.started_at is not None and (
                        time_provider.now() - st.started_at > step_def.timeout
                    ):
                        failure_reason = FailureReason.TIMEOUT_EXCEEDED
                        failed_step_ids.append(step_id)
                        self._atropos.cleanup(
                            f"{loop_state.task_id}.{step_id}", process_info, failure_reason
                        )
                        running.pop(step_id)
                        break

            if failure_reason is not None:
                for step_id, process_info in list(running.items()):
                    self._atropos.cleanup(
                        f"{loop_state.task_id}.{step_id}", process_info, failure_reason
                    )
                    inner_states[step_id].status = TaskStatus.FAILED
                running.clear()
                for step_id, st in inner_states.items():
                    if st.status == TaskStatus.PENDING:
                        st.status = TaskStatus.CANCELLED

                loop_state.loop_failed_iterations += 1
                loop_state.inner_task_states = inner_states
                self._append_iteration_log(
                    loop_state, iteration_number, now, time_provider.now(), inner_states,
                    terminate_on_met=False, final_output="",
                )
                return LoopIterationResult(
                    completed=False,
                    terminate_on_met=False,
                    inner_outputs=outputs,
                    final_output="",
                    failed_steps=failed_step_ids,
                    failure_reason=failure_reason,
                )

            if all(st.status == TaskStatus.COMPLETED for st in inner_states.values()):
                break

            time_provider.sleep(self._poll_interval_seconds)

        final_output = "\n".join(outputs[step_id] for step_id in leaf_ids if step_id in outputs)
        terminate_on_met = False
        if loop_def.terminate_on:
            terminate_on_met = any(
                self.check_terminate_on(outputs.get(step_id, ""), loop_def.terminate_on)
                for step_id in leaf_ids
            )

        loop_state.last_inner_outputs = outputs
        loop_state.inner_task_states = inner_states
        self._append_iteration_log(
            loop_state, iteration_number, now, time_provider.now(), inner_states,
            terminate_on_met=terminate_on_met, final_output=final_output,
        )

        return LoopIterationResult(
            completed=True,
            terminate_on_met=terminate_on_met,
            inner_outputs=outputs,
            final_output=final_output,
            failed_steps=[],
            failure_reason=None,
        )

    # ─── Internals ───────────────────────────────────────────────────

    @staticmethod
    def _default_loop_timeout(loop_def: LoopDef) -> float:
        if not loop_def.inner_steps:
            return _DEFAULT_LOOP_TIMEOUT_SECONDS
        max_inner_timeout = max(step.timeout for step in loop_def.inner_steps)
        return loop_def.max_iterations * max_inner_timeout * len(loop_def.inner_steps)

    @staticmethod
    def _append_iteration_log(
        loop_state: LoopTaskState,
        iteration_number: int,
        started_at: float,
        completed_at: float,
        inner_states: dict[str, TaskState],
        terminate_on_met: bool,
        final_output: str,
    ) -> None:
        loop_state.iteration_log.append(
            {
                "iteration": iteration_number,
                "started_at": started_at,
                "completed_at": completed_at,
                "inner_steps": {
                    step_id: {"status": st.status.name, "exit_code": st.exit_code}
                    for step_id, st in inner_states.items()
                },
                "terminate_on_met": terminate_on_met,
                "final_output_truncated": final_output[:_ITERATION_LOG_TRUNCATE_CHARS],
            }
        )
