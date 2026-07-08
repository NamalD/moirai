"""Atropos — cleanup / process termination (SPEC.md §7.6).

When Lachesis decides a task is hanging (crashed past max_retries, or
running past its timeout), Atropos kills the entire process tree, archives
its logs, and escalates to a human. Atropos does not attempt to fix or
retry the task itself — it only cleans up and escalates.
"""

import logging
import os
import signal
from datetime import datetime, timedelta, timezone
from typing import Optional

from moirai.protocols import HumanNotifier, ProcessManager, TimeProvider
from moirai.types import (
    CleanupConfig,
    CleanupOutcome,
    CleanupResult,
    FailureReason,
    LogArchive,
    ProcessInfo,
)

logger = logging.getLogger("moirai.atropos")


class Atropos:
    """Kills hanging tasks, archives their logs, and escalates to a human.

    One Atropos instance is bound to a single workflow_id, matching the
    "one Lachesis instance per workflow" assumption (SPEC.md §20.6) that
    Lachesis itself already relies on — this keeps the HangCleaner
    protocol Lachesis depends on free of a workflow_id parameter.
    """

    def __init__(
        self,
        workflow_id: str,
        process_manager: ProcessManager,
        human_notifier: HumanNotifier,
        time_provider: TimeProvider,
        config: Optional[CleanupConfig] = None,
        log_dir: str = "/tmp/moirai-logs",
    ) -> None:
        self._workflow_id = workflow_id
        self._process_manager = process_manager
        self._human_notifier = human_notifier
        self._time_provider = time_provider
        self._config = config or CleanupConfig()
        self._log_dir = log_dir

    def cleanup(
        self, task_id: str, process_info: ProcessInfo, failure_reason: FailureReason
    ) -> CleanupResult:
        outcome = self._kill_process_group(process_info)
        log_archive = self._archive_logs(task_id, process_info)
        self._record_failure_report(task_id, process_info, failure_reason, outcome, log_archive)
        self._request_human_intervention(task_id, failure_reason, log_archive)

        details = f"{outcome.name}: pid={process_info.pid} reason={failure_reason.name}"
        return CleanupResult(
            outcome=outcome,
            pid=process_info.pid,
            log_archive_path=log_archive.archive_path,
            details=details,
        )

    # ─── Kill sequence (SPEC.md §7.6 steps 1-5) ─────────────────────

    def _kill_process_group(self, process_info: ProcessInfo) -> CleanupOutcome:
        if self._process_manager.poll(process_info) is not None:
            return CleanupOutcome.ALREADY_DEAD

        try:
            self._process_manager.signal(process_info, signal.SIGTERM)
        except ProcessLookupError:
            return CleanupOutcome.ALREADY_DEAD

        self._time_provider.sleep(self._config.sigterm_grace_seconds)
        if self._process_manager.poll(process_info) is not None:
            return CleanupOutcome.KILLED

        for _ in range(self._config.kill_retry_count):
            try:
                self._process_manager.signal(process_info, signal.SIGKILL)
            except ProcessLookupError:
                return CleanupOutcome.FORCE_KILLED
            except PermissionError:
                pass  # fall through to retry delay below
            self._time_provider.sleep(self._config.kill_retry_delay_seconds)
            if self._process_manager.poll(process_info) is not None:
                return CleanupOutcome.FORCE_KILLED

        return CleanupOutcome.FAILED

    # ─── Log capture & archiving (SPEC.md §7.6 steps 6-7) ───────────

    def _archive_logs(self, task_id: str, process_info: ProcessInfo) -> LogArchive:
        stdout, stderr = self._process_manager.read_output(process_info)
        timestamp = self._time_provider.now()
        archive_dir = os.path.join(
            self._log_dir, self._workflow_id, task_id, f"{timestamp:.6f}"
        )
        os.makedirs(archive_dir, exist_ok=True)
        with open(os.path.join(archive_dir, "stdout.log"), "w") as f:
            f.write(stdout)
        with open(os.path.join(archive_dir, "stderr.log"), "w") as f:
            f.write(stderr)

        retained_until = (
            datetime.fromtimestamp(timestamp, tz=timezone.utc)
            + timedelta(days=self._config.log_retention_days)
        ).date().isoformat()

        return LogArchive(
            workflow_id=self._workflow_id,
            task_id=task_id,
            stdout_path=process_info.stdout_path,
            stderr_path=process_info.stderr_path,
            archive_path=archive_dir,
            retained_until=retained_until,
        )

    # ─── Failure report & human escalation (SPEC.md §7.6 steps 8-10) ─

    def _record_failure_report(
        self,
        task_id: str,
        process_info: ProcessInfo,
        failure_reason: FailureReason,
        outcome: CleanupOutcome,
        log_archive: LogArchive,
    ) -> None:
        logger.warning(
            "task_hang_cleanup",
            extra={
                "workflow_id": self._workflow_id,
                "task_id": task_id,
                "pid": process_info.pid,
                "command": process_info.command,
                "failure_reason": failure_reason.name,
                "cleanup_outcome": outcome.name,
                "log_archive_path": log_archive.archive_path,
            },
        )
        if outcome == CleanupOutcome.FAILED:
            logger.warning(
                "atropos_cleanup_failed: could not terminate pid=%s after %d SIGKILL retries",
                process_info.pid,
                self._config.kill_retry_count,
            )

    def _request_human_intervention(
        self, task_id: str, failure_reason: FailureReason, log_archive: LogArchive
    ) -> str:
        reason = f"Task '{task_id}' failed: {failure_reason.name}"
        return self._human_notifier.request_intervention(
            workflow_id=self._workflow_id,
            task_id=task_id,
            reason=reason,
            logs=log_archive.archive_path,
        )
