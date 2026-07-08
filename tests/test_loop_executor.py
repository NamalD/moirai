"""Tests for LoopExecutor (SPEC.md §4.7, §7.4 items 1-9, §19.1/§19.4)."""

from moirai.loop_executor import LoopExecutor
from moirai.types import (
    AgentDef,
    FailureReason,
    LoopDef,
    LoopStatus,
    LoopTaskState,
    TaskDef,
    TaskStatus,
)
from tests.fakes.atropos import FakeAtropos
from tests.fakes.process_manager import FakeProcessManager
from tests.fakes.time_provider import FakeTimeProvider

AGENT = AgentDef(id="agent-a", name="Agent A", command="/bin/true")


def make_executor(atropos=None, poll_interval_seconds=0.0):
    atropos = atropos or FakeAtropos()
    executor = LoopExecutor(
        agents={"agent-a": AGENT},
        atropos=atropos,
        default_work_dir=".",
        log_dir="/tmp/moirai-loop-test",
        poll_interval_seconds=poll_interval_seconds,
    )
    return executor, atropos


def auto_complete_spawn(pm, outputs_by_task_id=None):
    """Wrap pm.spawn so every spawned process auto-completes with exit 0,
    optionally with a queued stdout string per task id (popped in FIFO order
    so successive iterations can supply different outputs for the same
    inner step id).
    """
    outputs_by_task_id = outputs_by_task_id or {}
    original_spawn = pm.spawn
    calls: list[TaskDef] = []

    def spawn(task_def, agent_def, work_dir, log_dir):
        calls.append(task_def)
        info = original_spawn(task_def, agent_def, work_dir, log_dir)
        queue = outputs_by_task_id.get(task_def.id)
        output = queue.pop(0) if queue else ""
        pm.set_output(info.pid, output, "")
        pm.complete(info.pid, 0)
        return info

    pm.spawn = spawn
    return calls


def review_loop_def(terminate_on="APPROVED", max_iterations=3, max_concurrent_inner=1) -> LoopDef:
    implement = TaskDef(id="implement", agent="agent-a", command="echo implement", deps=[])
    review = TaskDef(id="review", agent="agent-a", command="echo review", deps=["implement"])
    return LoopDef(
        id="dev-review",
        max_iterations=max_iterations,
        terminate_on=terminate_on,
        inner_steps=[implement, review],
        max_concurrent_inner=max_concurrent_inner,
    )


def fresh_state(loop_def: LoopDef) -> LoopTaskState:
    return LoopTaskState(
        task_id=loop_def.id, max_iterations=loop_def.max_iterations, terminate_on=loop_def.terminate_on
    )


# ─── check_terminate_on (pure function) ──────────────────────────────


def test_check_terminate_on_matches_whole_word():
    executor, _ = make_executor()
    assert executor.check_terminate_on("Review result: APPROVED", "APPROVED") is True


def test_check_terminate_on_rejects_substring_match():
    executor, _ = make_executor()
    assert executor.check_terminate_on("Review result: UNAPPROVED", "APPROVED") is False


def test_check_terminate_on_empty_condition_never_matches():
    executor, _ = make_executor()
    assert executor.check_terminate_on("anything at all", "") is False


# ─── build_iteration_context (pure function) ─────────────────────────


def test_build_iteration_context_first_iteration_has_no_prev_output():
    executor, _ = make_executor()
    context = executor.build_iteration_context({}, 1)
    assert context == {"MOIRAI_LOOP_ITERATION": "1"}


def test_build_iteration_context_includes_prev_output_and_per_step_vars():
    executor, _ = make_executor()
    context = executor.build_iteration_context(
        {"implement": "impl v1", "review": "REJECTED"}, 2
    )
    assert context["MOIRAI_LOOP_ITERATION"] == "2"
    assert context["MOIRAI_PREV_OUTPUT"] == "impl v1\nREJECTED"
    assert context["MOIRAI_PREV_OUTPUTS_IMPLEMENT"] == "impl v1"
    assert context["MOIRAI_PREV_OUTPUTS_REVIEW"] == "REJECTED"


# ─── execute_iteration ────────────────────────────────────────────────


def test_single_iteration_success_meets_terminate_on():
    loop_def = review_loop_def()
    loop_state = fresh_state(loop_def)
    executor, atropos = make_executor()
    pm = FakeProcessManager()
    clock = FakeTimeProvider()
    auto_complete_spawn(pm, {"review": ["APPROVED"]})

    result = executor.execute_iteration(loop_state, loop_def, pm, clock)

    assert result.completed is True
    assert result.terminate_on_met is True
    assert result.failure_reason is None
    assert result.failed_steps == []
    assert loop_state.current_iteration == 1
    assert loop_state.loop_status == LoopStatus.ITERATING  # Lachesis, not LoopExecutor, flips COMPLETED
    assert loop_state.loop_started_at == clock.now()
    assert len(loop_state.iteration_log) == 1
    assert atropos.calls == []


def test_multi_iteration_until_terminate_on_met():
    loop_def = review_loop_def()
    loop_state = fresh_state(loop_def)
    executor, _ = make_executor()
    pm = FakeProcessManager()
    clock = FakeTimeProvider()
    auto_complete_spawn(pm, {"review": ["REJECTED", "APPROVED"]})

    first = executor.execute_iteration(loop_state, loop_def, pm, clock)
    assert first.completed is True
    assert first.terminate_on_met is False
    assert loop_state.current_iteration == 1

    second = executor.execute_iteration(loop_state, loop_def, pm, clock)
    assert second.completed is True
    assert second.terminate_on_met is True
    assert loop_state.current_iteration == 2


def test_whole_word_matching_across_iterations():
    """'UNAPPROVED' must not satisfy terminate_on='APPROVED' — only a real
    whole-word match on a later iteration should."""
    loop_def = review_loop_def()
    loop_state = fresh_state(loop_def)
    executor, _ = make_executor()
    pm = FakeProcessManager()
    clock = FakeTimeProvider()
    auto_complete_spawn(pm, {"review": ["UNAPPROVED", "APPROVED"]})

    first = executor.execute_iteration(loop_state, loop_def, pm, clock)
    assert first.terminate_on_met is False

    second = executor.execute_iteration(loop_state, loop_def, pm, clock)
    assert second.terminate_on_met is True


def test_iteration_runs_up_to_max_iterations_without_terminating():
    loop_def = review_loop_def(max_iterations=2)
    loop_state = fresh_state(loop_def)
    executor, _ = make_executor()
    pm = FakeProcessManager()
    clock = FakeTimeProvider()
    auto_complete_spawn(pm, {"review": ["REJECTED", "REJECTED"]})

    executor.execute_iteration(loop_state, loop_def, pm, clock)
    result = executor.execute_iteration(loop_state, loop_def, pm, clock)

    assert loop_state.current_iteration == 2
    assert result.completed is True
    assert result.terminate_on_met is False


def test_env_vars_passed_correctly_between_iterations():
    loop_def = review_loop_def()
    loop_state = fresh_state(loop_def)
    executor, _ = make_executor()
    pm = FakeProcessManager()
    clock = FakeTimeProvider()
    calls = auto_complete_spawn(pm, {"implement": ["impl v1", "impl v2"], "review": ["REJECTED", "APPROVED"]})

    executor.execute_iteration(loop_state, loop_def, pm, clock)

    iteration_1_calls = list(calls)
    for task_def in iteration_1_calls:
        assert task_def.env["MOIRAI_LOOP_ITERATION"] == "1"
        assert "MOIRAI_PREV_OUTPUT" not in task_def.env

    executor.execute_iteration(loop_state, loop_def, pm, clock)

    iteration_2_calls = calls[len(iteration_1_calls):]
    assert len(iteration_2_calls) == 2
    for task_def in iteration_2_calls:
        assert task_def.env["MOIRAI_LOOP_ITERATION"] == "2"
        assert task_def.env["MOIRAI_PREV_OUTPUT"] == "impl v1\nREJECTED"
        assert task_def.env["MOIRAI_PREV_OUTPUTS_IMPLEMENT"] == "impl v1"
        assert task_def.env["MOIRAI_PREV_OUTPUTS_REVIEW"] == "REJECTED"


def test_inner_step_crash_limit_exceeded_triggers_cleanup():
    a = TaskDef(id="a", agent="agent-a", command="echo a", deps=[], max_retries=0)
    b = TaskDef(id="b", agent="agent-a", command="echo b", deps=[], max_retries=0)
    c = TaskDef(id="c", agent="agent-a", command="echo c", deps=["a", "b"])
    loop_def = LoopDef(
        id="loop-1", max_iterations=3, terminate_on="", inner_steps=[a, b, c], max_concurrent_inner=2
    )
    loop_state = fresh_state(loop_def)
    executor, atropos = make_executor()
    pm = FakeProcessManager()
    clock = FakeTimeProvider()

    pids: dict[str, int] = {}
    original_spawn = pm.spawn

    def spawn(task_def, agent_def, work_dir, log_dir):
        info = original_spawn(task_def, agent_def, work_dir, log_dir)
        pids[task_def.id] = info.pid
        if task_def.id == "a":
            pm.complete(info.pid, 1)  # "a" crashes; "b" is left running (never completed).
        return info

    pm.spawn = spawn

    result = executor.execute_iteration(loop_state, loop_def, pm, clock)

    assert result.completed is False
    assert result.failure_reason == FailureReason.CRASH_LIMIT_EXCEEDED
    assert result.failed_steps == ["a"]
    assert loop_state.loop_failed_iterations == 1
    assert loop_state.inner_task_states["c"].status == TaskStatus.CANCELLED
    assert loop_state.inner_task_states["b"].status == TaskStatus.FAILED
    assert len(atropos.calls) == 1
    assert atropos.calls[0][0] == "loop-1.b"
    assert atropos.calls[0][2] == FailureReason.CRASH_LIMIT_EXCEEDED


def test_inner_step_hang_triggers_cleanup_via_atropos():
    a = TaskDef(id="a", agent="agent-a", command="sleep 999", deps=[], timeout=10)
    loop_def = LoopDef(id="loop-1", max_iterations=3, terminate_on="", inner_steps=[a])
    loop_state = fresh_state(loop_def)
    # A non-zero poll_interval_seconds is essential here: execute_iteration's
    # polling while-loop calls time_provider.sleep(poll_interval_seconds) on
    # every pass, which is what advances FakeTimeProvider's clock past the
    # inner step's timeout. (A previous version of this test advanced the
    # clock inside a mocked spawn() instead — but dispatch() records
    # started_at *after* spawn() returns, so started_at was already-advanced
    # and now - started_at never exceeded the timeout with
    # poll_interval_seconds=0.0, causing an infinite busy-loop.)
    executor, atropos = make_executor(poll_interval_seconds=5.0)
    pm = FakeProcessManager()  # never completes "a" -- it hangs.
    clock = FakeTimeProvider()

    result = executor.execute_iteration(loop_state, loop_def, pm, clock)

    assert result.completed is False
    assert result.failure_reason == FailureReason.TIMEOUT_EXCEEDED
    assert result.failed_steps == ["a"]
    assert len(atropos.calls) == 1
    assert atropos.calls[0][0] == "loop-1.a"
    assert atropos.calls[0][2] == FailureReason.TIMEOUT_EXCEEDED


def test_loop_timeout_exceeded_short_circuits_before_iterating():
    loop_def = review_loop_def()
    loop_state = fresh_state(loop_def)
    clock = FakeTimeProvider()
    loop_state.loop_timeout = clock.now() - 1  # deadline already in the past
    executor, atropos = make_executor()
    pm = FakeProcessManager()

    result = executor.execute_iteration(loop_state, loop_def, pm, clock)

    assert result.completed is False
    assert result.failure_reason == FailureReason.TIMEOUT_EXCEEDED
    assert loop_state.current_iteration == 0  # never incremented
    assert atropos.calls == []


def test_counter_controlled_loop_never_checks_terminate_on():
    """terminate_on='' means a counter-controlled loop: terminate_on_met is
    always False, regardless of leaf output content."""
    loop_def = review_loop_def(terminate_on="")
    loop_state = fresh_state(loop_def)
    executor, _ = make_executor()
    pm = FakeProcessManager()
    clock = FakeTimeProvider()
    auto_complete_spawn(pm, {"review": ["APPROVED"]})

    result = executor.execute_iteration(loop_state, loop_def, pm, clock)

    assert result.terminate_on_met is False
