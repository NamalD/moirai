"""Full pipeline integration test using only real components (SPEC.md §19.2).

No fakes anywhere: real Themis parses and validates real YAML, a real
Lachesis dispatches real OS subprocesses via SubprocessProcessManager,
using real wall-clock time and a real Atropos for the hang path. This is
the closest thing in the test suite to what the first live RSI dispatch
will actually do, so it's worth having this proven end-to-end rather than
only against fakes in the per-component test files.
"""

import os

from moirai.atropos import Atropos
from moirai.lachesis import Lachesis
from moirai.persistence import MemoryBackend
from moirai.process_manager import SubprocessProcessManager
from moirai.themis import Themis
from moirai.time_provider import SystemTimeProvider
from moirai.types import AgentDef, CleanupConfig, SchedulerConfig, TaskStatus


def test_two_task_shell_workflow_runs_to_completion(tmp_path):
    marker_file = tmp_path / "marker.txt"
    yaml_artifact = f"""
workflow:
  id: "wf-real"
  name: "Real pipeline smoke test"
  version: 1
  tasks:
    - id: "write"
      agent: "script-runner"
      command: "echo hello > {marker_file}"
      deps: []
    - id: "read"
      agent: "script-runner"
      command: "cat {marker_file}"
      deps: ["write"]
"""
    known_agents = [
        AgentDef(id="script-runner", name="Script Runner", command="/bin/bash")
    ]

    validation = Themis().validate(yaml_artifact, known_agents)
    assert validation.is_valid, validation.errors
    sm = validation.state_machine

    persistence = MemoryBackend()
    process_manager = SubprocessProcessManager()
    time_provider = SystemTimeProvider()
    atropos = Atropos(
        workflow_id=sm.workflow_id,
        process_manager=process_manager,
        human_notifier=_NoopHumanNotifier(),
        time_provider=time_provider,
        config=CleanupConfig(sigterm_grace_seconds=1),
        log_dir=str(tmp_path / "logs"),
    )
    lachesis = Lachesis(
        state_machine=sm,
        persistence=persistence,
        process_manager=process_manager,
        atropos=atropos,
        human_notifier=_NoopHumanNotifier(),
        time_provider=time_provider,
        agents={a.id: a for a in known_agents},
        config=SchedulerConfig(max_concurrent_tasks=2, poll_interval_seconds=0.05),
        default_work_dir=str(tmp_path),
        log_dir=str(tmp_path / "logs"),
    )

    log = lachesis.run()

    assert log.outcome == "success"
    assert persistence.get_task("wf-real", "write").status == TaskStatus.COMPLETED
    assert persistence.get_task("wf-real", "read").status == TaskStatus.COMPLETED
    read_state = persistence.get_task("wf-real", "read")
    with open(read_state.stdout_path) as f:
        assert "hello" in f.read()
    assert os.path.exists(marker_file)


class _NoopHumanNotifier:
    def request_intervention(self, workflow_id, task_id, reason, logs=None):
        return "noop"

    def poll_decision(self, request_id, timeout_seconds=86400.0):
        return None

    def cancel_request(self, request_id):
        pass
