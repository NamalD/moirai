"""ProcessManager — subprocess dispatch model (SPEC.md §9).

Tasks run as child OS processes spawned via subprocess.Popen, each placed
in its own process group (via start_new_session) so Atropos can kill the
entire process tree via os.killpg rather than just the immediate child.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from moirai.types import AgentDef, ProcessInfo, TaskDef

# Environment allowlist for spawned agent subprocesses (SPEC.md §9). We
# never pass os.environ through unmodified: an unattended agent running
# with bypassed permission prompts (e.g. claude-dev) must not be able to
# read Moirai's own secrets (§14) via a plain `printenv`. Anything a task
# needs beyond this must be declared explicitly via TaskDef.env.
_ENV_ALLOWLIST = ("PATH", "HOME")


class SubprocessProcessManager:
    """Real ProcessManager implementation backed by subprocess.Popen."""

    def __init__(self) -> None:
        self._handles: dict[int, subprocess.Popen] = {}

    def spawn(
        self, task_def: TaskDef, agent_def: AgentDef, work_dir: str, log_dir: str
    ) -> ProcessInfo:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        timestamp = time.time()
        stdout_path = os.path.join(log_dir, f"{timestamp:.6f}.stdout")
        stderr_path = os.path.join(log_dir, f"{timestamp:.6f}.stderr")

        env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
        env.update(task_def.env)

        stdout_f = open(stdout_path, "w")
        stderr_f = open(stderr_path, "w")
        try:
            process = subprocess.Popen(
                task_def.command,
                shell=True,
                cwd=work_dir,
                env=env,
                stdout=stdout_f,
                stderr=stderr_f,
                start_new_session=True,  # isolates the child in its own process group
            )
        finally:
            stdout_f.close()
            stderr_f.close()

        self._handles[process.pid] = process
        return ProcessInfo(
            pid=process.pid,
            pgid=os.getpgid(process.pid),
            start_time=timestamp,
            command=task_def.command,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    def poll(self, process: ProcessInfo) -> Optional[int]:
        handle = self._handles.get(process.pid)
        if handle is None:
            return None
        return handle.poll()

    def wait(self, process: ProcessInfo, timeout: float) -> int:
        handle = self._handles.get(process.pid)
        if handle is None:
            raise ValueError(f"No tracked process for pid {process.pid}")
        try:
            return handle.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"Process {process.pid} did not exit within {timeout}s"
            ) from exc

    def signal(self, process: ProcessInfo, sig: int) -> None:
        os.killpg(process.pgid, sig)

    def read_output(self, process: ProcessInfo) -> tuple[str, str]:
        stdout = self._read_file(process.stdout_path)
        stderr = self._read_file(process.stderr_path)
        return stdout, stderr

    @staticmethod
    def _read_file(path: str) -> str:
        try:
            with open(path) as f:
                return f.read()
        except FileNotFoundError:
            return ""
