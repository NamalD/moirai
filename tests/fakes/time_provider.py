"""FakeTimeProvider — manual time advancement for deterministic tests (SPEC.md §19.4)."""


class FakeTimeProvider:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        # No real blocking in tests — just advance the fake clock.
        self._now += seconds

    def advance(self, seconds: float) -> None:
        self._now += seconds
