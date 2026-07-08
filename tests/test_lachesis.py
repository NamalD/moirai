"""Tests for Lachesis (SPEC.md §7.4, §19.1)."""

import pytest

from moirai.lachesis import Lachesis
from moirai.persistence import MemoryBackend
from moirai.types import (
    AgentDef,
    FailureReason,
    LoopDef,
    LoopStatus,
    SchedulerConfig,
    StateMachine,
    TaskDef,
    TaskStatus,
)
from tests.fakes.atropos import FakeAtropos
from tests.fakes.human_notifier import FakeHumanNotifier
from tests.fakes.process_manager import FakeProcessManager
from tests.fakes.time_provider import FakeTimeProvider

AGENT = AgentDef(id="agent-a", name="Agent A", command="/bin/true")


def make_lachesis(state_machine, config=None, agents=None):
    persistence = MemoryBackend()
    process_manager = FakeProcessManager()
    atropos = FakeAtropos()
    human_notifier = FakeHumanNotifier()
    time_provider = FakeTimeProvider()
    lachesis = Lachesis(
        state_machine=state_machine,
        persistence=persistence,
        process_manager=process_manager,
        atropos=atropos,
        human_notifier=human_notifier,
        time_provider=time_provider,
        agents=agents or {"agent-a": AGENT},
        config=config or SchedulerConfig(max_concurrent_tasks=4, poll_interval_seconds=0.0),
    )
    return lachesis, persistence, process_manager, atropos, time_provider


def sm_linear() -> StateMachine:
    a = TaskDef(id="a", agent="agent-a", command="echo a", deps=[])
    b = TaskDef(id="b", agent="agent-a", command="echo b", deps=["a"])
    return StateMachine(
        workflow_id="wf-1",
        version=1,
        tasks={"a": a, "b": b},
        loop_tasks={},
        dependencies={"a": [], "b": ["a"]},
        entry_points=["a"],
    )


def test_dispatches_entry_point_first():
    sm = sm_linear()
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)

    # Drive one iteration manually via the internal helpers rather than run()
    # (which would spin forever without something completing tasks).
    lachesis._initialize_state()
    lachesis._dispatch_ready()
    assert "a" in lachesis._running
    assert "b" not in lachesis._running
    assert persistence.get_task("wf-1", "a").status == TaskStatus.RUNNING


def test_downstream_task_becomes_ready_after_dependency_completes():
    sm = sm_linear()
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)
    lachesis._initialize_state()
    lachesis._dispatch_ready()
    a_process = pm.spawned[0]
    pm.complete(a_process.pid, 0)
    lachesis._poll_running()
    assert persistence.get_task("wf-1", "a").status == TaskStatus.COMPLETED
    lachesis._dispatch_ready()
    assert "b" in lachesis._running


def test_full_run_completes_successfully():
    sm = sm_linear()
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)

    # Auto-complete every spawned process with exit code 0 on the next poll.
    original_spawn = pm.spawn

    def auto_spawn(task_def, agent_def, work_dir, log_dir):
        info = original_spawn(task_def, agent_def, work_dir, log_dir)
        pm.complete(info.pid, 0)
        return info

    pm.spawn = auto_spawn

    log = lachesis.run()
    assert log.outcome == "success"
    assert persistence.get_task("wf-1", "a").status == TaskStatus.COMPLETED
    assert persistence.get_task("wf-1", "b").status == TaskStatus.COMPLETED


def test_concurrency_limit_is_respected():
    a = TaskDef(id="a", agent="agent-a", command="echo a", deps=[])
    b = TaskDef(id="b", agent="agent-a", command="echo b", deps=[])
    c = TaskDef(id="c", agent="agent-a", command="echo c", deps=[])
    sm = StateMachine(
        workflow_id="wf-1",
        version=1,
        tasks={"a": a, "b": b, "c": c},
        loop_tasks={},
        dependencies={"a": [], "b": [], "c": []},
        entry_points=["a", "b", "c"],
    )
    lachesis, persistence, pm, atropos, clock = make_lachesis(
        sm, config=SchedulerConfig(max_concurrent_tasks=2, poll_interval_seconds=0.0)
    )
    lachesis._initialize_state()
    lachesis._dispatch_ready()
    assert len(lachesis._running) == 2


def test_crash_retries_up_to_max_retries_then_invokes_atropos():
    task = TaskDef(id="a", agent="agent-a", command="echo a", deps=[], max_retries=2)
    sm = StateMachine(
        workflow_id="wf-1",
        version=1,
        tasks={"a": task},
        loop_tasks={},
        dependencies={"a": []},
        entry_points=["a"],
    )
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)
    lachesis._initialize_state()

    # attempts=1: 1 < max_retries(2) -> retried (PENDING).
    lachesis._dispatch_ready()
    info = pm.spawned[-1]
    pm.complete(info.pid, 1)
    lachesis._poll_running()
    assert persistence.get_task("wf-1", "a").status == TaskStatus.PENDING
    assert len(atropos.calls) == 0

    # attempts=2: 2 < max_retries(2) is False -> crash limit exceeded.
    lachesis._dispatch_ready()
    info = pm.spawned[-1]
    pm.complete(info.pid, 1)
    lachesis._poll_running()

    assert len(atropos.calls) == 1
    assert atropos.calls[0][2] == FailureReason.CRASH_LIMIT_EXCEEDED
    assert persistence.get_task("wf-1", "a").status == TaskStatus.FAILED


def test_hang_detection_invokes_atropos_on_timeout():
    task = TaskDef(id="a", agent="agent-a", command="sleep 999", deps=[], timeout=10)
    sm = StateMachine(
        workflow_id="wf-1",
        version=1,
        tasks={"a": task},
        loop_tasks={},
        dependencies={"a": []},
        entry_points=["a"],
    )
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)
    lachesis._initialize_state()
    lachesis._dispatch_ready()

    clock.advance(11)
    lachesis._check_hangs()

    assert len(atropos.calls) == 1
    assert atropos.calls[0][2] == FailureReason.TIMEOUT_EXCEEDED
    assert persistence.get_task("wf-1", "a").status == TaskStatus.FAILED
    assert "a" not in lachesis._running


def test_cancellation_marks_pending_cancelled_and_kills_running():
    sm = sm_linear()
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)
    lachesis._initialize_state()
    lachesis._dispatch_ready()  # dispatches "a"

    lachesis.cancel()
    lachesis._do_cancel()

    assert persistence.get_task("wf-1", "b").status == TaskStatus.CANCELLED
    assert len(atropos.calls) == 1
    assert atropos.calls[0][2] == FailureReason.USER_ABORT
    assert persistence.get_task("wf-1", "a").status == TaskStatus.FAILED


def test_run_stops_when_blocked_with_nothing_running_or_ready():
    """If a task crashes past max_retries, its downstream never becomes ready.
    run() must terminate rather than spin forever once nothing is running
    and nothing is ready.
    """
    a = TaskDef(id="a", agent="agent-a", command="echo a", deps=[], max_retries=0)
    b = TaskDef(id="b", agent="agent-a", command="echo b", deps=["a"])
    sm = StateMachine(
        workflow_id="wf-1",
        version=1,
        tasks={"a": a, "b": b},
        loop_tasks={},
        dependencies={"a": [], "b": ["a"]},
        entry_points=["a"],
    )
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)

    original_spawn = pm.spawn

    def auto_fail_spawn(task_def, agent_def, work_dir, log_dir):
        info = original_spawn(task_def, agent_def, work_dir, log_dir)
        pm.complete(info.pid, 1)
        return info

    pm.spawn = auto_fail_spawn

    log = lachesis.run()
    assert log.outcome == "failed"
    assert persistence.get_task("wf-1", "a").status == TaskStatus.FAILED
    assert persistence.get_task("wf-1", "b").status == TaskStatus.PENDING


# ─── Loop step integration (Phase 5, SPEC.md §7.4 items 1-9) ───────────


def auto_complete_spawn(pm, outputs_by_task_id=None):
    """Wrap pm.spawn so every spawned process auto-completes with exit 0,
    optionally with a queued stdout string per task id (FIFO across
    iterations for steps re-run each loop iteration).
    """
    outputs_by_task_id = outputs_by_task_id or {}
    original_spawn = pm.spawn

    def spawn(task_def, agent_def, work_dir, log_dir):
        info = original_spawn(task_def, agent_def, work_dir, log_dir)
        queue = outputs_by_task_id.get(task_def.id)
        output = queue.pop(0) if queue else ""
        pm.set_output(info.pid, output, "")
        pm.complete(info.pid, 0)
        return info

    pm.spawn = spawn


def sm_with_loop(terminate_on="APPROVED", max_iterations=3, downstream=False) -> StateMachine:
    implement = TaskDef(id="implement", agent="agent-a", command="echo implement", deps=[])
    review = TaskDef(id="review", agent="agent-a", command="echo review", deps=["implement"])
    loop = LoopDef(
        id="dev-review",
        max_iterations=max_iterations,
        terminate_on=terminate_on,
        inner_steps=[implement, review],
    )
    tasks = {}
    dependencies = {"dev-review": []}
    entry_points = ["dev-review"]
    if downstream:
        deploy = TaskDef(id="deploy", agent="agent-a", command="echo deploy", deps=["dev-review"])
        tasks["deploy"] = deploy
        dependencies["deploy"] = ["dev-review"]
    return StateMachine(
        workflow_id="wf-1",
        version=1,
        tasks=tasks,
        loop_tasks={"dev-review": loop},
        dependencies=dependencies,
        entry_points=entry_points,
    )


def test_loop_step_completes_when_terminate_on_met_on_first_iteration():
    sm = sm_with_loop()
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)
    auto_complete_spawn(pm, {"review": ["APPROVED"]})

    log = lachesis.run()

    assert log.outcome == "success"
    assert persistence.get_task("wf-1", "dev-review").status == TaskStatus.COMPLETED
    assert lachesis._loop_states["dev-review"].loop_status == LoopStatus.COMPLETED
    assert lachesis._loop_states["dev-review"].current_iteration == 1


def test_loop_step_iterates_until_terminate_on_met():
    sm = sm_with_loop(max_iterations=5)
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)
    auto_complete_spawn(pm, {"review": ["REJECTED", "REJECTED", "APPROVED"]})

    log = lachesis.run()

    assert log.outcome == "success"
    assert persistence.get_task("wf-1", "dev-review").status == TaskStatus.COMPLETED
    assert lachesis._loop_states["dev-review"].current_iteration == 3


def test_loop_step_whole_word_matching_rejects_unapproved():
    sm = sm_with_loop(max_iterations=5)
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)
    auto_complete_spawn(pm, {"review": ["UNAPPROVED", "APPROVED"]})

    log = lachesis.run()

    assert log.outcome == "success"
    assert lachesis._loop_states["dev-review"].current_iteration == 2


def test_loop_step_exhaustion_marks_failed_and_escalates():
    sm = sm_with_loop(max_iterations=2)
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)
    auto_complete_spawn(pm, {"review": ["REJECTED", "REJECTED"]})

    log = lachesis.run()

    assert log.outcome == "failed"
    state = persistence.get_task("wf-1", "dev-review")
    assert state.status == TaskStatus.FAILED
    assert state.failure_reason == FailureReason.LOOP_EXHAUSTED
    assert lachesis._loop_states["dev-review"].loop_status == LoopStatus.EXHAUSTED
    assert len(lachesis._human_notifier.requests) == 1
    assert lachesis._human_notifier.requests[0]["task_id"] == "dev-review"


def test_counter_controlled_loop_completes_after_max_iterations():
    sm = sm_with_loop(terminate_on="", max_iterations=2)
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)
    auto_complete_spawn(pm)

    log = lachesis.run()

    assert log.outcome == "success"
    assert persistence.get_task("wf-1", "dev-review").status == TaskStatus.COMPLETED
    assert lachesis._loop_states["dev-review"].loop_status == LoopStatus.COMPLETED
    assert lachesis._loop_states["dev-review"].current_iteration == 2


def test_loop_step_inner_failure_marks_loop_failed_and_escalates():
    implement = TaskDef(id="implement", agent="agent-a", command="echo implement", deps=[], max_retries=0)
    review = TaskDef(id="review", agent="agent-a", command="echo review", deps=["implement"])
    loop = LoopDef(id="dev-review", max_iterations=3, terminate_on="APPROVED", inner_steps=[implement, review])
    sm = StateMachine(
        workflow_id="wf-1",
        version=1,
        tasks={},
        loop_tasks={"dev-review": loop},
        dependencies={"dev-review": []},
        entry_points=["dev-review"],
    )
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)

    original_spawn = pm.spawn

    def spawn(task_def, agent_def, work_dir, log_dir):
        info = original_spawn(task_def, agent_def, work_dir, log_dir)
        if task_def.id == "implement":
            pm.complete(info.pid, 1)  # crashes immediately, no retries left
        return info

    pm.spawn = spawn

    log = lachesis.run()

    assert log.outcome == "failed"
    state = persistence.get_task("wf-1", "dev-review")
    assert state.status == TaskStatus.FAILED
    assert state.failure_reason == FailureReason.CRASH_LIMIT_EXCEEDED
    assert len(lachesis._human_notifier.requests) == 1


def test_downstream_task_becomes_ready_after_loop_step_completes():
    sm = sm_with_loop(downstream=True)
    lachesis, persistence, pm, atropos, clock = make_lachesis(sm)
    auto_complete_spawn(pm, {"review": ["APPROVED"]})

    log = lachesis.run()

    assert log.outcome == "success"
    assert persistence.get_task("wf-1", "dev-review").status == TaskStatus.COMPLETED
    assert persistence.get_task("wf-1", "deploy").status == TaskStatus.COMPLETED
