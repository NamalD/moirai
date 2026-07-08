"""FakeAtropos — Lachesis's HangCleaner dependency, faked for Phase 3 tests
independent of Phase 4's real Atropos implementation.
"""

from moirai.types import CleanupOutcome, CleanupResult, FailureReason, ProcessInfo


class FakeAtropos:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ProcessInfo, FailureReason]] = []

    def cleanup(
        self, task_id: str, process_info: ProcessInfo, failure_reason: FailureReason
    ) -> CleanupResult:
        self.calls.append((task_id, process_info, failure_reason))
        return CleanupResult(
            outcome=CleanupOutcome.KILLED,
            pid=process_info.pid,
            details=f"fake cleanup of {task_id} ({failure_reason.name})",
        )
