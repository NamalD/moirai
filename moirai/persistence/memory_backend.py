"""MemoryBackend — in-memory PersistenceBackend implementation.

MVP persistence is in-memory only (per CLAUDE.md / SPEC.md §23 MVP scope);
file-based persistence (§18) is post-MVP.
"""

import copy
from contextlib import contextmanager
from typing import Iterator, Optional

from moirai.types import ExecutionState, TaskState

CURRENT_SCHEMA_VERSION = 4


class MemoryBackend:
    """In-memory implementation of the PersistenceBackend protocol.

    State does not survive process restart — intended for single-run
    execution and testing, not production durability.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, TaskState]] = {}
        self._execution_states: dict[str, ExecutionState] = {}
        self._schema_version: int = CURRENT_SCHEMA_VERSION
        self._in_transaction = False

    def get_task(self, workflow_id: str, task_id: str) -> Optional[TaskState]:
        return self._tasks.get(workflow_id, {}).get(task_id)

    def set_task(self, workflow_id: str, task_id: str, state: TaskState) -> None:
        self._tasks.setdefault(workflow_id, {})[task_id] = state

    def list_tasks(self, workflow_id: str) -> list[TaskState]:
        return list(self._tasks.get(workflow_id, {}).values())

    def get_execution_state(self, workflow_id: str) -> Optional[ExecutionState]:
        return self._execution_states.get(workflow_id)

    def set_execution_state(self, state: ExecutionState) -> None:
        self._execution_states[state.workflow_id] = state

    @contextmanager
    def atomic_transaction(self) -> Iterator[None]:
        """All-or-nothing writes: snapshot state, roll back on exception.

        Nested transactions are not supported — a transaction already in
        progress raises, since the isolation guarantee would otherwise be
        silently violated by an inner commit succeeding before an outer
        rollback.
        """
        if self._in_transaction:
            raise RuntimeError("atomic_transaction() does not support nesting")

        snapshot_tasks = copy.deepcopy(self._tasks)
        snapshot_states = copy.deepcopy(self._execution_states)
        self._in_transaction = True
        try:
            yield
        except BaseException:
            self._tasks = snapshot_tasks
            self._execution_states = snapshot_states
            raise
        finally:
            self._in_transaction = False

    def health_check(self) -> bool:
        return True

    def get_schema_version(self) -> int:
        return self._schema_version

    def set_schema_version(self, version: int) -> None:
        self._schema_version = version
