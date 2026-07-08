"""Tests for Lachesis (SPEC.md §7.4, §19.1)."""

import pytest

from moirai.lachesis import Lachesis
from moirai.persistence import MemoryBackend
from moirai.types import (
    AgentDef,
    FailureReason,
    LoopDef,
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


def test_rejects_state_machine_with_loop_tasks():
    sm = StateMachine(
        workflow_id="wf-1",
        version=1,
        tasks={},
        loop_tasks={"loop-1": LoopDef(id="loop-1")},
        dependencies={"loop-1": []},
        entry_points=["loop-1"],
    )
    with pytest.raises(NotImplementedError):
        make_lachesis(sm)


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
