"""Shared data structures — the contracts between every Moirai component.

See docs/architecture/initial-build/SPEC.md §3 for the authoritative definitions.
"""

from dataclasses import dataclass, field
from typing import Optional, Literal


# ─── Enums ──────────────────────────────────────────────────────────

from enum import Enum, auto


class TaskStatus(Enum):
    PENDING = auto()
    READY = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()
    SKIPPED = auto()


class HumanDecision(Enum):
    RETRY = auto()  # Re-attempt the failed/hanging task
    SKIP = auto()  # Mark task as skipped, continue workflow
    ABORT = auto()  # Abort the entire workflow
    RESTART = auto()  # Restart the workflow from scratch
    CONTINUE = auto()  # Accept current loop output as meeting terminate_on condition


class FailureReason(Enum):
    TIMEOUT_EXCEEDED = auto()
    CRASH_LIMIT_EXCEEDED = auto()
    CONSOLIDATION_FAILURE = auto()
    CLOTHO_TIMEOUT = auto()
    USER_ABORT = auto()
    LOOP_EXHAUSTED = auto()  # Loop step hit max_iterations without termination


class LoopStatus(Enum):
    """Status of a loop step's internal execution."""

    ITERATING = auto()  # Running inner steps
    COMPLETED = auto()  # terminate_on condition met (or max_iterations reached with no terminate_on set)
    EXHAUSTED = auto()  # max_iterations reached without termination (only when terminate_on is set and unmet)
    PENDING = auto()  # Not yet started
    CANCELLED = auto()


class CleanupOutcome(Enum):
    KILLED = auto()  # SIGTERM succeeded
    FORCE_KILLED = auto()  # SIGTERM failed, SIGKILL succeeded
    ALREADY_DEAD = auto()  # Process was already gone
    FAILED = auto()  # Could not terminate (permission, zombie)
    SKIPPED = auto()  # No process to clean up


class PersistenceBackendType(Enum):
    FILE = auto()
    MEMORY = auto()
    SQLITE = auto()


# ─── Core Data Types ────────────────────────────────────────────────


@dataclass
class AgentDef:
    """Definition of an agent that can execute tasks."""

    id: str  # Unique agent identifier
    name: str  # Human-readable name
    command: str  # Path to executable or command template
    env_vars: dict[str, str] = field(default_factory=dict)
    work_dir: Optional[str] = None
    max_concurrent_tasks: int = 1
    tags: list[str] = field(default_factory=list)


@dataclass
class TaskDef:
    """A task definition within a workflow YAML artifact."""

    id: str  # Stable task identifier (across YAML versions)
    agent: str  # References AgentDef.id
    command: str  # Shell command to execute
    type: str = "agent"  # "agent" (runs via LLM agent) or "script" (direct shell command)
    deps: list[str] = field(default_factory=list)  # Task IDs this task depends on
    timeout: int = 3600  # Seconds before deemed hanging
    max_retries: int = 3  # Times to auto-retry on crash
    env: dict[str, str] = field(default_factory=dict)
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)


@dataclass
class LoopDef:
    """A loop step definition within a workflow YAML artifact.

    A loop step is a node in the outer DAG that internally contains a
    sub-graph of steps executed in a bounded iteration loop.
    """

    id: str  # Stable task identifier
    type: Literal["loop"] = "loop"  # Discriminator from TaskDef
    max_iterations: int = 5  # Maximum number of iterations
    terminate_on: str = ""  # Empty = counter-controlled loop (runs exactly max_iterations, reports COMPLETED)
    deps: list[str] = field(default_factory=list)  # Outer DAG dependencies (opaque)
    inner_steps: list[TaskDef] = field(default_factory=list)  # Inner step definitions
    loop_timeout: Optional[int] = None  # Wall-clock timeout for entire loop step in seconds
    max_concurrent_inner: int = 1  # Max concurrent inner steps within a loop iteration


@dataclass
class ValidationError:
    """Structured error from validation (Themis or GraphValidator)."""

    field: str  # Dot-separated field path, e.g. "tasks.build.command"
    message: str  # Human-readable explanation
    severity: Literal["error", "warning"] = "error"
    yaml_line: Optional[int] = None  # Line number in the original YAML (if available)
    error_code: str = "UNKNOWN"  # Machine-readable error code
    task_id: Optional[str] = None  # Which task the error relates to


@dataclass
class ValidationResult:
    """Output of Themis.validate() / GraphValidator checks (SPEC §6, §7.2)."""

    state_machine: Optional["StateMachine"]
    errors: list[ValidationError] = field(default_factory=list)
    is_valid: bool = False


@dataclass
class StateMachine:
    """Formal representation of a workflow as a DAG of tasks.

    Themis produces this; Lachesis executes it; Penelope diffs it.
    """

    workflow_id: str  # Unique workflow identifier
    version: int  # Monotonically increasing per workflow
    tasks: dict[str, TaskDef]  # task_id -> TaskDef (regular task node map)
    loop_tasks: dict[str, LoopDef]  # task_id -> LoopDef (loop step node map)
    dependencies: dict[str, list[str]]  # task_id -> list of dependency task_ids
    entry_points: list[str]  # Tasks with no dependencies (zero in-degree)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class TaskState:
    """Current execution state of a single task."""

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0  # Number of times this task has been started
    started_at: Optional[float] = None  # Unix timestamp
    completed_at: Optional[float] = None
    exit_code: Optional[int] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    failure_reason: Optional[FailureReason] = None
    error_message: Optional[str] = None


@dataclass
class LoopTaskState:
    """Execution state for a loop step — tracks inner iteration progress.

    A loop step node in the outer DAG contains an internal sub-graph of steps.
    The outer DAG sees the loop step as a single opaque node; the inner steps
    execute per iteration.
    """

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    loop_status: LoopStatus = LoopStatus.PENDING
    current_iteration: int = 0  # 1-based, resets on PENDING
    max_iterations: int = 5  # Hard limit from step definition
    terminate_on: str = ""  # Condition string (empty = counter-controlled loop)
    last_inner_outputs: dict[str, str] = field(default_factory=dict)  # step_id -> output from last completed iteration
    last_inner_output: Optional[str] = None  # Deprecated alias — kept for persistence compatibility
    inner_task_states: dict[str, TaskState] = field(default_factory=dict)
    inner_execution_order: list[str] = field(default_factory=list)  # Cached topological order
    loop_timeout: Optional[int] = None  # Wall-clock deadline (absolute Unix timestamp) for entire loop
    loop_started_at: Optional[float] = None  # Unix timestamp when loop first entered ITERATING
    loop_failed_iterations: int = 0  # Cumulative count of iterations that failed
    iteration_log: list[dict] = field(default_factory=list)  # Persistent per-iteration record


@dataclass
class ExecutionState:
    """Snapshot of all task states in a workflow at a point in time."""

    workflow_id: str
    tasks: dict[str, TaskState]  # task_id -> TaskState (regular tasks)
    current_sm_version: int
    loop_tasks: dict[str, LoopTaskState] = field(default_factory=dict)  # task_id -> LoopTaskState


@dataclass
class ConsolidationError:
    reason: str
    task_id: Optional[str] = None
    details: str = ""


@dataclass
class ConsolidationPlan:
    """Result of comparing old and new state machines during mid-flight change."""

    new_tasks: list[str]  # Task IDs added in new SM
    removed_tasks: list[str]  # Task IDs absent from new SM
    unchanged_tasks: list[str]  # Task IDs with identical definition
    modified_tasks: dict[str, str]  # task_id -> "removed+added" reason
    state_transfers: dict[str, TaskStatus]  # task_id -> target status after consolidation
    can_consolidate: bool
    errors: list[ConsolidationError] = field(default_factory=list)


@dataclass
class TaskEvent:
    """Event emitted when a task transitions between states."""

    task_id: str
    from_status: TaskStatus
    to_status: TaskStatus
    timestamp: float
    details: Optional[str] = None


@dataclass
class ExecutionLog:
    """Full log of a workflow execution."""

    workflow_id: str
    start_time: float
    end_time: Optional[float] = None
    tasks: dict[str, TaskState] = field(default_factory=dict)
    events: list[TaskEvent] = field(default_factory=list)
    outcome: Optional[str] = None  # "success", "failed", "aborted", "cancelled"


@dataclass
class ProcessInfo:
    """Information about a task's OS process."""

    pid: int
    pgid: int  # Process group ID (for killpg cleanup)
    start_time: float
    command: str
    stdout_path: str
    stderr_path: str


@dataclass
class CleanupConfig:
    """Configuration for Atropos cleanup behavior."""

    sigterm_grace_seconds: int = 10
    kill_retry_count: int = 3  # Retries on failed SIGKILL
    kill_retry_delay_seconds: float = 1.0
    log_retention_days: int = 30


@dataclass
class CleanupResult:
    outcome: CleanupOutcome
    pid: int
    log_archive_path: Optional[str] = None
    details: str = ""


@dataclass
class LogArchive:
    """Reference to captured logs from a failed/hanging task."""

    workflow_id: str
    task_id: str
    stdout_path: str
    stderr_path: str
    archive_path: str  # Where logs were collected for investigation
    retained_until: Optional[str] = None  # ISO date of retention expiry


@dataclass
class AuditEntry:
    """Single entry in the append-only audit log."""

    timestamp: float
    event_type: str  # e.g. "task_completed", "human_escalation", "clotho_timeout"
    workflow_id: str
    task_id: Optional[str] = None
    details: dict = field(default_factory=dict)


@dataclass
class SchedulerConfig:
    """Configuration for Lachesis (SPEC §7.4)."""

    max_concurrent_tasks: int = 4  # Max tasks running simultaneously
    poll_interval_seconds: float = 1.0  # How often to check for ready tasks
    hang_check_interval_seconds: float = 5.0  # How often to check for hanging tasks
    crash_recovery_enabled: bool = True
    graceful_shutdown_timeout: float = 30.0


@dataclass
class LoopIterationResult:
    """Outcome of a single loop iteration (SPEC §4.7)."""

    completed: bool  # True if all inner steps completed (regardless of terminate_on)
    terminate_on_met: bool  # True if terminate_on condition matched
    inner_outputs: dict[str, str]  # step_id -> captured stdout
    final_output: str  # Concatenated output of leaf node(s)
    failed_steps: list[str]  # Inner step IDs that failed
    failure_reason: Optional[FailureReason] = None
