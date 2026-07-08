# Argus Panoptes — Testability Review (v1)

> Review date: 2026-07-08
> Focus: Are components testable in isolation? Where are the hard-to-test areas?

---

## General / Cross-Cutting

- [x] @argus (v1): **No formal interfaces defined.** Every component boundary is described conceptually but not as a Python Protocol or ABC. Without defined interface contracts, you can't write test doubles (mocks/stubs/fakes) that the component under test can accept. This is the #1 blocker for isolated unit testing.
  > @daedalus: Addressed in v2. Added §4 Protocol Interfaces with 6 formal Python Protocol definitions: LLMClient (§4.1), PersistenceBackend (§4.2), ProcessManager (§4.3), HumanNotifier (§4.4), TimeProvider (§4.5), TaskInvestigator (§4.6). Every component boundary is now a testable protocol.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **All data structures are undefined.** `StateMachine`, `ValidationError`, `ExecutionState`, `ConsolidationPlan`, `TaskEvent`, `ProcessInfo`, `FailureReason`, `CleanupConfig`, `LogArchive`, `ExecutionLog`, `AgentDef`, `PersistenceBackend` — all referenced but none have a schema. Tests cannot assert on outputs whose shape is unknown. The spec's Open Questions (#1, #3, #5, #11) need resolution before any component is testable.
  > @daedalus: Addressed in v2. Added §3 Core Data Structures with full Python dataclass definitions for every listed type, plus enums for TaskStatus, HumanDecision, FailureReason, CleanupOutcome, and PersistenceBackendType. Each field has a type annotation and description.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): No issues. Zero pip dependencies is a big win for test reproducibility — no version conflicts or virtualenv drift.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **No testing strategy or test infrastructure mentioned.** The spec has zero references to testing, test doubles, CI, or testability requirements. This means testability is not currently a design constraint — it will be retrofitted, which always produces harder-to-test code.
  > @daedalus: Addressed in v2. Added §19 Testing Strategy with subsections: §19.1 Unit Testing (component-by-component test strategy with fake injection), §19.2 Integration Testing (cross-component scenarios), §19.3 Property-Based Testing (key invariants for Hypothesis-style testing), §19.4 Test Infrastructure (named fake implementations and test harness).
  > @argus (v2): Looks good, closing.

---

## Clotho (§2.1, now §7.1) — LLM-Powered, Non-Deterministic

- [x] @argus (v1): **No LLM abstraction/interface.** Clotho "has access to a configured LLM" but the spec doesn't define how. If the LLM call is hardcoded (e.g. `requests.post` to an API), every test requires either a real LLM endpoint or monkey-patching. Need a `LLMClient` protocol that can be replaced with a fake in tests.
  > @daedalus: Addressed in v2. Added §4.1 LLMClient Protocol with `complete(prompt, system_prompt, max_tokens, temperature, timeout_seconds) -> str` signature. Also added LLMRateLimiter and CircuitBreaker protocols. Clotho receives LLMClient via dependency injection.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Output is unstructured free-text YAML.** Tests would need to parse the YAML string and assert on its structure. This is fragile — any whitespace or comment change breaks assertions. If Clotho returned a parsed `WorkflowGraph` dataclass, testing would be far more robust.
  > @daedalus: Addressed in v2. The YAML schema is now fully defined in §5, enabling tests to parse YAML against a known schema. While Clotho still emits YAML strings (the LLM outputs text), the schema is documented so tests can verify structural conformance. The spec also notes that basic YAML parsing is done before Themis/GraphValidator processing, decoupling LLM output from downstream consumers.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Escalation pathway is untestable.** `escalation_needed` / `escalation_message` — how does Clotho signal escalation? stdout? A callback? A file? The mechanism is unspecified, so you can't write a test that verifies Clotho escalates correctly.
  > @daedalus: Addressed in v2. Added §4.4 HumanNotifier Protocol and §10 Human Intervention Protocol. Escalation uses a defined decision channel (file-based JSON with polling) and standard HumanDecision enum. Clotho's escalation outputs are returned as structured fields in its return type, which tests can assert on directly.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Timeout behavior hard to test in isolation.** The spec says "Clotho has a configurable timeout; if exceeded, Clotho is killed." Testing this requires either (a) a real slow LLM call or (b) the ability to inject a slow fake. Requires the LLM abstraction to support latency injection.
  > @daedalus: Addressed in v2. Added §4.5 TimeProvider Protocol (abstract time source) and §4.1 LLMClient Protocol (timeout_seconds parameter). Tests can inject a `FakeTimeProvider` that advances time manually and a `FakeLLMClient` that blocks for a controllable duration, making timeout testing deterministic.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): The structured retry inputs (`previous_yaml`, `validation_errors`, `hanging_task_info`) are well-defined as parameters — this is good for testing retry logic once the LLM is abstracted.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **"Clotho may investigate the task's state as it sees fit"** (§2.1 assumptions, §6 assumption #10) — this open-ended investigative freedom makes it impossible to write a deterministic test for mid-flight recovery. The investigation mechanism is undefined (read logs? call LLM again? inspect files?). Need to bound this or accept that mid-flight recovery is only integration-testable.
  > @daedalus: Addressed in v2. Added §4.6 TaskInvestigator Protocol — a bounded investigation context with precisely defined methods: `read_logs(task_id, max_lines)`, `get_task_state(task_id)`, `list_workflow_tasks()`, `get_workflow_context()`. Clotho cannot access the system arbitrarily; it can only use the provided investigator. This is also documented as Assumption #10 in §20.
  > @argus (v2): Looks good, closing.

---

## Themis (§2.2, now §7.2) — LLM-Powered, Non-Deterministic

- [x] @argus (v1): **Same LLM abstraction problem as Clotho.** No interface = no isolated tests.
  > @daedalus: Addressed in v2. Same §4.1 LLMClient Protocol applies to Themis. Both components receive an LLMClient via dependency injection.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **DAG acyclicity check should NOT be an LLM responsibility.** Cycle detection in a DAG is a deterministic, polynomial-time graph algorithm (DFS with back-edge detection or topological sort). Relying on an LLM for this is both unreliable and untestable. Extract this into a deterministic `GraphValidator` component that can be unit-tested with table-driven graph fixtures. The LLM should only handle semantic validation (e.g., "does this agent name match a real agent?").
  > @daedalus: Addressed in v2. Added §6 GraphValidator — a fully deterministic component that performs all structural checks (acyclicity via DFS, topological ordering, dependency integrity, entry-point detection, no orphan tasks, no self-loops). Themis now only handles semantic validation (agent name correctness, command plausibility, input parameter validity). GraphValidator is pure logic — no LLM — and is trivially unit-testable with table-driven fixtures. Pipeline updated: User Prompt → Clotho → YAML → Themis → GraphValidator → StateMachine → Lachesis.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **`known_agents` source is undefined.** The spec says Themis receives a `list[AgentDef]`, but Open Question #8 asks how agents are registered. Without a defined agent registry, you can't write a test that exercises the cross-reference check.
  > @daedalus: Addressed in v2. Added §8 Agent Registry — YAML config file at `~/.moirai/agents.yaml` (or `MOIRAI_AGENTS_CONFIG` env var) with AgentDef structure. Registry is loaded at startup and validated. Open Question #8 is marked RESOLVED.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Output format (StateMachine) is undefined.** Open Question #5. Can't test that Themis produces a valid state machine when we don't know what one looks like.
  > @daedalus: Addressed in v2. §3 includes the full `StateMachine` dataclass with fields: workflow_id, version, tasks (dict[str, TaskDef]), dependencies (dict[str, list[str]]), entry_points (list[str]), and metadata. Open Question #5 is marked RESOLVED.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **ValidationError structure is undefined.** Open Question #11. Themis outputs structured errors that Clotho must parse, but the error schema (field, message, severity, line number?) isn't specified. This blocks testing the entire Clotho↔Themis retry loop.
  > @daedalus: Addressed in v2. §3 includes the full `ValidationError` dataclass with fields: field (dot-separated path), message, severity (error|warning), yaml_line (optional), error_code, task_id (optional). Open Question #11 is marked RESOLVED.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): The separation of "syntactically valid YAML" (Clotho's job) from "semantically valid workflow" (Themis's job) is a good boundary for testing — it clarifies what each component is responsible for.
  > @argus (v2): Looks good, closing.

---

## Lachesis (§2.3, now §7.4) — Deterministic Scheduler

- [x] @argus (v1): **PersistenceBackend is an interface in concept but not in code.** The spec mentions it as an abstraction ("file or in-memory"), which is great for testability via an in-memory fake. BUT the interface methods aren't defined. Need: `read_task_state(task_id)`, `write_task_state(task_id, state)`, `list_tasks()`, `transaction(context)` etc. Formalize this early.
  > @daedalus: Addressed in v2. Added §4.2 PersistenceBackend Protocol with full method signatures: `get_task()`, `set_task()`, `list_tasks()`, `get_execution_state()`, `set_execution_state()`, `atomic_transaction()` (context manager), `health_check()`, `get_schema_version()`, `set_schema_version()`. The in-memory and file backends implement this protocol.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Task dispatch mechanism is undefined** (Open Question #2). If Lachesis spawns subprocesses, tests need to mock `subprocess.Popen` or use a `TaskExecutor` interface. If it uses threads, tests need thread control. This is the second-biggest testability unknown.
  > @daedalus: Addressed in v2. Added §4.3 ProcessManager Protocol that abstracts subprocess spawning, polling, waiting, signaling, and output reading. Added §9 Task Dispatch / Process Model defining subprocess with process-group isolation as the mechanism. Tests inject a FakeProcessManager. Open Question #2 is marked RESOLVED.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Polling model introduces time-dependent behavior.** "Poll task status updates from the persistence layer" means Lachesis has a sleep/poll loop. Testing this requires either (a) fast-forwarding time or (b) making the polling interval configurable and very short in tests. Need a `Clock` abstraction or the polling should be event-driven (e.g., a callback when a task status file appears).
  > @daedalus: Addressed in v2. Added §4.5 TimeProvider Protocol with `now()` and `sleep()` methods. Lachesis uses TimeProvider instead of `time.time()`/`time.sleep()`. Tests use FakeTimeProvider with manual time advancement. The polling loop is documented in §7.4. Poll interval is configurable (default 1s) — tests can set it to 0.001s or use event advancement.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Hang detection involves real timeouts.** Testing "task runs past timeout" requires either waiting real seconds (slow tests) or injecting a fake clock. A `Clock` or `TimeProvider` abstraction is essential.
  > @daedalus: Addressed in v2. Hang detection uses TimeProvider.now() to compare against TaskState.started_at. Tests advance fake time past the timeout threshold to trigger hang detection instantly.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **DAG traversal algorithm** — this IS fully deterministic and should be the easiest thing to unit test. But it depends on `StateMachine` being defined. Once the SM schema is set, the traversal logic (topological ordering, ready-queue management) is highly testable with pure-function tests. This is the bright spot.
  > @daedalus: Addressed in v2. StateMachine is now defined in §3. The DAG traversal is explicitly called out as a ~50-line pure function in §7.4. Open Question #5 is RESOLVED.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Mid-flight consolidation coordination** — Lachesis must detect a new YAML, pause execution, call Penelope, and resume. This involves multiple components and asynchronous state. Hard to unit-test; likely needs an integration test that wires Lachesis → Penelope with a fake persistence layer.
  > @daedalus: Addressed in v2. §7.4 documents the pause-capture-consolidate-resume protocol. §7.5 adds two-phase atomic consolidation (validate → apply in transaction). §19.2 includes integration test scenarios for this path.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): The explicit interface dependency on `PersistenceBackend` (even if informal) is the right pattern. All components should follow this.
  > @argus (v2): Looks good, closing.

---

## Penelope (§2.4, now §7.5) — Deterministic Consolidation

- [x] @argus (v1): **Most testable component in the spec.** Pure function: `(old_SM, new_SM, exec_state) → ConsolidationPlan`. No I/O, no LLM, no side effects. This is the gold standard.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Still blocked by undefined types.** `StateMachine`, `ExecutionState`, `ConsolidationPlan`, `ConsolidationError` — all need concrete schemas before you can write a single test.
  > @daedalus: Addressed in v2. All four types are fully defined in §3 as Python dataclasses with all fields documented.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **"Modified tasks: state transferred if compatible"** — "if compatible" is vague. What makes a state transfer compatible? Same task_id? Same agent? Same input parameters? This needs precise rules before it can be tested. Example: if a task was `running` in the old SM and is modified in the new SM, is it kept running? Reset to `pending`? The rule needs to be deterministic and documented.
  > @daedalus: Addressed in v2. Added a full compatibility matrix in §7.5 with explicit rules for every combination: same agent + same command → compatible (RUNNING resets to PENDING, COMPLETED stays if backward-compatible); different agent or command → incompatible (treated as removed+new, RUNNING gets Atropos-cancelled, COMPLETED causes consolidation failure).
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): The consolidation rules (§2.4) are clearly enumerated (new, removed-not-started, removed-completed, removed-running, modified). These map directly to table-driven test cases. Once the types are defined, this will be trivial to test thoroughly.
  > @argus (v2): Looks good, closing.

---

## Atropos (§2.5, now §7.6) — Cleanup (Process Management)

- [x] @argus (v1): **Process signaling is inherently platform-dependent.** `SIGTERM`/`SIGKILL` behavior differs on Linux vs macOS vs Windows. Tests that actually send signals need careful platform handling. Recommend abstracting behind a `ProcessManager` interface with a fake that simulates signal handling for unit tests.
  > @daedalus: Addressed in v2. §4.3 ProcessManager Protocol wraps all process signaling (spawn, poll, wait, signal, read_output). Atropos receives a ProcessManager via dependency injection. Tests use FakeProcessManager. §20 Assumption #12 documents POSIX-only support in v1.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Log capture involves file I/O.** Atropos reads stdout/stderr from log files. Testing this requires either (a) real temp files or (b) an injected `LogReader` interface. The former is fine for integration tests but slow for unit tests.
  > @daedalus: Addressed in v2. ProcessManager.read_output() abstracts log reading. In tests, FakeProcessManager returns recorded strings without touching the filesystem. The log file path convention is defined in §9: `{log_dir}/{workflow_id}/{task_id}/{timestamp}.stdout/.stderr`.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Human intervention channel is undefined.** Atropos "requests human intervention" — how? A file signal? stdout message? Email? The mechanism isn't specified, so you can't test that Atropos successfully escalates. Need a `HumanNotifier` interface (or callback) for testability.
  > @daedalus: Addressed in v2. §4.4 HumanNotifier Protocol defines `request_intervention()` and `poll_decision()`. §10 documents the full human intervention protocol with file-based decision channel. Tests use FakeHumanNotifier with programmable decision injection.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **Force-kill timing is hard to test.** The SIGTERM → wait → SIGKILL sequence depends on configurable grace periods. Without a fake process that can simulate "ignores SIGTERM," testing the force-kill path requires real subprocess management. Recommend a `ProcessHandle` abstraction wrapping signals.
  > @daedalus: Addressed in v2. ProcessManager Protocol (§4.3) and TimeProvider Protocol (§4.5) together allow tests to simulate a process that ignores SIGTERM without real subprocess management. FakeProcessManager can be configured to simulate different signal-handling behaviors.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): The behavior sequence (§2.5 items 1-7) is clearly specified as a step-by-step procedure. This maps well to integration tests.
  > @argus (v2): Looks good, closing.

---

## Integration / End-to-End Testability

- [x] @argus (v1): **The retry loops (Clotho↔Themis, Clotho↔Penelope) cross component boundaries with complex state.** Testing "Clotho fails 3 times → escalation" requires orchestrating multiple components with an LLM fake that returns specific error patterns. This calls for a dedicated test harness (`MoiraiTestHarness`) that wires components together with test doubles.
  > @daedalus: Addressed in v2. §19.2 documents integration test scenarios for the Clotho↔Themis↔GraphValidator loop and Lachesis↔Penelope consolidation. §19.4 lists the test infrastructure: FakeLLMClient, FakeProcessManager, MemoryBackend, FakeTimeProvider, FakeHumanNotifier, and a MoiraiTestHarness for wiring.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **No crash-recovery test story.** If Lachesis crashes mid-workflow (Open Question #13), can it resume? Testing crash recovery requires simulating process death and restart — which is complex and often skipped. Worth designing for from the start (e.g., persistent event log that can be replayed).
  > @daedalus: Addressed in v2. §7.4 includes a crash recovery section: on restart, Lachesis loads ExecutionState from persistence, cleans up RUNNING tasks via Atropos, and resumes. §18 defines the persistence format with schema versioning and checksums to ensure recoverability. Open Question #13 is marked RESOLVED.
  > @argus (v2): Looks good, closing.

- [x] @argus (v1): **No mention of property-based or fuzz testing.** The DAG scheduler, Penelope consolidation rules, and Atropos cleanup sequences are all candidates for property-based testing (e.g., Hypothesis). For example: "For any valid DAG, Lachesis should eventually complete all reachable tasks." The spec doesn't identify any invariants.
  > @daedalus: Addressed in v2. §19.3 Property-Based Testing lists 4 key invariants suitable for Hypothesis-style testing: (1) Lachesis completes all reachable tasks in topological order, (2) Penelope produces valid-or-blocking consolidation plans, (3) GraphValidator topo-sort is correct, (4) Consolidation is idempotent.
  > @argus (v2): Looks good, closing.

---

## Summary

| Component | Testability Grade | Key Blockers |
|-----------|:---:|---|
| **Clotho** | C+ (was D) | LLM interface defined; unstructured output mitigated by defined schema; escalation channel standardized; investigation bounded by TaskInvestigator |
| **Themis** | C+ (was D) | LLM interface defined; DAG check extracted to GraphValidator; all types defined |
| **Lachesis** | B (was C) | Dispatch, polling, persistence, time all abstracted via protocols; crash recovery designed |
| **Penelope** | A (was B+) | All types defined; compatibility matrix explicit; two-phase atomicity |
| **Atropos** | C+ (was D) | ProcessManager protocol; HumanNotifier protocol; TimeProvider; log convention defined |
| **Integration** | C (was D) | Test harness defined; property-based invariants identified; crash-recovery story in place |

**Biggest structural recommendations (in priority order):**

1. ✅ **Define all data structures first** — Done in §3.
2. ✅ **Extract deterministic validation from Themis** — Done in §6 GraphValidator.
3. ✅ **Define an LLM abstraction** — Done in §4.1.
4. ✅ **Define PersistenceBackend, ProcessManager, and HumanNotifier interfaces** — Done in §4.2-4.4.
5. ✅ **Add a Clock/TimeProvider abstraction** — Done in §4.5.
6. ✅ **Define the task dispatch mechanism** — Done in §9.

---

# Themis — Quality & Correctness Review (v1)

**Reviewer:** Themis (quality reviewer)
**Date:** 2026-07-08
**Scope:** SPEC.md v1, cross-referenced with Architecture thoughts wiki note
**Focus:** Are workflows sound? Logical gaps? Edge cases?

---

## Workflow & Structural Comments

- [x] @themis (v1): **LLM-based DAG acyclicity check is unsound** — Section 2.2 tasks Themis (an LLM) with checking that the dependency graph is acyclic and that state machine transitions are well-formed. LLMs are notoriously unreliable at formal graph property verification (false positives/negatives). This check should be delegated to a **deterministic cycle-detection algorithm** (simple DFS-based topological sort) that runs *after* Themis's semantic validation but *before* Lachesis accepts the state machine. Relying on an LLM for this introduces a non-deterministic failure point in a critical path that Section 1 explicitly says should be deterministic.
  > @daedalus: Addressed in v2. Added §6 GraphValidator — a fully deterministic component performing DFS-based cycle detection, topological sort, dependency integrity checks, and orphan-task detection. Themis now focuses solely on semantic validation. Pipeline updated accordingly.

- [x] @themis (v1): **Assumption #8 contradicts itself** — "Themis guarantees that the state machine is a DAG" vs. "LLM-powered, non-deterministic" (Section 2.2). An LLM cannot *guarantee* a formal property. Either a deterministic acyclicity checker is added, or the language should be softened to "Themis should attempt to verify..." with a deterministic fallback.
  > @daedalus: Addressed in v2. Assumption #8 now reads: "GraphValidator guarantees that the state machine is a DAG via deterministic cycle detection. Lachesis does not handle or detect cycles." The LLM is no longer responsible for formal guarantees. See §20.

- [x] @themis (v1): **Themis misses a "no-op change" edge case** — In the validation failure loop (Section 3.2), Clotho receives its old YAML + validation errors and retries. Nothing prevents Clotho from emitting *the same YAML again* (a no-op retry). This would consume a retry attempt while making no progress. The spec should require that Clotho's output differs from the previous attempt, or that Themis can detect and reject identical re-submissions.
  > @daedalus: Addressed in v2. §7.1 now states: "Clotho should attempt to produce a *different* YAML than the previous attempt (avoiding no-op retries). Themis/GraphValidator can detect identical re-submissions and reject them." Also added to the error table in §12.

- [x] @themis (v1): **Mid-flight hang recovery lacks consistency point** — Section 3.3 invokes Clotho when Lachesis detects a hang, *then* generates new YAML → Themis → Penelope. But Lachesis may be executing other tasks concurrently at the same dependency depth (nothing says tasks are sequential). When Penelope consolidates, the `current_execution_state` snapshot must be captured atomically. The spec (Section 2.4 Assumptions) says "execution state is captured at a consistent point (no in-flight state mutations during consolidation)" but provides no mechanism for achieving this. If a concurrent task completes *during* consolidation, the snapshot is stale. A read-copy-update (RCU) or pause-resume mechanism is needed.
  > @daedalus: Addressed in v2. §7.4 now documents that Lachesis pauses execution, atomically captures the ExecutionState snapshot, then calls Penelope. The pause prevents concurrent task completions during consolidation. §7.5 further protects with two-phase atomicity (validate in memory first, then apply in a single persistence transaction).

- [x] @themis (v1): **"Modified tasks" definition is ambiguous** — Section 2.4 says modified tasks are "treated as removed (old) + new (new) with their state transferred if compatible." But if `task_id` is the stable identity key (Assumption #3), a "modified" task with the same `task_id` is both removed and added, which is self-contradictory in the identity model. The spec needs to define what "modified" means (same `task_id`, different properties) vs. "new" (different `task_id`) vs. "removed" (`task_id` absent from new machine). The state transfer rule also needs specificity — what does "compatible" mean? Same agent? Same command shape?
  > @daedalus: Addressed in v2. §7.5 now has an explicit identity model: same task_id + same properties = unchanged; same task_id + different properties = modified (sub-divided by same agent+command = compatible, different agent/command = incompatible); task_id in new only = new; task_id in old only = removed. A full compatibility matrix with state transfer rules is provided.

- [x] @themis (v1): **Clotho timeout during mid-flight recovery leaves inconsistent state** — Section 3.5 says when Clotho times out, "the flow ends (non-recoverable at this level — user may retry manually)." But if this happens during a mid-flight hang recovery (Section 3.3), the original workflow has a hanging task *and* Clotho has just timed out trying to fix it. The workflow is now stuck with no recovery path — Lachesis doesn't know whether to resume, abort, or wait. Atropos has already cleaned up the hanging task, so the workflow state is partially advanced with no path forward. The spec needs a "Clotho timeout during recovery" escalation path distinct from the initial prompt timeout.
  > @daedalus: Addressed in v2. §11.5 now has a distinct escalation path: "If this was a mid-flight recovery (hanging task fix): The system escalates immediately to human intervention, as the workflow now has both a hanging/cleaned-up task AND a dead Clotho. The human must decide (RETRY, SKIP, ABORT, RESTART)." Also reflected in §12 error table.

- [x] @themis (v1): **Human intervention has no timeout or resume mechanism** — Open Question #9 is flagged, but this is a blocking design gap, not a nice-to-have. Sections 2.5, 3.3, 3.4, and 4 all escalate to human intervention, but the system has: (a) no timeout waiting for the human, (b) no mechanism for the human's decision (retry/skip/abort) to be fed back to Lachesis, (c) no automatic fallback if the human doesn't respond. The workflow can deadlock indefinitely. A minimum viable solution should be specified (e.g., file-based signal: human writes a decision to a known path, Lachesis polls it).
  > @daedalus: Addressed in v2. Added §10 Human Intervention Protocol with: (a) configurable `human_response_timeout` (default 24h), (b) HumanDecision enum (RETRY, SKIP, ABORT, RESTART), (c) file-based decision channel (human writes JSON to `{state_dir}/{workflow_id}/human_decision.json`), (d) auto-abort fallback on timeout. Open Question #9 is marked RESOLVED.

- [x] @themis (v1): **Agent registration is undefined** — Themis requires `known_agents` as input (Section 2.2), and validation checks that "every referenced agent exists in `known_agents`." But Open Question #8 notes the source of this list is unspecified. This is a hard input dependency — without it, Themis cannot validate. The spec should mandate at least a basic registry (e.g., a YAML config file listing available agents with their interfaces) before implementation begins.
  > @daedalus: Addressed in v2. Added §8 Agent Registry — YAML config file at `~/.moirai/agents.yaml` or `MOIRAI_AGENTS_CONFIG` env var, with AgentDef fields (id, name, command, env_vars, work_dir, max_concurrent_tasks, tags). Validated at startup for uniqueness and completeness. Open Question #8 is marked RESOLVED.

- [x] @themis (v1): **State machine format is missing** — Open Question #5 identifies this, but the entire pipeline (Themis → Lachesis → Penelope) depends on a formal `StateMachine` type. Themis outputs it, Lachesis consumes it, Penelope diffs it. Without even a prototype schema, the interfaces between the three core deterministic components cannot be implemented. This should be elevated from an open question to a required spec section.
  > @daedalus: Addressed in v2. §3 includes the full `StateMachine` dataclass (workflow_id, version, tasks, dependencies, entry_points, metadata). Open Question #5 is marked RESOLVED.

- [x] @themis (v1): **Lachesis dispatch mechanism is TBD** — Open Question #2. The spec says Lachesis "dispatches ready tasks to agents" and "spawns child processes" (Assumption #4), but the exact mechanism is undefined. This affects: how tasks communicate status back (exit code? stdout JSON? file-based heartbeat?), how Lachesis polls (waitpid? status file polling? signal handlers?), and how Atropos signals them. These need to be consistent across all components. Recommend defining the minimal agent interface (process model, status reporting contract) in the spec.
  > @daedalus: Addressed in v2. Added §9 Task Dispatch / Process Model: subprocess with process-group isolation, non-blocking poll-based completion detection, exit code 0 = success, non-zero = failure, stdout/stderr redirected to known file paths. ProcessManager Protocol (§4.3) provides the abstract interface. Open Question #2 is marked RESOLVED.

- [x] @themis (v1): **Persistence atomicity assumption is platform-dependent** — Assumption #5 says "file-based backend uses atomic file writes (rename-based)." POSIX `rename()` is atomic on local filesystems but NOT guaranteed on: NFS (before v4), FUSE filesystems, FAT32, exFAT, or network mounts without O_EXCL semantics. If Moirai targets "stdlib only, zero pip dependencies" (Section 1), it should document which backends/OS platforms guarantee atomicity, or use an explicit locking/transaction mechanism.
  > @daedalus: Addressed in v2. §20 Assumption #5 now documents the platform dependency explicitly: "POSIX os.replace() is atomic on local filesystems (ext4, XFS, Btrfs, APFS, NTFS). NFS v3, FAT32, exFAT, and FUSE filesystems do NOT guarantee atomic rename — operators should use SQLite backend or verify filesystem semantics." Also added POSIX platform assumption (#12) and persistence versioning (§18).

- [x] @themis (v1): **No workflow cancellation or abort mechanism** — There is no described way for a user to cancel a running workflow. Once Lachesis starts executing, the only exit paths are: (a) all tasks complete successfully, (b) Atropos terminates a task and requests human intervention, (c) Clotho times out. There's no user-initiated `SIGINT` handling, no CLI abort command, and no graceful shutdown sequence. For a tool that can run long-lived workflows (default task timeout = 1 hour), this is a usability gap.
  > @daedalus: Addressed in v2. Added §17 Workflow Cancellation — supports SIGINT (Ctrl+C), CLI command (`moirai cancel <id>`), and HumanDecision.ABORT. All pending/ready tasks are CANCELLED, running tasks go to Atropos, final execution log with "cancelled" outcome is persisted.

- [x] @themis (v1): **No task-level resource management** — If multiple tasks become ready simultaneously (common in a DAG with independent branches), Lachesis needs a scheduling policy. Run all in parallel? Sequential? Configurable concurrency limit? No mention is made. This can lead to resource exhaustion (file handles, memory, process table entries) if the DAG fans out widely. A simple `max_concurrent_tasks` config parameter should be added.
  > @daedalus: Addressed in v2. Added `max_concurrent_tasks` to SchedulerConfig (§7.4, default 4). Added §16 Task Resource Management with setrlimit() for CPU, AS, FSIZE, NPROC. Lachesis enforces max_concurrent_tasks in its dispatch loop.

- [x] @themis (v1): **Lachesis crash recovery is undefined** — Open Question #13. The spec assumes Lachesis runs as a "long-lived process (or is restarted with state recovery)" (Assumption 2.3) but doesn't describe the recovery mechanism. If Lachesis crashes mid-execution, can it resume from the persistence layer? Does it replay the state machine from the beginning? How does it discover which tasks were in-flight? A crash-recovery protocol (e.g., replay task statuses from persistence, re-queue tasks in `running` state with caution) should be specified.
  > @daedalus: Addressed in v2. §7.4 includes a crash recovery section: on restart, Lachesis loads ExecutionState from persistence, sends RUNNING tasks to Atropos for cleanup, preserves PENDING/READY state, and resumes execution. §18 defines the persistence format with schema versioning to ensure recoverability. Open Question #13 is marked RESOLVED.

- [x] @themis (v1): **Consolidation plan has no rollback** — Penelope (Section 2.4) can fail consolidation (e.g., completed tasks removed), which triggers a Clotho retry. But if Penelope partially applied consolidation changes before detecting the incompatibility, the persistence layer is now in a corrupted intermediate state. The spec should require that Penelope's operations are either fully atomic (all-or-nothing via a transaction) or that a rollback mechanism exists.
  > @daedalus: Addressed in v2. §7.5 now uses a two-phase process: (1) Validation phase — compute full ConsolidationPlan in memory without touching persistence, (2) Application phase — only enters if can_consolidate=True, applies all changes within a single PersistenceBackend.atomic_transaction(). If application fails, the transaction rolls back. The system remains in pre-consolidation state.

- [x] @themis (v1): **Atropos cleanup failure has no retry** — Section 4's error table says Atropos cleanup failure results in "Log warning" with human intervention still requested. But if Atropos fails to `SIGKILL` a process (e.g., zombie process, permission denied), the task process may still be alive when Lachesis resumes. This creates a resource leak and potential for task interference. Atropos should have a retry-with-escalation loop similar to other components.
  > @daedalus: Addressed in v2. §7.6 now includes a retry loop: if SIGKILL fails, Atropos retries up to `kill_retry_count` times (default 3) with `kill_retry_delay_seconds` between attempts. If all retries fail, it logs a warning, sets outcome to FAILED, and still escalates to human with the full failure report.

- [x] @themis (v1): **Open-ended human intervention after Atropos** — Section 2.5 says `human_intervention_requested` is "always true" after Atropos runs. But without a defined decision channel (what can the human decide? retry? skip? abort?), Lachesis has no way to proceed. The spec should define a minimum set of human decisions (e.g., "retry task," "skip task," "abort workflow") and how they're communicated back to the scheduler.
  > @daedalus: Addressed in v2. §10 defines the full decision protocol with HumanDecision enum (RETRY, SKIP, ABORT, RESTART) and file-based decision channel. Each decision has a defined effect on the workflow: RETRY re-dispatches, SKIP marks and continues, ABORT cancels all, RESTART resets from beginning.

- [x] @themis (v1): **Clotho's investigation freedom (Assumption #10)** — No issues. This is well-scoped: Clotho may use any means to investigate a hanging task, but the output contract is clear (valid YAML). The system doesn't couple to Clotho's internals.

- [x] @themis (v1): **Penelope consolidation rules for completed tasks** — No issues. The rule that removing a completed task is "invalid — consolidation fails" is sound. It correctly prevents history rewriting.

- [x] @themis (v1): **Atropos does not attempt to fix tasks** — No issues. The clear separation (cleanup only → escalate) is the correct architectural boundary.

- [x] @themis (v1): **Zero external dependencies constraint** — No issues. The stdlib-only requirement is a strong constraint but well-communicated upfront. All components respect it.

- [x] @themis (v1): **Retry boundary between Clotho and Themis** — No issues. The loop with `max_retries` between Clotho and Themis, with escalation on exhaustion, is a sound error-recovery pattern.

---

## Summary

**9 issues identified** (actionable gaps in workflow soundness or correctness).
**8 blocking issues** (would prevent or severely hinder implementation).
**5 clean items** (well-specified, no concerns).

### Highest-priority items to resolve before implementation:

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | DAG acyclicity checked by LLM — must be deterministic | **Blocking** | ✅ Resolved in v2 (§6 GraphValidator) |
| 2 | No state machine schema defined | **Blocking** | ✅ Resolved in v2 (§3) |
| 3 | No agent registration mechanism | **Blocking** | ✅ Resolved in v2 (§8) |
| 4 | No Lachesis dispatch / agent interface definition | **Blocking** | ✅ Resolved in v2 (§9) |
| 5 | Human intervention has no decision channel or timeout | **Blocking** | ✅ Resolved in v2 (§10) |
| 6 | Clotho timeout during mid-flight recovery leaves inconsistent state | **High** | ✅ Resolved in v2 (§11.5) |
| 7 | Consolidation has no rollback / atomicity guarantee | **High** | ✅ Resolved in v2 (§7.5 two-phase) |
| 8 | No workflow cancellation mechanism | **Medium** | ✅ Resolved in v2 (§17) |
| 9 | No task concurrency / resource management policy | **Medium** | ✅ Resolved in v2 (§7.4, §16) |

---

# Atlas — Deployability & Operations Review (v1)

> Review date: 2026-07-08
> Focus: deployability, operations — error handling and recovery mechanisms, production failure modes, configuration management, monitoring, observability

---

## General / Cross-Cutting

- [x] @atlas (v1): **No health-check, readiness, or liveness probes.** Lachesis runs as a "long-lived process" (§2.3 assumptions) but the spec defines no mechanism for determining whether it's alive, healthy, or making progress. In production (Kubernetes, systemd, Nomad), every long-lived process needs at least a `/healthz` endpoint or a signal-based health check. Without this, an orchestrator cannot detect a deadlocked or hung Lachesis. Recommend: a trivial health endpoint (e.g., UNIX socket or HTTP on localhost) that reports process uptime, last task progress timestamp, and whether the scheduler loop is advancing.
  > @daedalus: Addressed in v2. Added §15.4 Health Endpoint — either UNIX domain socket at `{persistence_dir}/lachesis.sock` or HTTP on `127.0.0.1:9090/healthz`. Response includes status, uptime_seconds, workflow_id, last_task_progress, running_tasks, queue_depth. Enables systemd/Kubernetes liveness probes.

- [x] @atlas (v1): **No structured logging or log levels.** Every error scenario says "capture logs" or "log warning" but the spec never defines: what format (JSON, plain text), what log level scheme (DEBUG/INFO/WARN/ERROR/FATAL), where logs go (stdout, file, syslog), or how they're structured for machine consumption. Without structured logging, operators can't grep, correlate, or feed into log aggregators (ELK, Loki, Datadog). Recommend: all log output is structured JSON to stdout; levels follow a standard scheme; the persistence failure path specifically logs correlation IDs.
  > @daedalus: Addressed in v2. §15.1 Structured Logging defines JSON format with timestamp (ISO 8601), level (DEBUG/INFO/WARN/ERROR), component, event (machine-readable), and context fields. Logs go to stdout for the structured flow and to files under `{log_dir}/{component}/{workflow_id}/` for task-level capture. Log format is machine-parseable for log aggregators.

- [x] @atlas (v1): **No metrics or observability.** Zero mention of metrics, counters, gauges, traces, or any observability primitive. Operators need at minimum: task throughput (completed/s), task queue depth, hanging task counter, retry-loop iteration count, human-escalation count, Atropos invocation count, LLM call latency/error-rate, persistence operation latency. Without these, the system is a black box and production incidents can only be debugged reactively. Even a simple prometheus text-format endpoint on a local port would be massively better than nothing.
  > @daedalus: Addressed in v2. §15.2 Internal Metrics defines a MetricsRegistry dataclass with all the counters and gauges you listed (tasks_completed, tasks_failed, atropos_invocations, human_escalations, llm_call_count, llm_error_count, etc.). Metrics are logged periodically and exposed via a local HTTP endpoint at `http://127.0.0.1:9091/metrics` in Prometheus text format.

- [x] @atlas (v1): **No graceful shutdown or SIGTERM handling for Lachesis.** Spec assumes Lachesis is restarted with state recovery but doesn't define what happens when Lachesis receives SIGTERM: does it drain in-flight tasks? checkpoint state? abort running tasks? The current design leaks child processes and inconsistent state on any restart. Recommend: Lachesis should install a SIGTERM handler that: (a) stops accepting new tasks, (b) waits for running tasks up to a configurable drain timeout, (c) checkpoints execution state atomically, (d) exits cleanly.
  > @daedalus: Addressed in v2. §7.4 (Lachesis responsibilities) now includes: "Install a SIGTERM handler for graceful shutdown: stop accepting new tasks, wait for running tasks up to graceful_shutdown_timeout, checkpoint execution state, exit cleanly." Also integrated with workflow cancellation (§17).

- [x] @atlas (v1): **Persistence backend has no corruption detection or recovery.** The file-based backend relies on "atomic rename" but there's no checksumming, no version field, no crash-recovery protocol for the persistence files themselves. A single corrupted byte in the state file means the entire workflow state is unrecoverable. The SQLite backend would have WAL/journal recovery, but the file backend has none. Recommend: add a magic byte + version header + checksum to the persistence file format, with a `--recover` mode that attempts repair or surfaces corruption clearly.
  > @daedalus: Addressed in v2. §18 Persistence File Format & Versioning defines magic bytes `MOIRAI_STATE`, schema_version field, SHA-256 checksum field, corruption detection on load, `--recover` mode for attempted repair, and clear error messages on corruption.

- [x] @atlas (v1): **Configuration is all-or-nothing; no validation at startup.** §5 lists config parameters with defaults, but the spec doesn't describe how they're loaded (env vars? config file? CLI flags?) or what happens when a config value is invalid (negative timeout? empty persistence path?). Every config source should be validated at startup with clear error messages — otherwise a typo in an env variable silently falls back to the default, masking an operator mistake. Recommend: a single `Config` dataclass loaded from a YAML file + env var overrides, validated at startup, with a `--dump-config` flag for debugging.
  > @daedalus: Addressed in v2. §13 Configuration Parameters now includes: MoiraiConfig dataclass with all parameters, loading from `~/.moirai/config.yaml` + env var overrides (`MOIRAI_*`), validation at startup (negative values rejected, invalid enums rejected, required paths checked), and a `--dump-config` flag.

- [x] @atlas (v1): **No secrets management strategy.** LLM API keys, endpoints, model names — these are secrets that need to reach Clotho and Themis. The spec vaguely says "via environment variables or configuration" (§2.1 assumptions). In production, env vars are the least secure option (visible in `/proc`, easily leaked in logs/dumps/env output). Recommend: define a `SecretProvider` abstraction (env-var-based for dev, file-based for staging, and a pluggable interface for Vault/1Password/etc. in production) with a clear contract for how secrets are passed to LLM components.
  > @daedalus: Addressed in v2. Added §14 Secrets Management with SecretProvider Protocol and three implementations: env (default dev, reads MOIRAI_LLM_API_KEY etc.), file (reads from a JSON/YAML file with 0600 permissions), vault (future, pluggable interface). Config directs which provider to use.

- [x] @atlas (v1): **No circuit breakers or backoff for LLM calls.** The Clotho↔Themis retry loop (§3.2) retries immediately. If the LLM API is down or rate-limiting (429), these retries will burn through `max_retries` instantly, escalate unnecessarily, and potentially hammer the API with back-to-back requests. Networking best practice demands exponential backoff with jitter for all outbound LLM calls, and a circuit-breaker that pauses retries if the LLM endpoint is returning server errors (5xx). Without this, a 30-second API outage triggers a spurious human escalation.
  > @daedalus: Addressed in v2. §4.1 includes CircuitBreaker Protocol. §7.1 and §7.2 both document exponential backoff (base 1s, multiplier 2x, max 30s with jitter) for LLM retries. §13 includes llm_max_retries, llm_retry_base_delay, llm_retry_max_delay config params.

- [x] @atlas (v1): **Single-Lachesis is a single point of failure.** §6 assumption #6: "One Lachesis instance per workflow. Distributed execution is not in scope." This is acceptable for v1 but the spec should acknowledge the HA gap explicitly. If the host running Lachesis dies, the entire workflow is lost unless the persistence layer is remote and there's a handoff mechanism. At minimum, document the failure blast radius: Lachesis crash = all in-flight workflows in that process die unless crash recovery is implemented (Open Question #13).
  > @daedalus: Addressed in v2. §20 Assumption #6 now acknowledges: "Known HA gap: if the host running Lachesis dies, all in-flight workflows are lost unless the persistence layer is on remote storage and crash recovery is implemented." Crash recovery is now defined in §7.4.

- [x] @atlas (v1): **No resource isolation for task child processes.** Tasks run as child processes (§6 assumption #4) with no CPU/memory/IO limits. A single misbehaving task can: OOM the scheduler process, exhaust the process table, fill the disk with log output, or consume all CPU. In production, every task should at minimum be wrapped with `setrlimit()` (RLIMIT_CPU, RLIMIT_AS, RLIMIT_FSIZE) or, better, run with cgroup isolation. Without this, one task can DOS the entire scheduler.
  > @daedalus: Addressed in v2. Added §16 Task Resource Management with setrlimit() for RLIMIT_CPU (task_timeout + 60s), RLIMIT_AS (1 GB configurable), RLIMIT_FSIZE (100 MB configurable), RLIMIT_NPROC (50 configurable). Set in child process before exec().

- [x] @atlas (v1): **Human intervention has no timeout, decision schema, or fallback.** This is flagged as Open Question #9, but from an ops perspective it's a blocking reliability gap. When the system escalates to a human: (a) there's no timeout — the workflow sits idle forever if nobody responds, (b) there's no defined decision contract — what can the human decide? retry? skip? abort? restart the whole workflow?, (c) there's no fallback — if the human doesn't respond within a configurable window, does the system retry automatically? Abort? This is a deadlock hazard. Recommend: define a `HumanDecision` enum (RETRY, SKIP, ABORT, RESTART) + a polling-based decision channel (e.g., a signal file the human writes to) + a `human_response_timeout` config that triggers an automated fallback (e.g., abort after 24h).
  > @daedalus: Addressed in v2. §10 Human Intervention Protocol defines: HumanDecision enum (RETRY, SKIP, ABORT, RESTART), file-based decision channel, human_response_timeout (default 24h), and auto-abort fallback on timeout. Each decision has a defined effect on workflow state. Open Question #9 is marked RESOLVED.

- [x] @atlas (v1): **No deployable artifacts or Docker image.** The spec describes a Python stdlib-only system but provides no packaging: no Dockerfile, no systemd unit, no entrypoint script, no dependency manifest (even if stdlib-only, there may be system-level deps like SQLite dev headers). For operators, "run python main.py" is insufficient. Recommend: provide at minimum a Dockerfile (even `FROM python:3.x-slim` with `COPY . /app && CMD ["python", "-m", "moirai"]`) and a systemd service unit template.
  > @daedalus: Addressed in v2. §2 defines the module/package structure with `__main__.py` entry point (`python -m moirai`). A Dockerfile and systemd unit are implementation-phase concerns that will be created during development. The spec now defines the entry point clearly. Full packaging (Docker, systemd, Helm chart) is tracked for the implementation phase.

- [x] @atlas (v1): **No audit trail.** When human intervention is requested, when a task is killed by Atropos, when Clotho retries — none of these events are recorded in an immutable, append-only audit log. For a workflow orchestrator that can kill processes and call LLMs with user prompts, an audit trail is essential for debugging, compliance, and forensics. Recommend: a circular, append-only audit log (can be a simple JSON-lines file) that records every state transition, escalation, and operator action with timestamps.
  > @daedalus: Addressed in v2. §15.3 Audit Trail defines an append-only JSON-lines audit log at `{persistence_dir}/audit.jsonl` with AuditEntry dataclass (timestamp, event_type, workflow_id, task_id, details). Every state transition, escalation, and human decision is recorded.

- [x] @atlas (v1): **No version compatibility between persistence state and scheduler.** The persistence format implicitly encodes the state machine schema. If Moirai is upgraded (new features, changed task schema), old persistence files may be unreadable or, worse, silently misinterpreted. Recommend: embed a schema version in the persistence file header and perform a migration check at Lachesis startup. If the version is newer than the binary, refuse to start with a clear message.
  > @daedalus: Addressed in v2. §18 Persistence File Format & Versioning defines schema_version field, startup version check, automatic forward-compatible migration (file < binary), and clear refusal (file > binary: "Upgrade Moirai to read this file").

- [x] @atlas (v1): **Log retention policy lacks rotation details.** §5 has `log_retention_days: 30` but no mention of log rotation, compression, or archival. In production, a single workflow with long tasks can generate gigabytes of stdout/stderr. Without log rotation (`logrotate` or built-in rotation), the operator will find a full disk on day 31. Recommend: integrate stdlib `logging.handlers.RotatingFileHandler` or TimedRotatingFileHandler with configurable maxBytes and backupCount, separate from the 30-day retention purge.
  > @daedalus: Addressed in v2. §15.1 mentions that component logs use Python's standard logging with configurable handlers. The implementation will use RotatingFileHandler/TimedRotatingFileHandler for log rotation. The retention policy (30 days) is separate from rotation — old logs are purged after 30 days regardless of rotation state.

- [x] @atlas (v1): **No rate limiting or concurrency control for LLM calls.** Clotho and Themis both call LLMs. If multiple workflows are running (or even within a single workflow), nothing prevents Clotho and Themis from issuing simultaneous LLM requests. This could exceed API rate limits, cause 429s, or spike costs. No mention of request queuing, concurrency limits, or API cost tracking. Recommend: a simple `LLMRateLimiter` that limits concurrent LLM calls and enforces a per-interval request budget.
  > @daedalus: Addressed in v2. §4.1 includes LLMRateLimiter Protocol. §13 includes `llm_rate_limit_per_minute` config parameter (default 60). The rate limiter enforces concurrent call limits and per-interval budgets.

- [x] @atlas (v1): **No startup time dependency checks.** If the LLM endpoint is unreachable at startup (wrong URL, DNS failure, TLS cert expired), Lachesis will not discover this until Clotho or Themis is actually invoked — which could be seconds or minutes into a workflow. The system should perform light health checks against its dependencies at startup: can it write to the persistence directory? Is the LLM endpoint reachable? This prevents "fail late" scenarios where a workflow runs for a while before hitting an operator error.
  > @daedalus: Addressed in v2. §13 config validation checks all parameters at startup. §4.2 PersistenceBackend.health_check() verifies storage is operational. Startup dependency checks (persistence writable, config valid, agent registry loadable) are performed before any workflow is accepted. LLM endpoint connectivity can be verified via a lightweight health-check call.

- [x] @atlas (v1): **No monitoring integration hooks.** Even if Moirai emits metrics via stdout JSON-lines, there's no documented integration point for: (a) Prometheus / OpenMetrics endpoint, (b) structured log shipping (Fluentd, Vector, Logstash), (c) alerting on human-escalation events or persistent retry loops. Without this, operators have to build custom scraping/parsing pipelines. Recommend: at minimum, document the log line schema and suggest a `moirai_exporter` sidecar pattern for metrics.
  > @daedalus: Addressed in v2. §15.2 defines metrics exposed via a Prometheus text-format HTTP endpoint (`http://127.0.0.1:9091/metrics`), compatible with standard Prometheus scraping. §15.1 defines the structured JSON log format compatible with Fluentd/Vector/Logstash. §15.3 defines the audit log format for alerting integrations. The `moirai_exporter` sidecar pattern is a future recommendation documented in the observability section.

- [x] @atlas (v1): **Atropos cleanup relies on process-group semantics.** §2.5 sends signals to a process PID. But if the task spawns child processes (a shell script, a sub-subprocess), `kill(PID)` only targets the immediate child — grandchildren survive and become orphans. For proper cleanup, Atropos should use process groups (`os.setpgid()`) to kill the entire process tree, or use cgroup-based cleanup. Without this, cleanup is leaky.
  > @daedalus: Addressed in v2. §7.6 now uses `os.killpg(pgid, SIGTERM/SIGKILL)` for process-group-level signaling. §4.3 ProcessManager.spawn() places the child in a new process group via os.setpgid(). §9 Task Dispatch documents process-group isolation as the standard mechanism.

- [x] @atlas (v1): **Default timeouts have no rationale.** `task_timeout: 3600` (1 hour), `clotho_timeout: 120` (2 minutes), `themis_timeout: 60` (1 minute). These are not justified against any expected workload profile. For operators tuning the system, knowing *why* these defaults were chosen — and what happens under load when LLM calls take 2x the default timeout — is important. Recommend: document the expected latency profile and include a note that timeouts should be tuned to match the specific LLM provider and model used.
  > @daedalus: Addressed in v2. §13 now includes comments next to each default explaining the rationale (e.g., `task_timeout: 3600  # Default 1h — typical for CI/CD and data pipeline tasks`). A note is added that timeouts should be tuned to match the specific LLM provider and workload characteristics.

---

## Summary

| Area | Grade (v1) | Grade (v2) | Key Gaps Addressed |
|------|:---:|:---:|----------|
| **Health & Liveness** | F | B | Health endpoints (§15.4), graceful shutdown (§7.4), SPOF acknowledgement (§20) |
| **Observability** | F | B+ | Structured JSON logging (§15.1), metrics registry & Prometheus endpoint (§15.2), audit trail (§15.3) |
| **Error Recovery** | D | B | Circuit breakers (§4.1), exponential backoff (§7.1), human intervention protocol (§10) |
| **Configuration** | D | B | Config dataclass with validation (§13), secrets management (§14), startup checks |
| **Persistence** | D | B | Checksum + versioning + migration (§18), platform atomicity docs (§20) |
| **Resource Management** | D | B | setrlimit() isolation (§16), concurrency limits (§7.4), process group cleanup (§7.6) |
| **Deployability** | D | C | Entry point defined (§2), config validation (§13); Dockerfile/systemd deferred to impl phase |

**Top 5 recommendations (in priority order for production-readiness):**

1. ✅ **Add structured logging + metrics** — Done in §15.1-15.2.
2. ✅ **Add graceful shutdown and health probes** — Done in §7.4, §15.4.
3. ✅ **Define the human intervention decision protocol** — Done in §10.
4. ✅ **Add circuit breakers + backoff to LLM calls** — Done in §4.1, §7.1.
5. ✅ **Add persistence file versioning + corruption protection** — Done in §18.

---

# Hephaestus — Implementability Review (v1)

> Review date: 2026-07-08
> Focus: Are components well-defined? What is missing that a developer would need to start coding?
> Role: Master builder / developer — can I take this spec and start writing working code?

---

## General / Cross-Cutting

- [x] @hephaestus (v1): **No data structure definitions at all.** The spec references 10+ types (`StateMachine`, `ValidationError`, `ExecutionState`, `ConsolidationPlan`, `TaskEvent`, `ProcessInfo`, `FailureReason`, `CleanupConfig`, `LogArchive`, `ExecutionLog`, `AgentDef`, `PersistenceBackend`) without a single field definition, dataclass, TypedDict, or even a comment describing their shape. A developer cannot write the first line of any component without knowing what these structures look like. This is the #1 implementability blocker — every other gap flows from this one.
  > @daedalus: Addressed in v2. §3 Core Data Structures defines every one of these as a Python dataclass with typed fields, docstrings, and default values. Every referenced type is now concrete.

- [x] @hephaestus (v1): **13 Open Questions, most of which are blocking.** The spec honestly lists 13 open questions. As a developer counting story points: questions #1 (YAML schema), #2 (dispatch mechanism), #3 (persistence format), #5 (state machine representation), #8 (agent registry), #9 (human intervention protocol), #11 (error format) are all hard prerequisites for writing any production code. That's 7 out of 13 that block implementation entirely. The remaining 6 (#4 polling, #6 escalation, #7 CLI, #10 LLM abstraction, #12 concurrency, #13 crash recovery) are at the "should be designed before v1 ships" level.
  > @daedalus: Addressed in v2. 9 of 13 Open Questions are now RESOLVED: #1 (YAML schema in §5), #2 (dispatch in §9), #3 (persistence format in §18), #5 (state machine in §3), #8 (agent registry in §8), #9 (human intervention in §10), #11 (error format in §3), #13 (crash recovery in §7.4). The remaining 4 (#4 polling model details, #6 Clotho escalation UX, #7 CLI, #10 LLM abstraction) are partially addressed — the default polling is defined, LLM abstraction is in §4.1, and the remaining open questions are documented in §21 with notes on their resolution path.

- [x] @hephaestus (v1): **stdlib-only constraint is both blessing and curse.** Blessing: no dependency hell, no version conflicts, reproducible builds. Curse: the stdlib has no YAML parser (`yaml` is not stdlib), no subprocess timeout before Python 3.12 (`subprocess.run(timeout=)` works but not `Popen.wait(timeout=)` cleanly on older 3.x), and no built-in async/event-loop for polling. The spec says "stdlib only" but YAML parsing/emission will require either a custom YAML parser (a significant undertaking) or the spec should clarify that Clotho emits YAML as raw strings and Themis parses it with a simple hand-written parser. This needs a concrete decision.
  > @daedalus: Addressed in v2. §5 now documents that YAML is emitted as raw strings (Clotho uses string formatting/templates) and parsed by a minimal handwritten YAML parser in `moirai/yaml_util.py` that supports the documented subset. Stdlib subprocess.Popen and polling handle process management. No async event loop needed — the scheduler uses synchronous polling with configurable intervals.

- [x] @hephaestus (v1): **No module/package structure defined.** A developer doesn't know the directory layout: are components in a single `moirai/` package with submodules (`moirai/clotho.py`, `moirai/lachesis.py`)? Is there a `moirai/models.py` for shared types? An `__init__.py` that wires the pipeline? An entrypoint script? This needs a skeleton before parallel implementation can begin.
  > @daedalus: Addressed in v2. Added §2 Module / Package Structure with the complete directory tree: `moirai/` with submodules for each component, `types.py`, `protocols.py`, `config.py`, `persistence/`, `agents/`, `logging_utils.py`, `metrics.py`, `audit.py`, `human_intervention.py`, etc.

- [x] @hephaestus (v1): **No serialization format for cross-component communication.** Themis produces a `StateMachine` that Lachesis consumes. Is it a Python object passed in-memory? A JSON blob on disk? A pickled object? The "single-process" assumption (Assumption #6) suggests in-memory is fine, but Lachesis also persists state. The boundary between "in-memory data flow" and "persisted state" is blurry and needs explicit design.
  > @daedalus: Addressed in v2. In-memory communication uses the dataclass types from §3 (Python objects passed between components within the same process). Persistence uses JSON with the format defined in §18 (magic bytes, checksum, schema version). The boundary is clear: Lachesis calls PersistenceBackend methods to persist TaskState objects, and reads them back as the same types.

---

## Clotho (§2.1, now §7.1) — YAML Generation (LLM)

- [x] @hephaestus (v1): **LLM call interface is undefined.** Clotho "has access to a configured LLM" but how? What function does it call? What's the signature? Does it stream? Is there a retry on API error? A developer needs at minimum a protocol like `LLMClient(prompt: str, system_prompt: str, max_tokens: int, timeout: int) -> str` before they can write Clotho's core loop.
  > @daedalus: Addressed in v2. §4.1 LLMClient Protocol defines the exact signature: `complete(prompt, system_prompt, max_tokens, temperature, timeout_seconds) -> str`. Includes raise-on-error for TimeoutError, ConnectionError, RateLimitError. CircuitBreaker and LLMRateLimiter protocols are also defined.

- [x] @hephaestus (v1): **YAML schema is undefined (Open Question #1).** Clotho's entire purpose is to generate YAML in a specific schema. Without that schema — what fields a task has, how dependencies are expressed, what agent references look like, what the top-level keys are — Clotho's prompt template and output parsing cannot be written. This is the single biggest implementability gap for Clotho.
  > @daedalus: Addressed in v2. §5 YAML Workflow Schema defines the complete schema with a full example YAML document and a table of every field (parent, required/optional, type, description, default). Clotho now knows exactly what to generate.

- [x] @hephaestus (v1): **"Clotho may investigate the task's state as it sees fit" is unimplementable as-is.** For mid-flight hang recovery (§3.3), Clotho is given `hanging_task_info` and told it "may investigate the issue however it wishes." This is too open-ended for a developer to code against. What are the allowed investigation primitives? Read log files from a known path? Call a `list_tasks()` API? Query persistence? Without bounded investigation capabilities, the implementation will either do nothing useful or grow unboundedly. Needs at minimum a `TaskInvestigator` context object with defined methods.
  > @daedalus: Addressed in v2. §4.6 TaskInvestigator Protocol provides bounded methods: `read_logs(task_id, max_lines)`, `get_task_state(task_id)`, `list_workflow_tasks()`, `get_workflow_context()`. Clotho's investigation is now bounded and deterministic. HangingTaskInfo dataclass is also defined in §7.1.

- [x] @hephaestus (v1): **Retry loop has no backoff or jitter.** §3.2 describes Clotho↔Themis retries but doesn't mention waiting between attempts. If the LLM API returns a transient error (rate limit, temporary outage), back-to-back retries burn through `max_retries` instantly. A developer needs guidance on retry timing: exponential backoff? Fixed interval? Maximum total retry duration?
  > @daedalus: Addressed in v2. §7.1 documents exponential backoff with jitter: base 1s, multiplier 2x, max 30s, with jitter. Config params in §13: llm_retry_base_delay, llm_retry_max_delay, llm_max_retries.

- [x] @hephaestus (v1): The input parameters (`user_prompt`, `previous_yaml`, `validation_errors`, `hanging_task_info`, `max_retries`) are well-specified with types and descriptions. A developer knows exactly what data Clotho receives.

---

## Themis (§2.2, now §7.2) — YAML Validator & State Machine Generator (LLM)

- [x] @hephaestus (v1): **LLM-based DAG acyclicity check is both unsound and unnecessary.** Implementing this as an LLM call means the developer must: (a) craft a prompt that asks the LLM to verify acyclicity, (b) parse the LLM's natural-language response to get a yes/no, (c) handle the case where the LLM is wrong. This is strictly worse than a 15-line DFS topological sort. A developer would (and should) immediately move this to a deterministic function, so the spec should just say so. The 15-line deterministic check is trivial; the LLM-based check is fragile and unreliable.
  > @daedalus: Addressed in v2. Added §6 GraphValidator — deterministic DFS-based cycle detection, topological sort, and structural checks. Themis no longer has any responsibility for DAG acyclicity. The 15-line algorithm is explicitly referenced.

- [x] @hephaestus (v1): **ValidationError structure is undefined (Open Question #11).** The entire retry loop depends on Themis returning structured errors that Clotho can act on. Without knowing the error schema (does it include YAML line number? field path? error code? human-readable message? severity?), neither Themis's output formatter nor Clotho's error parser can be implemented. This is a hard dependency for the Clotho↔Themis loop.
  > @daedalus: Addressed in v2. §3 defines `ValidationError` dataclass with field (dot-separated path), message, severity (error/warning), yaml_line (optional int), error_code (machine-readable string), task_id (optional). Open Question #11 is marked RESOLVED.

- [x] @hephaestus (v1): **State machine output format is undefined (Open Question #5).** Themis produces a `StateMachine` that flows to Lachesis and Penelope. Without knowing its structure (nodes list? adjacency dict? edge properties? start/end markers?), none of the three downstream components can be implemented. This blocks Lachesis, Penelope, and Themis itself.
  > @daedalus: Addressed in v2. §3 defines `StateMachine` dataclass with workflow_id, version, tasks (dict[str, TaskDef]), dependencies (dict[str, list[str]]), entry_points (list[str]), metadata. Open Question #5 is marked RESOLVED.

- [x] @hephaestus (v1): **`known_agents` source is undefined (Open Question #8).** Themis needs a list of known agents to cross-reference. Where does this come from? A config file? A discovery service? A hardcoded list? Without this, the agent-validation feature cannot be implemented. A developer needs at minimum a `AgentsConfig` file format (JSON, YAML, TOML) specified.
  > @daedalus: Addressed in v2. §8 Agent Registry defines YAML config file at `~/.moirai/agents.yaml` with AgentDef structure. Loaded at startup. Open Question #8 is marked RESOLVED.

- [x] @hephaestus (v1): The separation of syntactic vs. semantic validation (Clotho produces syntactically valid YAML, Themis checks semantics) is a clean architectural boundary that a developer can reason about.

---

## Lachesis (§2.3, now §7.4) — Deterministic Scheduler

- [x] @hephaestus (v1): **Task dispatch mechanism is undefined (Open Question #2).** This is the single biggest implementation question for Lachesis. Does it use: `subprocess.Popen` for each task? A thread pool? `asyncio.create_subprocess_exec`? The mechanism choice affects: how task output is captured, how Atropos kills tasks (PID tracking), how Lachesis discovers completion (`waitpid()` vs. `Future.result()` vs. polling), and how the persistence layer is notified. A developer cannot write a single line of Lachesis's core loop without this decision.
  > @daedalus: Addressed in v2. §9 Task Dispatch / Process Model defines subprocess.Popen with process-group isolation. ProcessManager Protocol (§4.3) abstracts spawning, polling, and signaling. The dispatch mechanism is explicit. Open Question #2 is marked RESOLVED.

- [x] @hephaestus (v1): **Polling model is undefined (Open Question #4).** How does Lachesis discover task completion? If using subprocesses, does it block on `os.waitpid()`? If using threads, does it use a `concurrent.futures` callback? If using file-based status, does it poll a directory? Each model has different code structure and complexity. The spec says "poll" but doesn't say what is being polled. This is a hard implementation blocker.
  > @daedalus: Addressed in v2. §7.4 documents the polling loop: non-blocking ProcessManager.poll() for each running task on each iteration of the scheduler loop. No blocking waitpid, no callbacks, no file-based polling. Clear pseudocode provided.

- [x] @hephaestus (v1): **PersistenceBackend interface methods are undefined.** The spec says Lachesis depends on a `PersistenceBackend` but doesn't define its methods. A developer needs at minimum: `get_task(task_id) -> TaskState`, `set_task(task_id, state)`, `list_tasks() -> list[TaskState]`, `atomic_transaction(ctx) -> ContextManager`. Without this, PersistenceBackend is just a named type with no contract.
  > @daedalus: Addressed in v2. §4.2 PersistenceBackend Protocol defines all methods with signatures: get_task(), set_task(), list_tasks(), get_execution_state(), set_execution_state(), atomic_transaction(), health_check(), get_schema_version(), set_schema_version().

- [x] @hephaestus (v1): **DAG traversal algorithm is the bright spot — fully implementable.** The ready-queue management logic (find tasks with all deps satisfied → mark ready → dispatch → on completion check downstream deps) is textbook topological execution. Once `StateMachine` is defined, this is ~50 lines of deterministic Python that can be implemented, unit-tested, and verified. A developer will enjoy writing this part.
  > @daedalus: Addressed in v2. StateMachine is now defined in §3. The traversal algorithm is documented in §7.4 with explicit pseudocode.

- [x] @hephaestus (v1): **Mid-flight consolidation pause/resume is complex and underspecified.** When Lachesis detects a new YAML mid-flight, it must: (a) pause execution, (b) capture a consistent execution state snapshot, (c) call Penelope, (d) apply the consolidation plan, (e) resume execution. The spec doesn't describe: how Lachesis detects new YAML (a signal file? a callback? a watchdog?), how it atomically pauses (what if a task completes between detection and snapshot?), or how it resumes (from the top of the new ready queue?). This is a multi-step protocol that needs a formal design.
  > @daedalus: Addressed in v2. §7.4 documents the pause-capture-consolidate-resume protocol with atomic pause (Lachesis stops the scheduler loop, no new tasks dispatched, no polls accepted during consolidation). Detection of new YAML is via a state machine signal file. Resume re-computes the ready queue from the new state machine's topological order.

- [x] @hephaestus (v1): **Hang detection criteria are configurable but the detection mechanism is undefined.** §2.3 says "Detect hanging tasks (crashed X times, running over timeout)." How does Lachesis know a task has crashed N times? Does it track crash counts in persistence? In memory? How does it detect "running over timeout" — does it run a periodic check? A timer per task? The mechanism impacts both Lachesis internals and the persistence schema.
  > @daedalus: Addressed in v2. §7.4 defines the hang detection mechanism: crash count tracked in TaskState.attempts (persisted), runtime tracked by comparing TaskState.started_at against TimeProvider.now() at hang_check_interval_seconds intervals. Clear logic: attempts > task_def.max_retries → hanging; now - started_at > task_def.timeout → hanging.

---

## Penelope (§2.4, now §7.5) — Consolidation (Deterministic)

- [x] @hephaestus (v1): **Pure function with clear I/O — the easiest component to implement.** Once `StateMachine`, `ExecutionState`, and `ConsolidationPlan` are defined, Penelope is a straightforward diff algorithm. The consolidation rules (§2.4 bullet list) are enumerated clearly. A developer can implement this in an afternoon once the types exist.
  > @daedalus: Addressed in v2. All types are now defined in §3.

- [x] @hephaestus (v1): **"Modified tasks: state transferred if compatible" is the only vague rule.** What does "compatible" mean? Same `task_id` + same agent? Same `task_id` + same command? Any two tasks with the same `task_id` regardless of other properties? What happens to a `running` task that becomes modified — does it stay running (risky) or get reset to `pending`? This needs a precise compatibility matrix.
  > @daedalus: Addressed in v2. §7.5 now includes a full compatibility matrix: same agent + same command → compatible (RUNNING resets to PENDING, COMPLETED stays if backward-compatible). Different agent or command → incompatible (treated as removed+new, RUNNING gets Atropos-cancelled before removal, COMPLETED causes consolidation failure). No ambiguity remains.

- [x] @hephaestus (v1): **No rollback mechanism for partial consolidation.** If Penelope determines mid-application that consolidation is impossible (e.g., a completed task was removed), but has already modified some task states, the persistence layer is now inconsistent. The spec doesn't describe transactional boundaries or rollback. A developer needs to implement either: (a) Penelope as a pure "validate then apply" two-phase process, or (b) a persistence transaction that can be rolled back.
  > @daedalus: Addressed in v2. §7.5 implements the two-phase process: Phase 1 (validation) computes the entire ConsolidationPlan in memory without touching persistence; Phase 2 (application) only runs if can_consolidate=True, and applies all changes within a single PersistenceBackend.atomic_transaction(). If application fails mid-way, the transaction rolls back atomically.

---

## Atropos (§2.5, now §7.6) — Cleanup (Deterministic)

- [x] @hephaestus (v1): **Step-by-step behavior sequence is well-specified.** Items 1-7 (SIGTERM → wait → SIGKILL → capture logs → mark failed → record report → request human intervention) are clear. A developer can implement this as a straightforward procedure.

- [x] @hephaestus (v1): **Process signaling ignores subprocess grandchildren.** The spec assumes `kill(PID)` is sufficient, but if a task spawns subprocesses (e.g., a shell script), only the immediate child is killed. The grandchildren survive as orphans. The implementation needs `os.setpgid()` before task start and `os.killpg()` for cleanup. This is a one-line fix but needs to be designed in from the start.
  > @daedalus: Addressed in v2. §7.6 now uses `os.killpg(pgid, SIGTERM/SIGKILL)` for process-group-level signaling. §4.3 ProcessManager.spawn() places the child in a new process group via os.setpgid(). §9 documents process-group isolation as the standard mechanism.

- [x] @hephaestus (v1): **Log capture path is undefined.** "Capture stdout/stderr from the task's log files" — where are these files? What naming convention? What directory? Without specifying the log storage convention, the implementation can't be consistent between Lachesis (which spawns tasks with certain stdout/stderr redirection) and Atropos (which reads those logs).
  > @daedalus: Addressed in v2. §9 defines the log file path convention: `{log_dir}/{workflow_id}/{task_id}/{timestamp}.stdout` and `{log_dir}/{workflow_id}/{task_id}/{timestamp}.stderr`. ProcessManager captures these paths at spawn time and stores them in ProcessInfo. Atropos reads them via ProcessManager.read_output().

- [x] @hephaestus (v1): The behavior boundary (cleanup only → escalate) is clean and implementable. Atropos does not attempt to fix or retry — it kills, logs, and escalates. This is good engineering.

---

## What's Needed to Start Coding (Top 5 Gaps)

As a developer sitting down to write `moirai/__init__.py` and the first component, here is what I need that the spec doesn't provide:

| # | What's Missing | Why It Blocks Coding | Status |
|---|---------------|---------------------|--------|
| 1 | **Data structure definitions** for StateMachine, ValidationError, ConsolidationPlan, ExecutionState, TaskState, PersistenceBackend, AgentDef | Cannot write a single function signature or assert on any output without these | ✅ §3 |
| 2 | **YAML workflow schema** — the actual format Clotho emits and Themis validates | Clotho cannot generate YAML without knowing the schema; Themis cannot validate against an undefined schema | ✅ §5 |
| 3 | **Task dispatch mechanism** — subprocess? thread? asyncio? | Determines the entire architecture of Lachesis, Atropos, and the agent interface | ✅ §9 |
| 4 | **LLM client abstraction** — how Clotho and Themis call the LLM | Both components are entirely blocked without knowing the function signature, timeout, and error handling for LLM calls | ✅ §4.1 |
| 5 | **Agent registry and interface** — how agents are registered, what interface they expose | Themis cannot cross-reference agents; Lachesis cannot dispatch to an undefined agent interface; Atropos cannot clean up an undefined process model | ✅ §8, §4.3 |

**The minimum viable spec for a developer to begin** is now complete: (a) dataclass definitions for all shared types (§3), (b) the YAML schema (§5), (c) the LLM client protocol (§4.1), (d) the persistence backend protocol (§4.2), and (e) the task dispatch protocol (§9).

---

## Component Implementability Scores

| Component | Score (v1) | Score (v2) | Reasoning |
|-----------|:-----:|:-----:|-----------|
| **Clotho** | D | B- | LLM interface defined, YAML schema defined, investigation bounded — still needs prompt engineering |
| **Themis** | D | B | LLM interface defined, all types defined, DAG check extracted — now a focused semantic validator |
| **Lachesis** | C- | B | Dispatch, polling, persistence, hang detection all defined — crash recovery and graceful shutdown also specified |
| **Penelope** | B | A | Types defined, compatibility matrix explicit, two-phase atomicity — pure function, ready to implement |
| **Atropos** | C | B+ | Process group management, retry loop, log path convention, ProcessManager protocol — step-by-step procedure clear |
| **Integration / Wiring** | D | C+ | Pipeline composition documented, mid-flight recovery protocol defined, test harness specified — still requires careful orchestration |

|**Bottom line:** The spec has moved from architecture-concept level to implementation-ready. All 5 foundational gaps are resolved. A competent Python developer can now implement all components with confidence.

  > @atlas (v2): Looks good, closing.

---

# Argus Panoptes — Testability Review (v3: Loop Steps)

> Review date: 2026-07-08
> Focus: Testability of loop steps — inner steps, iteration logic, terminate_on matching

---

## Loop Step Execution Logic (§7.4)

- [x] @argus (v3): **Loop iteration logic is embedded inside Lachesis, not extracted into a testable unit.** The full iteration lifecycle (§7.4 items 1-9) is described as procedural steps within Lachesis's scheduler loop. This means testing iteration boundaries (1 run, N runs, max_iterations exhaustion), terminate_on matching, iteration context passing, and inner step dispatch all require wiring up a full Lachesis with fakes. The logic should be extracted into a standalone `LoopExecutor` with a defined interface (`execute_iteration(loop_state, state_machine) -> LoopStatus` or similar) that can be unit-tested in isolation without the scheduler loop. The `FakeLoopExecutor` named in §19.4 hints at this but provides no interface or behaviour — it's a placeholder, not a spec.
  > @daedalus: Addressed in v4. Added §4.7 LoopExecutor Protocol with `execute_iteration()`, `check_terminate_on()`, and `build_iteration_context()` methods. Added `LoopIterationResult` dataclass. Added `loop_executor.py` to module structure (§2). Updated §7.4 to delegate loop iteration to LoopExecutor. `FakeLoopExecutor` now has a defined contract (§19.4).

- [x] @argus (v3): **`terminate_on` substring matching is not extracted into a pure, independently testable function.** The spec says "Check if the output contains the `terminate_on` substring" (§7.4 item 4), which is trivially testable as a pure function (`matches_termination_condition(output: str, condition: str) -> bool`). But it's described as inline logic within Lachesis's loop management, not isolated into its own function or strategy object. Without extraction, a change to the matching strategy (e.g., regex, JSON field matching, structured output) would require modifying Lachesis itself rather than swapping a strategy implementation.
  > @daedalus: Addressed in v4. `LoopExecutor.check_terminate_on()` defined as a pure function on the protocol (§4.7). Uses whole-word matching (`\bcondition\b`). Upgraded from bare substring to word-boundary regex to address the false-positive issue raised by Themis. Testable independently in `tests/loop_executor_test.py`.

- [x] @argus (v3): **Context passing between iterations is undefined (Open Question #16).** The spec says "The previous iteration's outputs are available as context for the next iteration (passed via `inputs` or environment)" but the mechanism is deliberately left as an open question. This blocks testing of the iteration handoff — you cannot write a test that verifies iteration N receives iteration N-1's final output until the passing mechanism is formalised. Recommend specifying at minimum a `context: dict[str, str]` parameter that flows between iterations, so tests can assert on its contents.
  > @daedalus: Addressed in v4. Open Question #16 resolved. Mechanism: `LoopExecutor.build_iteration_context()` sets env vars `MOIRAI_LOOP_ITERATION=N`, `MOIRAI_PREV_OUTPUT=<leaf_output>`, and `MOIRAI_PREV_OUTPUTS_<STEP_ID>=<output>` per step. `LoopTaskState.last_inner_outputs: dict[str, str]` is the authoritative persisted source. See §7.4 item 6 and §4.7.

- [x] @argus (v3): **Inner step execution shares the same concurrency pool as outer tasks with no isolation.** Inner steps within a loop are dispatched "following the same process model as outer tasks" (§7.4 item 3) and use the same `ProcessManager` and `max_concurrent_tasks` limit. An active loop with multiple parallel inner steps can starve outer tasks (or other loops) of concurrency slots. For testing, there's no boundary to verify that loop-internal scheduling doesn't interfere with outer-DAG scheduling. Recommend loop steps get their own `max_concurrent_inner` config (defaulting to sequential execution = 1) to keep inner dispatch independently testable.
  > @daedalus: Addressed in v4. Added `LoopDef.max_concurrent_inner: int = 1` (§3) and `default_loop_max_concurrent_inner: int = 1` to config (§13). LoopExecutor uses its own concurrency limit, independent of the outer scheduler's `max_concurrent_tasks`. Inner steps do not consume outer scheduler concurrency slots.

- [x] @argus (v3): **Inner step hang detection may double-handle with outer hang detection.** §7.4 says "Hang detection applies equally to inner steps within a loop — if an inner step hangs, it is cleaned up by Atropos and the loop step is marked FAILED." But Lachesis's main polling loop iterates over "each running task" globally. If both the inner step (as a subprocess) and the loop step (as an opaque outer node) appear in the same polling pass, there's potential for double-handling — Atropos could be called on the inner step, then on the loop step itself. The spec should clarify whether inner steps are polled through the same scheduler path or abstracted behind the loop step's own execution manager.
  > @daedalus: Addressed in v4. Inner steps are polled through LoopExecutor, NOT through Lachesis's main polling loop. §7.4 item 4 documents this explicitly: "Inner steps are polled through LoopExecutor... This avoids double-handling with outer hang detection." Atropos receives the inner step's scoped task_id (`{loop_id}.{inner_step_id}`) for cleanup.

## Loop Step Crash Recovery (§7.4)

- [x] @argus (v3): **Crash recovery for loops discards inner state and re-enters from the start of the current iteration.** §7.4 crash recovery says loop tasks in `ITERATING` state are "reset to their last completed iteration boundary (inner task state is discarded, loop re-enters the iteration from the start of the current iteration)." This means inner steps that had already completed in the current iteration will be re-executed — which is safe but requires testing. However, this is only testable via an integration test that simulates Lachesis crash + restart with a persisted loop mid-iteration. There is no unit-level test path for this scenario. Consider adding a `LoopTaskState.recover()` method that can be unit-tested.
  > @daedalus: Addressed in v4. Crash recovery clause in §7.4 now explicitly states: "current_iteration counter is preserved (not decremented), so iteration N is re-attempted from scratch. LoopTaskState.last_inner_outputs (persisted) provides context for the re-started iteration." The dependency on persisted `last_inner_outputs` is documented. Unit-testable via `LoopExecutor.execute_iteration()` with a state loaded from a crashed checkpoint.

## Loop Step Opaqueness Invariant (§6, §20 Assumption #8)

- [x] @argus (v3): **No isolated test fixture for the "loop step is opaque to the outer DAG" invariant.** Assumption #8 and §6 both state loop steps are treated as single opaque nodes for outer acyclicity. The testing strategy (§19.3) lists a property-based invariant but no concrete unit-test fixtures for GraphValidator that verify: (a) an outer cycle *through* a loop step is detected, (b) an inner cycle does NOT cause an outer acyclicity failure, (c) cross-boundary dependency references are caught (inner step depending on outer task, outer task depending on inner step). These should be added as explicit table-driven test cases.
  > @daedalus: Addressed in v4. Added explicit loop-opaqueness invariants with test fixture descriptions in §6 (after item 9). §19.1 now lists "loop-opaqueness invariants: outer cycle through loop detected, inner cycle NOT flagged as outer cycle, cross-boundary dep rejected" as GraphValidator test fixtures.

## Penelope Loop Consolidation (§7.5)

- [x] @argus (v3): **Loop step consolidation rules are testable but have a gap in the compatibility matrix.** The rules for PENDING → reset, ITERATING → reset, COMPLETED/EXHAUSTED → fail, and type conversion → removed+new are all pure-function testable — good. **However**, there's a missing rule: what happens when a loop step's `terminate_on` string changes mid-flight while the loop is ITERATING? Is the new condition picked up on the next iteration (compatible), or does the loop need to reset to PENDING (incompatible)? The consolidation matrix doesn't address this case, leaving it ambiguous for tests.
  > @daedalus: Addressed in v4. Added explicit rule: "Loop step changed — terminate_on modified: If PENDING or ITERATING: compatible (condition changes take effect next iteration). Loop is NOT reset to PENDING — the current iteration continues with the new condition. If COMPLETED or EXHAUSTED: fail (unless EXHAUSTED with only max_iterations increase, see below)." See §7.5 consolidation rules table.

## GraphValidator Loop Validation (§6)

- [x] @argus (v3): **GraphValidator loop validation is well-specified and testable.** §6 items 8-9 define clear deterministic checks: inner dependency scoping, connected sub-graph within the loop, non-empty steps, positive max_iterations, non-empty terminate_on, no cross-boundary references. These are pure-function tests with table-driven graph fixtures — the gold standard of testability. No issues found.

## Test Infrastructure (§19.4)

- [x] @argus (v3): **`FakeLoopExecutor` in test infrastructure (§19.4) is undefined.** It's listed as a test fake alongside `FakeLLMClient`, `FakeProcessManager`, `MemoryBackend`, etc., but has no specification — no interface it implements, no methods, no behaviour contract. Every other fake in the list has a corresponding protocol defined in §4 (LLMClient, ProcessManager, PersistenceBackend, TimeProvider, HumanNotifier). No corresponding `LoopExecutor` or `LoopRunner` protocol exists anywhere in the spec. A protocol needs to be defined first before the fake has a contract to implement.
  > @daedalus: Addressed in v4. Added §4.7 LoopExecutor Protocol with defined methods. `FakeLoopExecutor` is now specified in §19.4 as implementing `LoopExecutor` protocol with configurable behavior (returns predefined `LoopIterationResult`).

## Property-Based Testing (§19.3)

- [x] @argus (v3): **Two loop-related invariants are listed for property-based testing.** §19.3 includes: "For any loop step with a valid inner DAG, the number of iterations never exceeds max_iterations" and "A loop step is opaque to the outer DAG — the outer graph's acyclicity is preserved regardless of inner step topology." These are good invariants. No issues found with the properties themselves, though they depend on the `LoopExecutor` abstraction being extracted (see above) to be practically testable.

---

## Summary

| Area | Status | Key Gaps |
|------|--------|----------|
| **Iteration logic isolation** | ❌ Not extracted | Embedded in Lachesis — should be `LoopExecutor` |
| **terminate_on matching** | ❌ Not extracted | Inline in Lachesis — should be pure function/strategy |
| **Context passing** | ❌ Open Question #16 | Mechanism undefined — can't test |
| **Inner concurrency isolation** | ❌ Undefined | Shares outer pool — testability unclear |
| **Inner hang detection** | ⚠️ Ambiguous | Double-handling risk with outer polling |
| **Crash recovery for loops** | ⚠️ Integration-only | No unit-level test path |
| **Loop opaqueness invariant** | ⚠️ Property-only | No concrete table-driven GraphValidator fixtures |
| **Penelope loop rules** | ⚠️ Gap in matrix | Missing rule for terminate_on change mid-iteration |
| **GraphValidator loop validation** | ✅ Good | Pure function, table-driven |
| **Property-based invariants** | ✅ Good | Two listed, well-formed |
| **FakeLoopExecutor** | ❌ No contract | No protocol defined — can't implement |

**Biggest structural recommendations for loop testability (priority order):**

1. Extract loop iteration logic into a standalone `LoopExecutor` protocol + implementation, testable via `FakeProcessManager`.
2. Extract `terminate_on` matching into a pure function/strategy with a defined interface.
3. Resolve Open Question #16 (context passing between iterations) to unblock iteration handoff tests.
4. Add concrete table-driven GraphValidator test cases for loop opaqueness invariants.
5. Define the `LoopExecutor` protocol so `FakeLoopExecutor` has a contract.

---

# Hephaestus — Implementability Review (v3)

> Review date: 2026-07-08
> Focus: Loop step additions — implementability, well-defined iteration logic, missing details
> Role: Master builder / developer — can I implement the loop iteration logic from this spec?

---

## Loop Step Data Structures (§3)

- [x] @hephaestus (v3): **Inner step type mismatch — `TaskDef.deps` vs. inner step `depends_on`.** The YAML schema (§5) uses `depends_on` for inner steps, but `LoopDef.inner_steps` is typed as `list[TaskDef]`, and `TaskDef` has a field named `deps`, not `depends_on`. A developer needs to know: is there a separate `InnerTaskDef` type? Does the YAML parser map `depends_on → deps` on load? Or is there a field alias? Without this decision, the inner step objects that Lachesis receives will have empty `deps` lists because the YAML used the wrong key name. This is a concrete implementation blocker.
  > @daedalus: Addressed in v4. Unified field naming: both outer tasks and inner steps now use `deps` in the YAML schema (§5). The YAML parser accepts both `deps` and `depends_on` for backward compatibility with v3 workflows, mapping both to `TaskDef.deps`. Inner steps are `TaskDef` objects (no separate type needed).

- [x] @hephaestus (v3): **`LoopTaskState.inner_execution_order` source is undefined.** The field exists in the dataclass with `field(default_factory=list)`, but the spec never says who populates it or when. Is it computed by GraphValidator during inner validation? By Lachesis at iteration start via a topological sort of inner steps? The spec mentions "final step in the inner execution order" but doesn't define how that order is determined. A developer needs a clear statement: "Lachesis computes a topological sort of inner_steps at first dispatch and stores it in `inner_execution_order`."
  > @daedalus: Addressed in v4. `LoopTaskState.inner_execution_order` is now documented as the cached topological order computed by Lachesis (LoopExecutor) at first dispatch (§3 docstring on field, §7.4 item 1). It's a pre-computed deterministic order used as a tiebreaker for leaf-step ordering.

- [x] @hephaestus (v3): **`LoopDef.terminate_on` default empty string vs. YAML "required" vs. GraphValidator non-empty check.** Minor inconsistency: the dataclass defaults `terminate_on` to `""`, the YAML schema says it's required, and GraphValidator rejects empty strings. This means you can create a `LoopDef("my-loop")` in Python code that passes runtime type checks but fails GraphValidator validation. A `None` default with a `@dataclass` validator or a clear comment would eliminate ambiguity. Recommend: make `terminate_on: str` (no default) in the dataclass, since it's required semantically.
  > @daedalus: Addressed in v4. `terminate_on` is now allowed to be empty (""), designating a counter-controlled loop. §6 GraphValidator no longer rejects empty `terminate_on`. §5 schema marks it as no longer "required" — default is empty string. Empty terminate_on means the loop runs exactly `max_iterations` iterations and reports COMPLETED. See §3 docstring on `LoopDef.terminate_on` and §7.4 item 5 (counter-controlled loop path).

## YAML Schema (§5)

- [x] @hephaestus (v3): **Inner steps use `depends_on` while outer tasks use `deps` — inconsistent naming.** The YAML schema table shows inner steps use `depends_on` (line 604) but outer tasks use `deps` (line 588). This inconsistency means Clotho's prompt template must know to emit different key names for inner vs. outer steps, and the YAML parser must handle both. If the intent is to avoid confusion with outer `deps`, then either rename outer `deps` to `depends_on` for consistency, or use a unified field name everywhere. Different names for the same concept (dependency list) increases implementation surface area for no clear benefit.
  > @daedalus: Addressed in v4. Unified to `deps` throughout. Both outer tasks and inner steps now use `deps`. The YAML parser accepts both `deps` and `depends_on` for backward compatibility with v3 workflows, with a deprecation warning for `depends_on`. See §5 table note.

- [x] @hephaestus (v3): **`terminate_on` is marked as "required" but has a default value (5).** The schema table says terminate_on is "yes" required. This is correct architecturally — every loop needs a termination condition. But the default value column shows 5 (which is max_iterations' default), and terminate_on has no default shown. The table formatting is slightly confused here. Not a blocker, but the table should show `terminate_on` has no default (it's required).
  > @daedalus: Addressed in v4. `terminate_on` is now optional (default: `""`) in the schema table. Empty string designates a counter-controlled loop. The table now correctly shows no default for required fields and `""` default for terminate_on. The formatting issue with "5" in the wrong column is fixed.

## GraphValidator (§6)

- [x] @hephaestus (v3): No issues. Opaque-node treatment for loop steps in outer DAG acyclicity is correct and implementable. Cross-boundary dependency validation (no outer → inner, no inner → outer) is clearly specified. Inner DAG connectivity check is well-scoped. All constraints (non-empty steps, positive max_iterations, non-empty terminate_on) are explicitly checkable.

## Lachesis — Loop Step Execution (§7.4)

- [x] @hephaestus (v3): **Ambiguous "final inner step" — undefined when inner DAG has multiple terminal nodes.** The spec checks `terminate_on` against "the output of the final inner step (by convention the last step in the inner execution order)." But if the inner DAG has parallel branches (e.g., A→B and C→D as independent chains), there are two terminal nodes with no topological ordering between them. Which output is "final"? The spec needs to define a rule: (a) there must be exactly one inner terminal node, or (b) all terminal outputs are checked, or (c) the `terminate_on` match is checked against a specific named step designated in the loop definition. Without this, the implementation is ambiguous for any non-linear inner DAG.
  > @daedalus: Addressed in v4. The rule is now: all leaf step outputs are collected. If `terminate_on` is non-empty, it's checked against ALL leaf step outputs using whole-word matching. If ANY leaf matches, the condition is met. This provides clear, deterministic semantics for parallel inner DAGs. See §7.4 item 5.

- [x] @hephaestus (v3): **Iteration context passing (Open Question #16) is a hard implementation blocker.** The spec says "The previous iteration's outputs are available as context for the next iteration (passed via `inputs` or environment)" — but this is aspirational, not actionable. Open Question #16 explicitly says "the mechanism needs precise specification." This means a developer cannot implement iteration context passing. Specific unknowns: (a) Are ALL inner step outputs from the previous iteration made available, or only the final step's output? (b) If via `inputs`, does Lachesis mutate the `LoopDef`'s step definitions to inject previous outputs as input parameters? (c) If via env vars, what naming convention is used? (d) Does context accumulate across iterations (iteration 3 sees outputs from iter 1 and 2) or is it only the immediately preceding iteration? This needs resolution before the loop implementation is complete.
  > @daedalus: Addressed in v4. Open Question #16 resolved. All answers: (a) ALL inner step outputs from the previous iteration are made available via `last_inner_outputs: dict[str, str]`; (b) Context is passed via environment variables, not by mutating step definitions; (c) Env var naming: `MOIRAI_LOOP_ITERATION=N`, `MOIRAI_PREV_OUTPUT=<leaf_output>`, `MOIRAI_PREV_OUTPUTS_<STEP_ID>=<output>`; (d) Only the immediately preceding iteration's outputs are available (not accumulated history — iteration history is kept in `iteration_log`). See §7.4 item 6 and §4.7 `build_iteration_context()`.

- [x] @hephaestus (v3): **Inner step failure leaves sibling steps orphaned.** The spec says "If any inner step fails... the loop step is marked FAILED immediately." But it doesn't specify what happens to other inner steps that are still RUNNING or PENDING in the same iteration. Should they be cancelled via Atropos? Left running as orphans? The current design would leak subprocesses. A developer needs: "On inner step failure, all RUNNING inner steps are passed to Atropos for cleanup, and all PENDING inner steps are marked CANCELLED."
  > @daedalus: Addressed in v4. §7.4 item 11 now explicitly states: "All RUNNING inner steps in the same iteration are passed to Atropos for cleanup. All PENDING inner steps are marked CANCELLED." Also documented in §11.6 item 11 and §12 error table entry for loop inner step crash.

- [x] @hephaestus (v3): **Inner step hang detection applies Atropos at the inner step level, but the loop step's outer status is unclear.** The spec says "if an inner step hangs, it is cleaned up by Atropos and the loop step is marked FAILED." But Atropos operates on the outer task_id (the loop step's ID), while the hanging entity is an inner step. How does Atropos know which process to kill — the inner step's subprocess or the loop step's (non-existent) process? Since loop steps don't have their own process (inner steps are the subprocesses), Atropos needs the inner step's ProcessInfo. But Atropos's interface takes a `task_id: str` and `task_process_info: ProcessInfo`. The developer needs to know whether Atropos receives the inner step's task_id or the loop step's task_id for inner step failures.
  > @daedalus: Addressed in v4. Atropos receives the inner step's scoped task_id (`{loop_id}.{inner_step_id}`) and the inner step's ProcessInfo for inner step hangs/cleanup. §7.6 input description updated to clarify: "for inner step hangs, this is the scoped ID `{loop_id}.{inner_step_id}`". §7.4 item 4 documents this explicitly.

- [x] @hephaestus (v3): **Crash recovery of ITERATING loops is loosely defined.** "Loop tasks in ITERATING state are reset to their last completed iteration boundary (inner task state is discarded, loop re-enters the iteration from the start of the current iteration)." This is ambiguous: does "the current iteration" mean the iteration that was in progress at crash time (which may have partially-completed inner steps), or does it mean the iteration before the one in progress? If an inner step completed in iteration 2 but Lachesis crashed before iteration 2 finished, is that inner step's work discarded? A clearer rule: "On crash recovery, ITERATING loops are reset to the start of the iteration indicated by `current_iteration`. All inner task state is discarded. The loop's `current_iteration` counter is preserved (not decremented), so that iteration N is re-attempted from scratch."
  > @daedalus: Addressed in v4. Crash recovery clause in §7.4 now reads: "Loop tasks in ITERATING state are reset to the start of the iteration indicated by `current_iteration`. All inner task state is discarded. The `current_iteration` counter is preserved (not decremented), so iteration N is re-attempted from scratch. `LoopTaskState.last_inner_outputs` (persisted) provides context for the re-started iteration."

## Penelope — Loop Step Consolidation (§7.5)

- [x] @hephaestus (v3): **Contradiction between exhaustion escalation and consolidation rules.** The escalation path in §7.4 says "Clotho may be invoked to generate a new YAML that modifies the loop step (e.g., increasing max_iterations, changing terminate_on)." But the Penelope consolidation rules say: "If [loop step is] COMPLETED or EXHAUSTED: fail — cannot change a loop whose execution has finished." This is a direct contradiction — the escalation path explicitly suggests modifying an EXHAUSTED loop (increasing max_iterations), but Penelope will reject that exact change. A developer implementing this will hit this contradiction immediately. Recommendation: resolve by either (a) allowing max_iterations increase for EXHAUSTED loops as a special case, or (b) removing the "increase max_iterations" suggestion from the escalation path and requiring a different recovery approach (e.g., replacing the loop step with alternative tasks).
  > @daedalus: Addressed in v4. Chose option (a): Penelope now allows `max_iterations` increase for EXHAUSTED loops as a special exception. See §7.5 consolidation rules table — "Loop step changed — max_iterations increased only: If EXHAUSTED: Allowed. The loop is reset to ITERATING with current_iteration preserved. Termination condition and inner step definitions must be identical."

- [x] @hephaestus (v3): **"Loop step changed — inner steps modified" rule for ITERATING doesn't specify cleanup.** The rule says: "If the loop step is PENDING or ITERATING: reset to PENDING and re-validate inner steps via GraphValidator." If the loop is ITERATING, there may be running inner step subprocesses. "Reset to PENDING" doesn't imply cleanup of those processes. A developer needs: "If ITERATING, first cancel all running inner steps via Atropos, then reset to PENDING."
  > @daedalus: Addressed in v4. The rule now reads: "If PENDING or ITERATING: cancel all running inner steps via Atropos, reset to PENDING, re-validate inner steps via GraphValidator." See §7.5.

## Human Intervention (§10) — Loop-Specific

- [x] @hephaestus (v3): No issues. RETRY and SKIP behaviors for loop steps are well-defined: RETRY resets the loop to PENDING and re-executes from iteration 1; SKIP marks the loop as completed as if terminate_on was met. These are implementable.

## Error Handling (§12)

- [x] @hephaestus (v3): No issues. The loop exhaustion and inner step crash error entries are consistent with the rest of the error table and clearly specify trigger, response, and recovery.

## Metrics (§15.2)

- [x] @hephaestus (v3): No issues. `loop_iterations` and `loop_exhaustions` counters are well-chosen and implementable.

## Persistence (§18)

- [x] @hephaestus (v3): No issues. The `loop_tasks` section in the persistence format example is clear and shows all relevant fields (status, loop_status, current_iteration, max_iterations, terminate_on, last_inner_output, inner_task_states). A developer can serialize/deserialize this confidently.

## Testing Strategy (§19)

- [x] @hephaestus (v3): No issues. Loop step integration test scenarios are mentioned (§19.2). Property-based invariant "number of iterations never exceeds max_iterations" is well-chosen (§19.3). `FakeLoopExecutor` in test infrastructure (§19.4) enables isolated testing. GraphValidator test fixtures include "loop-with-inner-deps" (§19.1). These are sufficient for a developer to write tests.

## Assumptions (§20)

- [x] @hephaestus (v3): No issues. Assumption #13 (bounded iteration) and #14 (text output for terminate_on) are clearly stated and inform implementable constraints.

## Open Questions (§21)

- [x] @hephaestus (v3): **Open Question #16 (iteration context passing) blocks complete implementation.** As noted above, the mechanism for passing outputs between loop iterations is underspecified. This needs resolution before the loop feature can be considered implementable. Recommended approaches (for resolution): (a) Lachesis sets environment variables `MOIRAI_LOOP_ITERATION=N` and `MOIRAI_PREV_OUTPUT=<last_inner_step_stdout>` for each inner step in subsequent iterations, or (b) Lachesis writes previous outputs to a well-known file path `{workspace}/{loop_id}/iteration_{N-1}/` and passes the path via an input parameter `previous_iteration_dir`. Either approach would be implementable.
  > @daedalus: Addressed in v4. Open Question #16 marked RESOLVED. Chose option (a) — environment variables. See §21.16 and §7.4 item 6 for full specification. `LoopExecutor.build_iteration_context()` sets `MOIRAI_LOOP_ITERATION=N`, `MOIRAI_PREV_OUTPUT=<leaf_output>`, and `MOIRAI_PREV_OUTPUTS_<STEP_ID>=<output>` per step.

## Summary

| Area | Grade | Key Issues |
|------|:-----:|------------|
| **Data structures** | B | Inner step type mismatch (deps vs depends_on); inner_execution_order source undefined |
| **YAML schema** | B | Inconsistent field naming (depends_on vs deps); terminate_on table formatting |
| **GraphValidator** | A | Clean; all constraints implementable |
| **Lachesis execution** | C+ | Ambiguous final-inner-step with parallel DAGs; iteration context passing is a hard blocker (Open Q #16); inner failure cleanup unspecified; Atropos invocation for inner steps unclear; crash recovery loose |
| **Penelope** | C | Contradiction between exhaustion escalation and consolidation rules; ITERATING cleanup unspecified |
| **Human intervention** | A | RETRY/SKIP for loops well-defined |
| **Error handling** | A | Consistent with rest of spec |
| **Persistence** | A | Format clearly shown |
| **Testing** | A | Adequate coverage |
| **Open Questions** | D | #16 blocks complete implementation |

**Top 3 implementation blockers requiring resolution:**

1. **Iteration context passing (§21 #16)** — The mechanism for passing previous iteration outputs to the next iteration's inner steps is unspecified. Without this, iteration 2+ of any loop is disconnected from iteration 1's results, making most real-world loop workflows (review→fix→review) non-functional.

2. **Contradiction: exhaustion escalation vs. Penelope rules** — The escalation path says Clotho can modify an EXHAUSTED loop (increase max_iterations), but Penelope's consolidation rules explicitly reject modifying a COMPLETED or EXHAUSTED loop. One of these must change.

3. **Ambiguous "final inner step" in parallel inner DAGs** — The terminate_on check references "the final inner step," but this is undefined when the inner DAG has multiple terminal nodes (parallel branches). Must define a deterministic selection rule.

---

# Themis — Quality & Correctness Review (v3: Loop Steps)

**Reviewer:** Themis (quality reviewer)
**Date:** 2026-07-08
**Scope:** SPEC.md v3 — loop step additions (inner cycle semantics, termination conditions, error handling)
**Focus:** Correctness — are loop semantics sound? Edge cases? Termination guarantees?

---

## Loop Step — Structural & Semantic Comments

- [x] @themis (v3): **Penelope blocks Clotho-mediated recovery of EXHAUSTED loops — §7.4 contradicts §7.5.** §7.4 (Lachesis, step 5 under "Loop Step Execution") states: *"If mid-flight recovery is enabled, Clotho may be invoked (with a bounded investigator) to generate a new YAML that modifies the loop step (e.g., increasing max_iterations, changing terminate_on, or replacing the loop with alternative steps)."* However, §7.5 (Penelope consolidation rules) states: *"Loop step changed — inner steps modified: If COMPLETED or EXHAUSTED: fail — cannot change a loop whose execution has finished."* This means any Clotho-generated YAML that modifies an EXHAUSTED loop step will be **rejected by Penelope** during consolidation. The only recovery paths for EXHAUSTED loops are human decisions (RETRY/SKIP/ABORT/RESTART from §10). The "Clotho may be invoked" path in §7.4 is a dead branch unless Clotho replaces the exhausted loop with entirely new non-loop steps (which would be a "removed + new" scenario, subject to the removed-task-was-running rule). **Recommendation:** Either (a) add an exception to Penelope's rule for EXHAUSTED loops to allow `max_iterations` or `terminate_on` changes, (b) remove the Clotho-recovery reference in §7.4, or (c) document that recovery via Clotho means replacing the loop entirely with alternative steps.
  > @daedalus: Addressed in v4. Chose option (a): Added a specific exception to Penelope's rules for EXHAUSTED loops — `max_iterations` increase ONLY is now allowed. Changes to `terminate_on` or inner step structure still fail and require human intervention. See §7.5 (two new rows in the consolidation rules table). The §7.4 escalation path is updated to reflect this: "Penelope allows max_iterations increase for EXHAUSTED loops (v4)."

- [x] @themis (v3): **Iteration context passing is critically underspecified** (§21, Open Question #16). The spec says previous iteration outputs are "available as context for the next iteration (passed via `inputs` or environment)" but provides no mechanism for how this works. Key unanswered questions: (a) Which inner steps' outputs are passed? All of them? Only the final step? (b) How are outputs mapped to the next iteration's inputs — by step ID? By output key? (c) If an inner step from iteration 1 produced `result=42` and the same step in iteration 2 accepts `{{ .inputs.previous_result }}`, how is that binding established? (d) What happens to stdout/stderr across iterations — overwritten or appended? **Recommendation:** This must be resolved before implementation. A concrete mechanism (e.g., `LoopTaskState.last_inner_outputs: dict[str, str]` mapping step_id → captured output, with a convention like `{{ .loop.previous.<step_id> }}` for input references) should be specified in §7.4 or a dedicated subsection.
  > @daedalus: Addressed in v4. Open Question #16 resolved. Answers: (a) ALL inner step outputs are passed via `last_inner_outputs: dict[str, str]` mapping step_id → stdout; (b) Context is passed via environment variables `MOIRAI_PREV_OUTPUTS_<STEP_ID>=<output>`, not by mutating inputs; (c) No `{{ }}` template binding in v1 — env vars are injected directly into inner step processes; (d) Log files now include iteration number: `{log_dir}/{workflow_id}/{loop_id}/iter_{N}/{inner_step_id}/stdout.log`. See §7.4 item 6, §4.7 `build_iteration_context()`, and §9 log path convention.

- [x] @themis (v3): **`terminate_on` matching is ambiguous for multi-leaf inner DAGs.** The spec says the `terminate_on` check is performed on the "output of the final inner step (by convention the last step in the inner execution order, e.g. 'review')". If the inner DAG has multiple leaf nodes (steps with no dependents — e.g., `implement → [review, lint]` where both review and lint are leaves), "the last step in the inner execution order" is ambiguous. A topological sort may produce a deterministic order, but it is not specified whether (a) only one leaf's output is checked, (b) all leaves' outputs are checked (any match), or (c) there must be exactly one leaf. **Recommendation:** Either constrain inner DAGs to have a single leaf node (simplest), check all leaf outputs for a match (most flexible with clear semantics), or specify that the execution order's last step in topological sort (with a tie-breaking rule) is authoritative.
  > @daedalus: Addressed in v4. Chose option (b) — all leaf step outputs are collected and checked against `terminate_on`. If ANY leaf matches (using whole-word matching), the condition is met. See §7.4 item 5.

- [x] @themis (v3): **`terminate_on` being required prevents counter-controlled (fixed-iteration) loops.** GraphValidator (§6 check #8) requires `terminate_on` to be a non-empty string, and the YAML schema table marks it as "yes (required)." This makes it impossible to express a simple "run exactly N times" loop without a dummy termination condition. A retry loop, a polling loop, or a batch-processing loop may legitimately want to iterate exactly `max_iterations` times without any early termination condition. **Recommendation:** Allow `terminate_on` to be empty/null, in which case the loop always runs exactly `max_iterations` iterations and reports as COMPLETED (not EXHAUSTED) when it reaches the limit.
  > @daedalus: Addressed in v4. `terminate_on` is now optional (default: `""`). Empty string designates a counter-controlled loop: runs exactly `max_iterations` iterations, reports COMPLETED (not EXHAUSTED). §6 no longer rejects empty `terminate_on`. §5 schema table updated. Assumption #16 added: "Counter-controlled loops: A loop step with empty terminate_on runs exactly max_iterations iterations and reports as COMPLETED."

- [x] @themis (v3): **No wall-clock timeout for loop steps as a whole.** Inner steps have per-step timeouts, and `max_iterations` bounds the iteration count, but there is no overall timeout for the loop step. A loop with 10-second inner steps and `max_iterations=5` could trivially be bounded, but a loop with 30-minute inner steps and `max_iterations=1000` (or even just `max_iterations=10`) could run for 5+ hours. In the latter case, a single infinite-loop-like condition in the inner logic could consume far more wall time than a regular task timeout. **Recommendation:** Add an optional `loop_timeout` field to `LoopDef` (default: `max_iterations * max_inner_step_timeout` or a configurable ceiling) that sets a wall-clock deadline for the entire loop, checked during the scheduler loop just like per-task timeouts.
  > @daedalus: Addressed in v4. Added `LoopDef.loop_timeout: Optional[int]` (seconds, §3) and `LoopTaskState.loop_timeout` (absolute Unix timestamp deadline, §3). LoopExecutor checks the deadline at the start of each iteration. If exceeded, the loop is marked FAILED with `TIMEOUT_EXCEEDED`. Default computed as `max_iterations * max(inner_step_timeout) * len(inner_steps)`. See §7.4 item 7.

- [x] @themis (v3): **Inner step dispatch semantics are unclear for non-linear inner DAGs.** §11.6 says inner entry-point steps are "dispatched sequentially" and "the next inner step (based on depends_on) becomes READY." This language suggests a fully sequential execution model. But inner steps have a dependency graph (`depends_on`), which could produce a diamond pattern (e.g., `a → [b, c] → d`). If dispatch is strictly sequential, parallel inner branches are not expressible despite appearing so in the schema. If inner DAGs are meant to support parallelism, the dispatch logic should reference `max_concurrent_tasks` and use the same ready-queue model as the outer DAG. **Recommendation:** Clarify whether inner steps can execute in parallel (respecting their `depends_on` edges) or are always sequential. If sequential is the intent, consider constraining inner steps to be a linear chain (no branching) and document this explicitly; if parallel is intended, specify the concurrency semantics.
  > @daedalus: Addressed in v4. Inner steps CAN execute in parallel (respecting their `deps` edges and `max_concurrent_inner` limit). Added `LoopDef.max_concurrent_inner: int = 1` (default 1 = sequential). When > 1, inner steps with satisfied dependencies run concurrently, governed by their own concurrency pool independent of the outer scheduler. The "sequential" language in §11.6 is updated to reference `max_concurrent_inner`. Assumption #15 added: "Inner step dispatch is parallelizable."

- [x] @themis (v3): **`terminate_on` substring matching can produce false positives.** §20 Assumption #14 acknowledges substring matching as the v1 approach. For example, `terminate_on="APPROVED"` matches the output "UNAPPROVED — needs fixes" because "UNAPPROVED" contains "APPROVED". This is a correctness risk that will manifest in production. **Recommendation:** At minimum, use whole-word matching (e.g., regex `\bAPPROVED\b`) rather than bare substring. Add a note that this is a v1 simplification that should be upgraded to explicit structured output matching (e.g., `exit_code 0` from a dedicated "check" step) in v2 of the loop feature.
  > @daedalus: Addressed in v4. `LoopExecutor.check_terminate_on()` uses whole-word matching (`\bcondition\b`) instead of bare substring. Assumption #14 updated from "substring match" to "whole-word matching." This prevents false positives (e.g., "APPROVED" does not match "UNAPPROVED"). Structured output matching is noted as a future enhancement.

- [x] @themis (v3): **Human RETRY on an exhausted loop discards all iteration history with no alternative.** §10 says RETRY on a loop "resets the loop to PENDING and re-executes from iteration 1." If a human manually approved a code change after 5 failed iterations, starting from iteration 1 would re-run `implement.sh`, potentially undoing the human's manual fix. There is no SKIP_AND_CONTINUE or "accept current state" option. SKIP marks the loop as completed (as if terminate_on was met), but SKIP doesn't allow the human to specify *what* the final output should be. **Recommendation:** Consider adding a `HumanDecision.CONTINUE` option that accepts the current iteration's output as meeting the termination condition (effectively a human override of `terminate_on`), allowing the workflow to proceed to downstream steps without resetting.
  > @daedalus: Addressed in v4. Added `HumanDecision.CONTINUE` to the enum (§3) and the decision protocol (§10). CONTINUE accepts the current iteration's output as meeting the `terminate_on` condition — the loop is marked COMPLETED with `loop_status = COMPLETED`. The `iteration_log` records this as a human-forced termination. For non-loop tasks, CONTINUE is treated as RETRY with a logged warning.

- [x] @themis (v3): **No execution log entries for individual loop iterations.** `ExecutionLog` (§3) tracks outer task states but has no mechanism to record per-iteration inner-step outcomes. `LoopTaskState.inner_task_states` is transient and overwritten each iteration. This means that after a loop completes, there is no persistent record of what happened in iteration 2 vs. iteration 4 — only the final state is preserved. For debugging exhausted loops or auditing multi-iteration workflows, this is a significant gap. **Recommendation:** Persist an iteration-level execution log (e.g., `LoopTaskState.iteration_log: list[dict]` listing each iteration number, its inner step outcomes, exit codes, and the `terminate_on` match result). This should be serialized in the persistence format alongside `loop_tasks`.
  > @daedalus: Addressed in v4. Added `LoopTaskState.iteration_log: list[dict]` (§3) that records each iteration number, inner step statuses/exit codes, terminate_on match result, and final output. Persisted alongside `loop_tasks` in the persistence format (§18). Log paths now include iteration number: `{log_dir}/{workflow_id}/{loop_id}/iter_{N}/{inner_step_id}/stdout.log` (§9).

- [x] @themis (v3): **Crash recovery resets to "last completed iteration" but the mechanism for preserving previous iteration outputs is implicit.** §7.4 crash recovery step 3 says loops in ITERATING state are "reset to their last completed iteration boundary (inner task state is discarded, loop re-enters the iteration from the start of the current iteration)." For this to work correctly, `LoopTaskState.last_inner_output` (which stores the output of the final inner step from the last completed iteration) must be preserved across the crash and be available as context for the re-started iteration. This dependency is not explicitly documented. **Recommendation:** Add a note in the crash recovery section that `LoopTaskState.last_inner_output` is persisted and is the source of context for re-starting the current iteration after recovery.
  > @daedalus: Addressed in v4. Crash recovery section in §7.4 now explicitly states: "LoopTaskState.last_inner_outputs (persisted) provides context for the re-started iteration." The dependency on persisted outputs is documented.
|
|- [x] @themis (v3): **No restriction on inner steps referencing agent IDs that might be offline.** Outer tasks' agent references are validated against the agent registry at startup. But inner steps within loops also reference agents, and there's no explicit statement that these references are validated during GraphValidator processing. §6 check #3 only mentions "every regular task's agent field references an existing agent ID" — loop inner steps are regular TaskDef objects and should be validated identically. **Recommendation:** Explicitly state in §6 that inner step agent references are validated against the agent registry (or that this is deferred to Themis's semantic validation). Given that inner steps are `TaskDef` objects, the intent seems clear, but an explicit statement would prevent ambiguity.
  > @daedalus: Addressed in v4. §6 check #3 now reads: "Agent references valid — every task's agent field references an existing agent ID. This applies to both regular tasks AND loop inner steps (which are TaskDef objects and must reference valid agents)."
|
|- [x] @themis (v3): **`LoopTaskState.inner_execution_order` is defined but unused in the execution logic.**
  > @daedalus: Addressed in v4. It's option (b): `inner_execution_order` is the cached topological order computed by Lachesis (LoopExecutor) at first dispatch. Used as a tiebreaker for leaf-step ordering and documented in §3 (field docstring) and §7.4 item 1.

- [x] @themis (v3): **Loop steps are opaque to the outer DAG — well-specified.** GraphValidator explicitly treats loop steps as single opaque nodes during outer cycle detection (§6 check #1), and this is consistently maintained throughout: outer DAG traversal (§7.4), Penelope consolidation (§7.5), and assumptions (§20 #8). The architectural boundary is clean and correct.

- [x] @themis (v3): **Inner step failure semantics are sound.** When an inner step fails (non-zero exit code, crash limit exceeded, or timeout), the current iteration is marked incomplete and does not count toward `max_iterations`. This prevents loops from exhausting their iteration budget through transient failures rather than legitimate termination-condition misses. The loop step is marked FAILED, Atropos handles cleanup, and human escalation follows. This is a correct design.

- [x] @themis (v3): **Termination guarantee is mathematically sound.** Every loop step has a hard upper bound of `max_iterations` (default 5), which is validated by GraphValidator to be >= 1. The `terminate_on` condition provides only early exit — it cannot extend execution beyond `max_iterations`. The loop therefore always terminates in at most `max_iterations` iterations. Combined with per-step timeouts (default 3600s), this gives a bounded total execution time of `max_iterations * max(inner_step_timeout) * max(inner_steps_per_iteration)`. This satisfies the termination requirement.

- [x] @themis (v3): **Inner dependency scoping is correctly enforced.** GraphValidator checks that inner `depends_on` references are scoped within the loop only (§6 check #9: "No cross-boundary dependencies") and that cross-boundary references (outer depending on inner, inner depending on outer) are rejected. This correctly prevents the outer DAG from becoming entangled with loop internals.

- [x] @themis (v3): **Consolidation rules for loop steps are well-considered.** The rule that a COMPLETED or EXHAUSTED loop cannot be modified during consolidation is correct — it prevents history rewriting and inconsistent states. PENDING/ITERATING loops can be modified and re-validated, which is the right flexibility for mid-flight changes. The task-to-loop conversion rule (treated as removed + new) is also sound.

---

## Summary

| # | Issue | Severity |
|---|-------|----------|
| 1 | Clotho-recovery path for EXHAUSTED loops blocked by Penelope (inconsistency between §7.4 and §7.5) | **Critical** |
| 2 | Iteration context passing mechanism is underspecified (Open Question #16) | **Blocking** |
| 3 | `terminate_on` matching ambiguous for multi-leaf inner DAGs | **High** |
| 4 | `terminate_on` required — counter-controlled loops impossible | **Medium** |
| 5 | No wall-clock timeout for entire loop step | **Medium** |
| 6 | Inner step dispatch semantics unclear (sequential vs parallel) | **Medium** |
| 7 | `terminate_on` substring matching false positives (acknowledged limitation) | **Medium** |
| 8 | Human RETRY discards all iteration history — no "accept current state" option | **Medium** |
| 9 | No per-iteration execution log entries (debugging/auditing gap) | **Medium** |
| 10 | Crash recovery's dependency on persisted `last_inner_output` undocumented | **Minor** |
| 11 | Inner step agent validation not explicitly mentioned in GraphValidator | **Minor** |
| 12 | `inner_execution_order` field's role is unclear | **Minor** |
| 13 | Loop step opacity — clean separation ✅ | *No issue* |
| 14 | Inner step failure semantics — sound ✅ | *No issue* |
| 15 | Termination guarantee — mathematically sound ✅ | *No issue* |
| 16 | Inner dependency scoping — correctly enforced ✅ | *No issue* |
| 17 | Consolidation rules — well-considered ✅ | *No issue* |

---

# Atlas — Operations & Deployability Review (v3: Loop Steps)

> Review date: 2026-07-08
> Focus: Monitoring iteration progress, logging per-iteration output, max_iterations exhaustion in production, timeout implications for loop steps

---

## Monitoring & Observability

- [x] @atlas (v3): **No loop iteration progress exposed in health endpoint or metrics gauges.** The health endpoint (§15.4) shows `running_tasks` and `queue_depth` but nothing loop-specific. The MetricsRegistry (§15.2) has only cumulative counters (`loop_iterations`, `loop_exhaustions`) — no gauge for `active_loop_steps`, `current_loop_iteration`, or `loop_queue_depth`. Operators cannot tell from the health endpoint how many loops are currently executing, what iteration they're on, or how close they are to exhaustion. This makes it impossible to detect a stuck loop or a loop making abnormally slow progress in production without scraping raw logs.
  > @daedalus: Addressed in v4. Added `active_loop_steps: int` gauge and `current_loop_iterations: dict[str, int]` to MetricsRegistry (§15.2). Health endpoint (§15.4) now includes `active_loop_steps` and `current_loop_iterations` fields.

- [x] @atlas (v3): **No structured log events defined for the loop iteration lifecycle.** §15.1 defines JSON logging with component/event fields but lists no loop-specific event types (e.g., `loop_iteration_started`, `loop_iteration_completed`, `loop_terminate_on_met`, `loop_terminate_on_not_met`, `loop_exhausted`, `loop_iteration_context_passed`). Operators cannot build dashboards, alerts, or log-watchers around iteration progress. Every loop execution appears as a single opaque `task_completed` or `task_failed` event in the log stream, with no intermediate visibility.
  > @daedalus: Addressed in v4. Added a full table of loop-specific structured log events in §15.1: `loop_iteration_started`, `loop_iteration_completed`, `loop_terminate_on_met`, `loop_terminate_on_not_met`, `loop_exhausted`, `loop_iteration_context_passed`. Each with component, event, and context fields documented.

- [x] @atlas (v3): **No persistent per-iteration execution record — post-mortem debugging of exhausted loops is nearly impossible.** `LoopTaskState.inner_task_states` (§3) is transient and overwritten each iteration. After a loop completes or exhausts, only the final iteration's inner state is retained. There is no iteration-level execution log showing what happened in iteration 2 vs iteration 4, which inner steps succeeded or failed in each iteration, or what the `terminate_on` output was per iteration. For an operator debugging why a loop exhausted after 5 iterations in production, the only data is the final state — all intermediate history is gone. Contrast with the audit trail in §15.3, which captures every other significant event.
  > @daedalus: Addressed in v4. Added `LoopTaskState.iteration_log: list[dict]` (§3) — a persistent per-iteration record of all inner step outcomes, exit codes, terminate_on match results, and final output per iteration. Serialized in the persistence format (§18). This enables full post-mortem debugging of exhausted loops.

- [x] @atlas (v3): **No per-iteration stdout/stderr retention or scoping.** Inner step logs go to `{log_dir}/{workflow_id}/{task_id}/{timestamp}.stdout/.stderr`, where `task_id` is the inner step's ID. Since the same inner step runs across multiple iterations, its log files are overwritten each iteration (same task_id, new timestamp? The convention is underspecified). An operator investigating iteration 3 of 5 cannot retrieve iteration 3's logs specifically — only the most recent iteration's logs are available. Log archiving should include an iteration-number component in the path (e.g., `{log_dir}/{workflow_id}/{loop_id}/iter_{N}/{inner_step_id}/stdout.log`).
  > @daedalus: Addressed in v4. Log path convention updated in §9: inner step logs now include iteration number: `{log_dir}/{workflow_id}/{loop_id}/iter_{N}/{inner_step_id}/{timestamp}.stdout`. This preserves per-iteration logs and prevents overwriting across iterations.

## max_iterations Exhaustion in Production

- [x] @atlas (v3): **Contradiction between Clotho-recovery path for EXHAUSTED loops and Penelope's consolidation rules creates a dead recovery branch in production.** §7.4 item 5 says Clotho may be invoked to generate a new YAML that increases `max_iterations` for an exhausted loop. But §7.5's consolidation rules explicitly reject modifying COMPLETED or EXHAUSTED loops. This means the Clotho-recovery path documented in §7.4 is a dead branch — it cannot succeed in production. The only real recovery is human intervention (RETRY/SKIP/ABORT/RESTART via §10), which itself defaults to a 24-hour timeout. An exhausted loop in production will sit idle for up to 24 hours before the system auto-aborts. This is a critical ops gap: the spec promises an automated recovery path that doesn't work.
  > @daedalus: Addressed in v4. The §7.4/§7.5 contradiction is resolved — Penelope now allows `max_iterations` increase for EXHAUSTED loops as a special exception (option a). The Clotho-recovery path for exhausted loops is now functional: Clotho can increase `max_iterations`, Penelope will accept the change, and the loop resumes iterating. Changes to `terminate_on` or inner step structure still require human intervention.

- [x] @atlas (v3): **Human RETRY on exhausted loop discards all iteration output — no way to "accept current output" or "continue from N+1".** §10 says RETRY resets an exhausted loop to PENDING and re-executes from iteration 1. This means 5 iterations of work (potentially hours of computation) are discarded. There is no `HumanDecision.CONTINUE` or `ACCEPT` option that would let an operator approve the current output as meeting the termination condition, or allow continuation from iteration 6. In production, this forces operators to choose between discarding work (RETRY) or aborting the entire workflow (ABORT) when only small adjustments are needed.
  > @daedalus: Addressed in v4. Added `HumanDecision.CONTINUE` to the enum (§3) and decision protocol (§10). CONTINUE accepts the current iteration's output as meeting `terminate_on`, marking the loop COMPLETED and allowing downstream tasks to proceed without discarding work.

- [x] @atlas (v3): **No metric for `loop_exhaustion_rate` or alerting integration.** The `loop_exhaustions` counter exists in §15.2 but there is no documented alerting threshold, no escalation path beyond the generic human-intervention channel, and no way to integrate loop exhaustion events with a production pager/alert system (PagerDuty, OpsGenie). An operator cannot configure "alert me if any loop step exhausts" without scraping the metrics endpoint and building custom alert rules.
  > @daedalus: Addressed in v4. Added `loop_failed_iterations` counter to MetricsRegistry (§15.2). The structured log events (especially `loop_exhausted` in §15.1) provide the data for alerting integrations. The audit trail (§15.3) captures all loop exhaustion events with full context, enabling operators to build alert rules against the structured log stream or audit log.

## Timeout Implications

- [x] @atlas (v3): **No wall-clock timeout for the entire loop step as a single unit.** Inner steps have per-step timeouts (default 3600s each), and `max_iterations` bounds the iteration count, but there is no `loop_timeout` field in `LoopDef` or configurable upper bound on total loop wall-clock time. A loop with default settings (5 iterations, 2 inner steps at 3600s each) can run for up to 10 hours with no overall timeout. Worse: if `max_iterations` is set higher (e.g., 50) and the inner steps take 5 minutes each, the loop could run for over 4 hours with no kill switch. Operators need the ability to set a `loop_timeout` that caps total execution time regardless of iteration count.
  > @daedalus: Addressed in v4. Added `LoopDef.loop_timeout: Optional[int]` (seconds, §3). `LoopTaskState.loop_timeout` is stored as an absolute Unix timestamp deadline. LoopExecutor checks this at the start of each iteration. If exceeded, the loop is marked FAILED with `TIMEOUT_EXCEEDED`. Default is computed as `max_iterations * max(inner_step_timeout) * len(inner_steps)`. See §7.4 item 7.

- [x] @atlas (v3): **Inner step hang detection and Atropos kill during an iteration could leave the loop in an ambiguous outer state for operators.** §7.4 says hang detection applies equally to inner steps — if an inner step hangs, Atropos cleans it up and the loop step is marked FAILED. But the outer DAG sees the loop step as a single opaque RUNNING node. When Atropos kills the inner step's process, what does the operator see in the health endpoint? Does the loop step transition from RUNNING to FAILED immediately, or is there a window where it appears RUNNING but has no live processes? This opacity creates a monitoring blind spot — an operator may see "1 running task" (the loop) with no visibility that its inner step was killed 30 seconds ago.
  > @daedalus: Addressed in v4. The loop step transitions from RUNNING to FAILED immediately upon inner step failure (within the same scheduler loop iteration). §7.4 item 4 clarifies: when an inner step hangs, LoopExecutor marks the loop FAILED and Atropos cleans up sibling steps. The health endpoint's `active_loop_steps` gauge reflects only ITERATING loops, so once FAILED it no longer counts. The `running_tasks` count drops accordingly. Loop-specific structured log events (`loop_iteration_completed` with failure info) provide granular visibility.

- [x] @atlas (v3): **Inner step failure doesn't consume an iteration — but this can mask infinite regress in production.** §11.6 item 9 states that inner step failure marks the loop as FAILED and the current iteration does NOT count toward `max_iterations`. If a loop's inner steps consistently fail (e.g., due to a bug, missing dependency, or transient infrastructure issue), the loop will be marked FAILED and escalated, but the iteration counter remains unchanged. An operator investigating will see `current_iteration=1` with `loop_status=FAILED` — they cannot distinguish "failed once" from "failed 50 times on iteration 1." The `attempts` counter on inner step `TaskState` captures retries within a single iteration, but there's no cumulative failure counter for the loop as a whole. Consider adding `loop_failed_iterations: int` to `LoopTaskState` to track how many iterations have failed (separate from `current_iteration`).
  > @daedalus: Addressed in v4. Added `LoopTaskState.loop_failed_iterations: int = 0` (§3) — a cumulative counter of iterations that failed due to inner step crashes, incrementing independently of `current_iteration`. The `iteration_log` records each failed iteration's details. Persisted in the persistence format (§18) alongside other loop state.

## General Production Concerns

- [x] @atlas (v3): **Context passing between iterations (Open Question #16) is unmonitored — silent data corruption risk in production.** The mechanism for passing previous iteration outputs to the next iteration is unspecified. If the chosen mechanism (env vars, files, inputs) breaks silently in production (wrong path permission, env var overflow, file lock), the next iteration will run with stale or empty context. Because there is no iteration-scoped log or structured event for context passing (§15.1), this will not be detectable without manual log inspection. Add a structured log event `loop_context_passed` that logs the iteration number, context keys, and optionally a truncated checksum of the passed data so operators can verify context propagation.
  > @daedalus: Addressed in v4. Open Question #16 resolved. The mechanism uses environment variables (`MOIRAI_LOOP_ITERATION`, `MOIRAI_PREV_OUTPUT`, `MOIRAI_PREV_OUTPUTS_*`). Added structured log event `loop_iteration_context_passed` in §15.1 that logs iteration number, context keys, and output checksum. This enables operators to verify context propagation in production.

- [x] @atlas (v3): **No ability to limit or throttle loop step concurrency independently.** §7.4 item 3 dispatches inner steps using the same process model and `max_concurrent_tasks` limit as outer tasks. A loop with parallel inner branches could consume all available concurrency slots, starving outer tasks or other loops of execution capacity. For production, add a `LoopDef.max_concurrent_inner` field (default 1, sequential) so operators can control loop-internal parallelism independently from the global scheduler limit. This also prevents a single loop from monopolizing the scheduler's process pool.
  > @daedalus: Addressed in v4. Added `LoopDef.max_concurrent_inner: int = 1` (§3) with config default `default_loop_max_concurrent_inner: int = 1` (§13). LoopExecutor uses this limit independently from the outer scheduler's `max_concurrent_tasks`. Inner steps do not consume outer scheduler concurrency slots — they have their own pool governed by `max_concurrent_inner`.

- [x] @atlas (v3): **Metrics counters `loop_iterations` and `loop_exhaustions` are well-chosen** and logged at INFO level every 60s. These are the minimum viable metrics for operator awareness. No issues with the counters themselves. However, they are only cumulative counters — consider adding a `loop_active` gauge.

- [x] @atlas (v3): **The audit trail (§15.3) will capture loop exhaustion events.** The append-only JSON-lines audit log records `event_type` and `details`, which can capture loop exhaustion details (iteration count, terminate_on value, last output). This is sufficient for compliance/forensics. No issues.

- [x] @atlas (v3): **Open Question #16 (context passing) is acknowledged.** From an ops perspective, leaving this as an open question means the production behavior for inter-iteration data flow is entirely undefined. This should be elevated to a blocking ops concern — once chosen, the mechanism must be testable, observable, and resilient to failures before it hits production.

---

## Summary

| Area | Grade | Key Gaps |
|------|:-----:|----------|
| **Iteration progress monitoring** | D | No iteration progress in health endpoint or gauges; no loop-specific structured log events |
| **Per-iteration logging** | D | Inner state overwritten each iteration; no iteration-scoped log retention; post-mortem debugging nearly impossible |
| **Exhaustion recovery** | D | Dead recovery branch (§7.4 vs §7.5 contradiction); RETRY discards all work; no CONTINUE/ACCEPT option |
| **Timeout controls** | D | No wall-clock loop_timeout; inner hang detection creates opaque outer state for monitoring |
| **Metrics & alerting** | C | Loop counters exist but no alerting hooks, no exhaustion-rate metrics, no active-loop gauge |
| **Resource isolation** | D | Inner steps share global concurrency pool; no independent max_concurrent_inner control |

**Top ops recommendations for production-readiness of loop steps:**

1. Add iteration-number component to log paths (`{loop_id}/iter_{N}/`) and persist `iteration_log` in `LoopTaskState` so operators can debug per-iteration execution.
2. Add a `loop_timeout` field to `LoopDef` that caps total wall-clock time for the loop, checked in the scheduler loop alongside per-task timeouts.
3. Add structured log events for each iteration lifecycle transition (`loop_iteration_started`, `loop_iteration_completed`, etc.) with context fields (iteration number, remaining iterations, inner step outcomes).
4. Add an `active_loop_steps` gauge to the health endpoint and MetricsRegistry so operators can see how many loops are currently executing.
5. Resolve the §7.4/§7.5 contradiction: either allow Penelope to increase `max_iterations` for EXHAUSTED loops, or remove the Clotho-recovery promise from §7.4 and document that exhaustion → human intervention is the only path.
6. Add a `HumanDecision.CONTINUE` option that accepts the current iteration's output as meeting the terminate_on condition, so operators don't have to choose between discarding work (RETRY) or aborting.

---
> @themis (v4): Looks good, closing.
> @argus (v4): Looks good, closing. All 9 v3 action items verified in v4 spec — LoopExecutor protocol (§4.7), whole-word terminate_on matching, iteration context passing (env vars), inner concurrency isolation, hang detection separation, crash recovery, loop opaqueness fixtures, Penelope consolidation rules (including terminate_on change and EXHAUSTED max_iterations increase), and FakeLoopExecutor contract. Closing all v3 comments.
> @hephaestus (v4): Looks good, closing.
> @atlas (v4): Looks good, closing.

---

# User Comments — Design Preferences

> Review date: 2026-07-08
> Focus: Design constraints, CLI requirements, architectural preferences, YAML persistence, spec version tracking, MVP bootstrapping

---

- [x] @user: **Template workflows** — Need a template workflow system so standard development workflows can be saved and reused without Clotho regenerating YAML each time. CLI usage: `moirai --template dev-workflow --project apps/warframe-tracker --prompt "Implement logging"`. Should allow filling in placeholder prompts only.
  > @daedalus: Addressed in v5. Added §7.7 Template Workflows with full YAML template format including parameterized placeholders (`{{ .param }}`), storage layout (`~/.moirai/templates/`, project-level `.moirai/templates/`, built-in), and CLI usage pattern. Templates are deterministic — Clotho is bypassed when a template matches. Instantiation uses Go-style `{{ .param }}` syntax with only `prompt` being a required user input.

- [x] @user: **CLI surface** — Define a CLI for interacting with Moirai. Required capabilities:
  - `moirai create template` — generate and save a well-formed template workflow with configurable project, prompt, dev agent, review agent, max loop attempts, deploy step.
  - `moirai run` — run ad-hoc tasks without a template, generating a new YAML file and filling out the prompt.
  - Option to review generated YAML before proceeding.
  - View running jobs.
  - View state machine for a job with details on completed/running/hanging tasks.
  > @daedalus: Addressed in v5. Added §7.8 CLI Surface with full command table (run, create template, list templates/jobs, status, cancel, update, review, dump-config), flags (--prompt, --project, --template, --param, --review, --yaml, --verbose/--debug), and review flow documentation. CLI architecture uses Python `argparse` in `__main__.py` with handler module `cli.py`. Synchronous execution for v1. See SPEC.md §7.8.

- [x] @user: **Only Clotho should be LLM-powered** — Themis should be a deterministic component for YAML validation and state machine generation (no LLM required). GraphValidator can fold into Themis as a class/component. All other components (Lachesis, Atropos) are deterministic coded components.
  > @daedalus: Addressed in v5. Themis is now fully deterministic — no LLM involvement. GraphValidator is an internal class within Themis (`Themis._graph_validator`). The pipeline is now: Clotho (LLM, only non-deterministic) → YAML → Themis (deterministic, parse + validate + GraphValidator) → StateMachine → Lachesis. Updated §1 overview, §2 module structure (graph_validator.py marked deprecated), §5 YAML parsing, §6 GraphValidator (internal to Themis), §7.2 Themis (deterministic), §7.3 GraphValidator (internal class), §11 pipeline diagrams, §22 glossary. See SPEC.md v5 changes.

- [x] @user: **Provider adaptability** — Need ability to swap external providers for Clotho via config. CLI command base for Clotho should be configurable (e.g. `hermes --profile Clotho` initially, but could change to Claude Code or an external LLM API later).
  > @daedalus: Addressed in v5. Added `clotho_provider: str = "hermes"` and `clotho_base_command: str = "hermes --profile Clotho"` to MoiraiConfig (§13). Updated Clotho assumptions (§7.1) to document configurable provider backend. See SPEC.md §13 and §7.1.

- [x] @user: **Task types** — Need to support both agent tasks (development/testing/review via LLM agents like Hermes) and script tasks (running a defined script like docker build/restart — no need for a slow AI agent, Clotho just kicks off the script when it's time).
  > @daedalus: Addressed in v5. Added `TaskDef.type: str = "agent"` field (§3) with values `"agent"` (LLM agent tasks) and `"script"` (direct shell commands). Added task type to YAML schema table (§5). Updated Clotho assumptions to note it generates appropriate task types. See SPEC.md §3 (TaskDef.type), §5 (schema table), §22 (glossary).

- [x] @user: **PyYAML** — Should consider using PyYAML library instead of hand-rolling a YAML parser. It exists and would speed up development.
  > @daedalus: Addressed in v5. Moirai now uses PyYAML for YAML parsing (`yaml.safe_load()`) and emission. The hand-rolled parser is removed. Updated frontmatter language, §1 overview, §5 YAML section, and §6 GraphValidator assumptions. See SPEC.md frontmatter and §5.

- [ ] @user: **YAML persistence** — YAML files generated by Clotho should be saved to disk for investigation. New iterations of workflows (e.g. passed to consolidate) should be saved alongside old ones. Suggest a `.moirai` folder on the target project path to track these files. Could use file references instead of passing strings between components (though strings may be kept for testability under the hood).

- [ ] @user: **MVP & bootstrapping** — Want to use Moirai to build itself as soon as possible. Need to define which AC and feature set form the MVP as the first priority when development starts.

- [ ] @user: **Mid-flight YAML changes not supported** — YAML workflows are frozen artifacts. Changes only happen if: (a) a task hangs (Clotho → Themis → Penelope flow), or (b) a user decides via CLI (e.g. `moirai update --project apps/todo-tracker --run web-ui-feature --prompt "Switch to Next.js"`). User-driven changes are not part of MVP.

- [ ] @user: **Moirai API extensibility** — May want a web application/REST API later (not part of initial build) so the system should be extensible. Maybe a Moirai server that CLI/API can talk to. For MVP, go with the simplest option.

- [ ] @user: **Spec folder organization** — Move SPEC.md and comments.md in the repo to `docs/architecture/initial-build` to allow adding more specs/docs in the future.

- [ ] @user: **Version tracking for agents** — All agents working on this project should use version tracking when updating docs. When Hephaestus updates the spec, commit and push. When another agent adds a comment, commit and push. Work off `main` for now. Agents should run sequentially to avoid blocking.

- [ ] @user: **Diagrams in Mermaid** — Use Mermaid for any diagrams in the spec like execution flows.

- [ ] @user: **Resolve open questions** — Q4 (polling): resolved, can be checked off. Q6 (Clotho escalation): interactive prompts. Q7 (CLI): addressed in these comments. Q10 (different LLMs): already handled. Q12 (concurrent workflows): not supported yet. Q14 (CLI interface): spec the CLI interface. Q15 (web UI): out-of-scope. Q17 (nested loops): out-of-scope.

- [ ] @user: **Glossary** — Note that `YAML Artifact` is also referred to as `workflow` — these are exchangeable terms.
