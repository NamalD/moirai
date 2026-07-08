"""FakeProcessManager — controllable ProcessManager test double (SPEC.md §19.4)."""

from typing import Optional

from moirai.types import AgentDef, ProcessInfo, TaskDef


class FakeProcessManager:
    """In-memory ProcessManager double. No real OS processes are spawned.

    Tests drive completion explicitly via `complete(pid, exit_code)` —
    until then, `poll()` reports the process as still running (mirrors a
    hang, for hang-detection tests).
    """

    def __init__(self) -> None:
        self.spawned: list[ProcessInfo] = []
        self.signals_received: dict[int, list[int]] = {}
        self._next_pid = 1000
        self._exit_codes: dict[int, Optional[int]] = {}
        self._killed: set[int] = set()

    def spawn(
        self, task_def: TaskDef, agent_def: AgentDef, work_dir: str, log_dir: str
    ) -> ProcessInfo:
        pid = self._next_pid
        self._next_pid += 1
        info = ProcessInfo(
            pid=pid,
            pgid=pid,
            start_time=0.0,
            command=task_def.command,
            stdout_path=f"/fake/{pid}.stdout",
            stderr_path=f"/fake/{pid}.stderr",
        )
        self._exit_codes[pid] = None
        self.spawned.append(info)
        return info

    def poll(self, process: ProcessInfo) -> Optional[int]:
        return self._exit_codes.get(process.pid)

    def wait(self, process: ProcessInfo, timeout: float) -> int:
        code = self._exit_codes.get(process.pid)
        if code is None:
            raise TimeoutError(f"fake process {process.pid} has not exited")
        return code

    def signal(self, process: ProcessInfo, sig: int) -> None:
        self.signals_received.setdefault(process.pid, []).append(sig)

    def read_output(self, process: ProcessInfo) -> tuple[str, str]:
        return f"stdout for {process.pid}", f"stderr for {process.pid}"

    # ─── Test control surface ───────────────────────────────────────

    def complete(self, pid: int, exit_code: int) -> None:
        self._exit_codes[pid] = exit_code

    def mark_killed(self, pid: int) -> None:
        """Simulate a successful SIGTERM/SIGKILL — process now reports exited."""
        self._killed.add(pid)
        self._exit_codes[pid] = -15
