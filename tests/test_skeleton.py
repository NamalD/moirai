"""Phase 0 smoke tests: types and protocols import and construct correctly."""

from moirai import protocols, types


def test_task_def_defaults():
    task = types.TaskDef(id="t1", agent="a1", command="echo hi")
    assert task.type == "agent"
    assert task.deps == []
    assert task.timeout == 3600
    assert task.max_retries == 3


def test_state_machine_construction():
    task = types.TaskDef(id="t1", agent="a1", command="echo hi")
    sm = types.StateMachine(
        workflow_id="wf-1",
        version=1,
        tasks={"t1": task},
        loop_tasks={},
        dependencies={"t1": []},
        entry_points=["t1"],
    )
    assert sm.tasks["t1"] is task
    assert sm.entry_points == ["t1"]


def test_protocols_are_importable():
    assert protocols.PersistenceBackend is not None
    assert protocols.ProcessManager is not None
    assert protocols.TimeProvider is not None
    assert protocols.LoopExecutor is not None
    assert protocols.HumanNotifier is not None
    assert protocols.TaskInvestigator is not None
    assert protocols.LLMClient is not None
