"""Tests for MemoryBackend (SPEC.md §4.2, §19.1)."""

import pytest

from moirai.persistence import MemoryBackend
from moirai.types import ExecutionState, TaskState, TaskStatus


def test_get_task_missing_returns_none():
    backend = MemoryBackend()
    assert backend.get_task("wf-1", "t1") is None


def test_set_and_get_task_roundtrip():
    backend = MemoryBackend()
    state = TaskState(task_id="t1", status=TaskStatus.RUNNING, attempts=1)
    backend.set_task("wf-1", "t1", state)
    assert backend.get_task("wf-1", "t1") == state


def test_list_tasks_returns_all_tasks_for_workflow():
    backend = MemoryBackend()
    backend.set_task("wf-1", "t1", TaskState(task_id="t1"))
    backend.set_task("wf-1", "t2", TaskState(task_id="t2"))
    backend.set_task("wf-2", "t3", TaskState(task_id="t3"))
    tasks = backend.list_tasks("wf-1")
    assert {t.task_id for t in tasks} == {"t1", "t2"}


def test_list_tasks_empty_workflow():
    backend = MemoryBackend()
    assert backend.list_tasks("nonexistent") == []


def test_execution_state_roundtrip():
    backend = MemoryBackend()
    state = ExecutionState(workflow_id="wf-1", tasks={}, current_sm_version=1)
    backend.set_execution_state(state)
    assert backend.get_execution_state("wf-1") == state
    assert backend.get_execution_state("wf-missing") is None


def test_schema_version_roundtrip():
    backend = MemoryBackend()
    assert backend.get_schema_version() == 4
    backend.set_schema_version(5)
    assert backend.get_schema_version() == 5


def test_health_check_always_true_for_memory_backend():
    assert MemoryBackend().health_check() is True


def test_atomic_transaction_commits_on_success():
    backend = MemoryBackend()
    with backend.atomic_transaction():
        backend.set_task("wf-1", "t1", TaskState(task_id="t1", status=TaskStatus.COMPLETED))
    assert backend.get_task("wf-1", "t1").status == TaskStatus.COMPLETED


def test_atomic_transaction_rolls_back_on_exception():
    backend = MemoryBackend()
    backend.set_task("wf-1", "t1", TaskState(task_id="t1", status=TaskStatus.PENDING))

    with pytest.raises(ValueError):
        with backend.atomic_transaction():
            backend.set_task("wf-1", "t1", TaskState(task_id="t1", status=TaskStatus.RUNNING))
            backend.set_task("wf-1", "t2", TaskState(task_id="t2", status=TaskStatus.RUNNING))
            raise ValueError("simulated failure mid-transaction")

    # Both the modified existing task and the newly-added task must be rolled back.
    assert backend.get_task("wf-1", "t1").status == TaskStatus.PENDING
    assert backend.get_task("wf-1", "t2") is None


def test_atomic_transaction_does_not_support_nesting():
    backend = MemoryBackend()
    with pytest.raises(RuntimeError):
        with backend.atomic_transaction():
            with backend.atomic_transaction():
                pass
