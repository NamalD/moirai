"""TimeProvider implementation — real wall-clock time (SPEC.md §4.5)."""

import time


class SystemTimeProvider:
    """Real time source backed by the stdlib `time` module."""

    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
