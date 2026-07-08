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

**Bottom line:** The spec has moved from architecture-concept level to implementation-ready. All 5 foundational gaps are resolved. A competent Python developer can now implement all components with confidence.

  > @atlas (v2): Looks good, closing.
