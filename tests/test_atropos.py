"""Tests for Atropos (SPEC.md §7.6, §19.1)."""

import os
import signal
from typing import Optional

import pytest

from moirai.atropos import Atropos
from moirai.types import CleanupConfig, CleanupOutcome, FailureReason, ProcessInfo
from tests.fakes.human_notifier import FakeHumanNotifier
from tests.fakes.time_provider import FakeTimeProvider


class ScriptedProcessManager:
    """Controllable ProcessManager double for exercising Atropos's kill sequence."""

    def __init__(self, dies_on=None):
        """dies_on: None (never dies), "SIGTERM", or ("SIGKILL", n) meaning
        the process dies on the nth SIGKILL signal.
        """
        self.signals_sent: list[int] = []
        self._dead = False
        self._dies_on = dies_on
        self.raise_on_signal: Optional[type] = None

    def poll(self, process_info: ProcessInfo):
        return 0 if self._dead else None

    def signal(self, process_info: ProcessInfo, sig: int) -> None:
        if self.raise_on_signal is not None:
            raise self.raise_on_signal()
        self.signals_sent.append(sig)
        if self._dies_on == "SIGTERM" and sig == signal.SIGTERM:
            self._dead = True
        elif (
            isinstance(self._dies_on, tuple)
            and self._dies_on[0] == "SIGKILL"
            and sig == signal.SIGKILL
            and self.signals_sent.count(signal.SIGKILL) >= self._dies_on[1]
        ):
            self._dead = True

    def read_output(self, process_info: ProcessInfo):
        return "captured stdout", "captured stderr"


PROCESS_INFO = ProcessInfo(
    pid=4242,
    pgid=4242,
    start_time=1_000_000.0,
    command="echo hi",
    stdout_path="/fake/4242.stdout",
    stderr_path="/fake/4242.stderr",
)


def make_atropos(pm, tmp_path, config=None):
    human_notifier = FakeHumanNotifier()
    time_provider = FakeTimeProvider()
    atropos = Atropos(
        workflow_id="wf-1",
        process_manager=pm,
        human_notifier=human_notifier,
        time_provider=time_provider,
        config=config or CleanupConfig(sigterm_grace_seconds=1, kill_retry_delay_seconds=0.1),
        log_dir=str(tmp_path),
    )
    return atropos, human_notifier, time_provider


def test_already_dead_process_sends_no_signals(tmp_path):
    pm = ScriptedProcessManager(dies_on=None)
    pm._dead = True  # already exited before Atropos was invoked
    atropos, human_notifier, _ = make_atropos(pm, tmp_path)

    result = atropos.cleanup("t1", PROCESS_INFO, FailureReason.TIMEOUT_EXCEEDED)

    assert result.outcome == CleanupOutcome.ALREADY_DEAD
    assert pm.signals_sent == []
    assert len(human_notifier.requests) == 1


def test_dies_on_sigterm_reports_killed(tmp_path):
    pm = ScriptedProcessManager(dies_on="SIGTERM")
    atropos, human_notifier, _ = make_atropos(pm, tmp_path)

    result = atropos.cleanup("t1", PROCESS_INFO, FailureReason.TIMEOUT_EXCEEDED)

    assert result.outcome == CleanupOutcome.KILLED
    assert pm.signals_sent == [signal.SIGTERM]
    assert len(human_notifier.requests) == 1


def test_survives_sigterm_dies_on_first_sigkill(tmp_path):
    pm = ScriptedProcessManager(dies_on=("SIGKILL", 1))
    atropos, human_notifier, _ = make_atropos(pm, tmp_path)

    result = atropos.cleanup("t1", PROCESS_INFO, FailureReason.CRASH_LIMIT_EXCEEDED)

    assert result.outcome == CleanupOutcome.FORCE_KILLED
    assert pm.signals_sent == [signal.SIGTERM, signal.SIGKILL]


def test_survives_first_sigkill_dies_on_retry(tmp_path):
    pm = ScriptedProcessManager(dies_on=("SIGKILL", 2))
    atropos, human_notifier, _ = make_atropos(
        pm, tmp_path, config=CleanupConfig(sigterm_grace_seconds=0, kill_retry_count=3, kill_retry_delay_seconds=0)
    )

    result = atropos.cleanup("t1", PROCESS_INFO, FailureReason.CRASH_LIMIT_EXCEEDED)

    assert result.outcome == CleanupOutcome.FORCE_KILLED
    assert pm.signals_sent == [signal.SIGTERM, signal.SIGKILL, signal.SIGKILL]


def test_never_dies_reports_failed_after_retries_exhausted(tmp_path):
    pm = ScriptedProcessManager(dies_on=None)
    atropos, human_notifier, _ = make_atropos(
        pm, tmp_path, config=CleanupConfig(sigterm_grace_seconds=0, kill_retry_count=3, kill_retry_delay_seconds=0)
    )

    result = atropos.cleanup("t1", PROCESS_INFO, FailureReason.CRASH_LIMIT_EXCEEDED)

    assert result.outcome == CleanupOutcome.FAILED
    assert pm.signals_sent == [signal.SIGTERM, signal.SIGKILL, signal.SIGKILL, signal.SIGKILL]
    # Even total cleanup failure still escalates to a human.
    assert len(human_notifier.requests) == 1


def test_process_lookup_error_on_sigterm_reports_already_dead(tmp_path):
    pm = ScriptedProcessManager(dies_on=None)
    pm.raise_on_signal = ProcessLookupError
    atropos, human_notifier, _ = make_atropos(pm, tmp_path)

    result = atropos.cleanup("t1", PROCESS_INFO, FailureReason.TIMEOUT_EXCEEDED)

    assert result.outcome == CleanupOutcome.ALREADY_DEAD


def test_logs_are_archived_to_disk(tmp_path):
    pm = ScriptedProcessManager(dies_on="SIGTERM")
    atropos, _, _ = make_atropos(pm, tmp_path)

    result = atropos.cleanup("t1", PROCESS_INFO, FailureReason.TIMEOUT_EXCEEDED)

    assert result.log_archive_path is not None
    archive_dir = result.log_archive_path
    assert os.path.isdir(archive_dir)
    with open(os.path.join(archive_dir, "stdout.log")) as f:
        assert f.read() == "captured stdout"
    with open(os.path.join(archive_dir, "stderr.log")) as f:
        assert f.read() == "captured stderr"


def test_human_intervention_includes_task_and_reason(tmp_path):
    pm = ScriptedProcessManager(dies_on="SIGTERM")
    atropos, human_notifier, _ = make_atropos(pm, tmp_path)

    atropos.cleanup("build-step", PROCESS_INFO, FailureReason.LOOP_EXHAUSTED)

    assert len(human_notifier.requests) == 1
    req = human_notifier.requests[0]
    assert req["workflow_id"] == "wf-1"
    assert req["task_id"] == "build-step"
    assert "LOOP_EXHAUSTED" in req["reason"]
