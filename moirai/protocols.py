"""Protocol interfaces — component boundaries, so fakes can be swapped in for tests.

See docs/architecture/initial-build/SPEC.md §4 for the authoritative definitions.
"""

from typing import ContextManager, Optional, Protocol

from moirai.types import (
    AgentDef,
    ExecutionState,
    HumanDecision,
    LoopDef,
    LoopIterationResult,
    LoopTaskState,
    ProcessInfo,
    TaskDef,
    TaskState,
)


class LLMClient(Protocol):
    """Interface for LLM calls used by Clotho and Themis.

    Implementations may wrap OpenAI, Anthropic, local models, or be a
    FakeLLMClient for testing.
    """

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout_seconds: int = 120,
    ) -> str:
        """Send a prompt to the LLM and return the text response.

        Raises:
            TimeoutError: If the LLM does not respond within timeout_seconds.
            ConnectionError: If the LLM endpoint is unreachable.
            RateLimitError: If the API rate limit is exceeded.
        """
        ...


class LLMRateLimiter(Protocol):
    """Rate limiter for LLM calls to prevent exceeding API quotas."""

    def acquire(self) -> None:
        """Block until a request slot is available."""
        ...

    def release(self) -> None:
        """Release a request slot."""
        ...


class CircuitBreaker(Protocol):
    """Circuit breaker for LLM API calls — prevents hammering a failing endpoint."""

    def call(self, fn, *args, **kwargs):
        """Execute fn if circuit is closed; raise CircuitOpenError if open."""
        ...


class PersistenceBackend(Protocol):
    """Storage interface for tracking task states.

    Must provide atomic read/write operations. The file backend uses
    atomic rename (os.replace) on POSIX-compliant local filesystems.
    NFS v3 and FAT32/exFAT do NOT guarantee atomic rename — operators
    should use SQLite backend or a POSIX-local filesystem.
    """

    def get_task(self, workflow_id: str, task_id: str) -> Optional[TaskState]: ...

    def set_task(self, workflow_id: str, task_id: str, state: TaskState) -> None: ...

    def list_tasks(self, workflow_id: str) -> list[TaskState]: ...

    def get_execution_state(self, workflow_id: str) -> Optional[ExecutionState]: ...

    def set_execution_state(self, state: ExecutionState) -> None: ...

    def atomic_transaction(self) -> ContextManager:
        """Context manager providing atomic all-or-nothing writes.

        If an exception occurs inside the context, all writes are discarded.
        On success exit, all writes are committed atomically.
        """
        ...

    def health_check(self) -> bool:
        """Verify the backend is operational (can read/write)."""
        ...

    def get_schema_version(self) -> int: ...

    def set_schema_version(self, version: int) -> None: ...


class ProcessManager(Protocol):
    """Abstraction over OS process management for testability."""

    def spawn(
        self, task_def: TaskDef, agent_def: AgentDef, work_dir: str, log_dir: str
    ) -> ProcessInfo:
        """Spawn a task as a child process with process-group isolation.

        The child is placed in a new process group (os.setpgid) so that
        Atropos can kill the entire process tree via os.killpg.
        """
        ...

    def poll(self, process: ProcessInfo) -> Optional[int]:
        """Check if process has exited. Returns exit code or None."""
        ...

    def wait(self, process: ProcessInfo, timeout: float) -> int:
        """Wait for process to exit. Returns exit code. Raises TimeoutError."""
        ...

    def signal(self, process: ProcessInfo, sig: int) -> None:
        """Send a signal to the process group (os.killpg)."""
        ...

    def read_output(self, process: ProcessInfo) -> tuple[str, str]:
        """Read captured stdout/stderr from log files."""
        ...


class HumanNotifier(Protocol):
    """Interface for requesting and polling human decisions."""

    def request_intervention(
        self,
        workflow_id: str,
        task_id: Optional[str],
        reason: str,
        logs: Optional[str] = None,
    ) -> str:
        """Raise a human intervention request.

        Returns a request ID that can be used to poll for the decision.
        The notification mechanism is implementation-defined (file signal,
        stdout message, HTTP callback, email).
        """
        ...

    def poll_decision(
        self,
        request_id: str,
        timeout_seconds: float = 86400.0,  # Default 24h
    ) -> Optional[HumanDecision]:
        """Poll for a human decision.

        Returns None if no decision has been made yet.
        Raises TimeoutError if the timeout expires without a decision
        (the default fallback is HumanDecision.ABORT).
        """
        ...

    def cancel_request(self, request_id: str) -> None: ...


class TimeProvider(Protocol):
    """Abstract time source for testing time-dependent behavior."""

    def now(self) -> float:
        """Current time in Unix seconds."""
        ...

    def sleep(self, seconds: float) -> None:
        """Block for the given duration (or advance fake time in tests)."""
        ...


class TaskInvestigator(Protocol):
    """Bounded context for Clotho to investigate a hanging task.

    Clotho does NOT have unbounded system access — it can only use
    the methods below to gather information.
    """

    def read_logs(self, task_id: str, max_lines: int = 200) -> str: ...

    def get_task_state(self, task_id: str) -> Optional[TaskState]: ...

    def list_workflow_tasks(self) -> list[TaskState]: ...

    def get_workflow_context(self) -> dict: ...


class LoopExecutor(Protocol):
    """Standalone loop iteration manager — extracted from Lachesis for testability.

    LoopExecutor handles the inner iteration lifecycle of a loop step.
    It receives loop state and process-management infrastructure, and
    returns iteration outcomes. Lachesis delegates loop step management
    to this component rather than embedding it inline.
    """

    def execute_iteration(
        self,
        loop_state: LoopTaskState,
        loop_def: LoopDef,
        process_manager: "ProcessManager",
        time_provider: "TimeProvider",
    ) -> LoopIterationResult:
        """Execute one iteration of inner steps.

        Spawns inner steps, polls for completion, handles inner step
        failures, checks terminate_on, and returns the iteration result.
        Inner step hang detection is handled here, not in Lachesis's
        main polling loop.
        """
        ...

    def check_terminate_on(self, output: str, condition: str) -> bool:
        """Pure function: does 'output' match 'condition'?

        Uses whole-word matching (\\bCONDITION\\b) rather than bare
        substring matching to prevent false positives.
        """
        ...

    def build_iteration_context(
        self, previous_outputs: dict[str, str], current_iteration: int
    ) -> dict[str, str]:
        """Build context dict for the next iteration from previous outputs.

        Returns a dict of environment variable overrides:
        - MOIRAI_LOOP_ITERATION=N
        - MOIRAI_PREV_OUTPUT=<final step output>
        - MOIRAI_PREV_OUTPUTS_<step_id>=<output> for each step
        """
        ...
