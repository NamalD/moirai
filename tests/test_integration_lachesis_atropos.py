"""Integration test: real Atropos wired into real Lachesis (SPEC.md §19.2).

Confirms Atropos.cleanup() actually satisfies the HangCleaner protocol
shape Lachesis depends on, rather than just matching in isolation against
FakeAtropos.
"""

from moirai.atropos import Atropos
from moirai.lachesis import Lachesis
from moirai.persistence import MemoryBackend
from moirai.types import AgentDef, CleanupConfig, SchedulerConfig, StateMachine, TaskDef, TaskStatus
from tests.fakes.human_notifier import FakeHumanNotifier
from tests.fakes.process_manager import FakeProcessManager
from tests.fakes.time_provider import FakeTimeProvider

AGENT = AgentDef(id="agent-a", name="Agent A", command="/bin/true")


def test_hanging_task_is_cleaned_up_by_real_atropos(tmp_path):
    task = TaskDef(id="a", agent="agent-a", command="sleep 999", deps=[], timeout=10)
    sm = StateMachine(
        workflow_id="wf-1",
        version=1,
        tasks={"a": task},
        loop_tasks={},
        dependencies={"a": []},
        entry_points=["a"],
    )

    persistence = MemoryBackend()
    process_manager = FakeProcessManager()
    human_notifier = FakeHumanNotifier()
    time_provider = FakeTimeProvider()
    atropos = Atropos(
        workflow_id="wf-1",
        process_manager=process_manager,
        human_notifier=human_notifier,
        time_provider=time_provider,
        config=CleanupConfig(sigterm_grace_seconds=1, kill_retry_delay_seconds=0),
        log_dir=str(tmp_path),
    )
    lachesis = Lachesis(
        state_machine=sm,
        persistence=persistence,
        process_manager=process_manager,
        atropos=atropos,
        human_notifier=human_notifier,
        time_provider=time_provider,
        agents={"agent-a": AGENT},
        config=SchedulerConfig(poll_interval_seconds=0.0),
    )

    lachesis._initialize_state()
    lachesis._dispatch_ready()
    spawned = process_manager.spawned[0]

    # The fake process never exits on its own — simulate SIGTERM actually
    # killing it (FakeProcessManager.mark_killed), matching what a real
    # process would do once Atropos signals it during timeout cleanup.
    original_signal = process_manager.signal

    def signal_and_kill(process_info, sig):
        original_signal(process_info, sig)
        process_manager.mark_killed(process_info.pid)

    process_manager.signal = signal_and_kill

    time_provider.advance(11)
    lachesis._check_hangs()

    assert persistence.get_task("wf-1", "a").status == TaskStatus.FAILED
    assert len(human_notifier.requests) == 1
    assert human_notifier.requests[0]["task_id"] == "a"
    assert spawned.pid in process_manager.signals_received
