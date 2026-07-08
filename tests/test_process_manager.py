"""Tests for SubprocessProcessManager against real OS processes (SPEC.md §9)."""

import os
import signal
import time

import pytest

from moirai.process_manager import SubprocessProcessManager
from moirai.types import AgentDef, TaskDef

AGENT = AgentDef(id="agent-a", name="Agent A", command="/bin/true")


def test_spawn_and_poll_short_lived_command(tmp_path):
    pm = SubprocessProcessManager()
    task = TaskDef(id="t1", agent="agent-a", command="echo hello-moirai")
    info = pm.spawn(task, AGENT, work_dir=str(tmp_path), log_dir=str(tmp_path / "logs"))

    for _ in range(50):
        exit_code = pm.poll(info)
        if exit_code is not None:
            break
        time.sleep(0.05)

    assert exit_code == 0
    stdout, stderr = pm.read_output(info)
    assert "hello-moirai" in stdout


def test_spawn_captures_nonzero_exit_code(tmp_path):
    pm = SubprocessProcessManager()
    task = TaskDef(id="t1", agent="agent-a", command="exit 7")
    info = pm.spawn(task, AGENT, work_dir=str(tmp_path), log_dir=str(tmp_path / "logs"))

    exit_code = pm.wait(info, timeout=5)
    assert exit_code == 7


def test_spawn_runs_in_specified_work_dir(tmp_path):
    pm = SubprocessProcessManager()
    task = TaskDef(id="t1", agent="agent-a", command="pwd")
    info = pm.spawn(task, AGENT, work_dir=str(tmp_path), log_dir=str(tmp_path / "logs"))
    pm.wait(info, timeout=5)
    stdout, _ = pm.read_output(info)
    assert stdout.strip() == str(tmp_path)


def test_env_is_allowlisted_not_inherited(tmp_path, monkeypatch):
    monkeypatch.setenv("MOIRAI_TEST_SECRET", "should-not-leak")
    pm = SubprocessProcessManager()
    task = TaskDef(id="t1", agent="agent-a", command="env")
    info = pm.spawn(task, AGENT, work_dir=str(tmp_path), log_dir=str(tmp_path / "logs"))
    pm.wait(info, timeout=5)
    stdout, _ = pm.read_output(info)
    assert "MOIRAI_TEST_SECRET" not in stdout
    assert "PATH=" in stdout


def test_task_env_overrides_are_passed_through(tmp_path):
    pm = SubprocessProcessManager()
    task = TaskDef(
        id="t1",
        agent="agent-a",
        command="echo $MOIRAI_LOOP_ITERATION",
        env={"MOIRAI_LOOP_ITERATION": "3"},
    )
    info = pm.spawn(task, AGENT, work_dir=str(tmp_path), log_dir=str(tmp_path / "logs"))
    pm.wait(info, timeout=5)
    stdout, _ = pm.read_output(info)
    assert stdout.strip() == "3"


def test_signal_kills_entire_process_group(tmp_path):
    pm = SubprocessProcessManager()
    # A shell child that spawns a grandchild `sleep` — killpg must reach both.
    task = TaskDef(id="t1", agent="agent-a", command="sleep 60 & wait")
    info = pm.spawn(task, AGENT, work_dir=str(tmp_path), log_dir=str(tmp_path / "logs"))

    time.sleep(0.2)  # let the grandchild `sleep` actually start
    pm.signal(info, signal.SIGKILL)

    exit_code = pm.wait(info, timeout=5)
    assert exit_code != 0

    # The process group should now be empty — no leaked `sleep` grandchild.
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.killpg(info.pgid, 0)


def test_poll_returns_none_for_still_running_process(tmp_path):
    pm = SubprocessProcessManager()
    task = TaskDef(id="t1", agent="agent-a", command="sleep 5")
    info = pm.spawn(task, AGENT, work_dir=str(tmp_path), log_dir=str(tmp_path / "logs"))
    try:
        assert pm.poll(info) is None
    finally:
        pm.signal(info, signal.SIGKILL)
        pm.wait(info, timeout=5)
