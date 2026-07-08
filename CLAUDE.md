# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Moirai is **pre-implementation**. Only `pyproject.toml` and design docs exist — there is no `moirai/` package, no CLI, and no tests yet. The spec (v5) is complete and frozen; the current work is building the MVP against it phase by phase (see `docs/architecture/initial-build/SPEC.md` §23).

Before writing code, check `SPEC.md` §23 "Implementation Order (MVP)" and `SELF_IMPROVEMENT.md`'s phase table to see which phase is current, and check git log / open issues rather than assuming — this file will not be kept in sync with that fast-moving state.

## Commands

```bash
uv sync                          # install deps into the venv
uv run moirai --help             # CLI (once __main__.py/cli.py exist)
uv run moirai run --prompt "..." # run an ad-hoc workflow
uv run python -m pytest tests/   # run tests (once a test suite exists)
uv add <package>                 # add a dependency — updates pyproject.toml + uv.lock, commit both
```

There is no separate lint/typecheck command configured yet; check `pyproject.toml` before assuming one exists.

## Architecture (target design per SPEC.md)

Moirai turns a natural-language prompt into a validated, deterministically-executed task DAG. Named after the three Fates: Clotho spins the YAML, Lachesis measures out execution, Atropos cuts hanging tasks.

Pipeline: `User Prompt → Clotho (LLM) → YAML → Themis (parse + validate + GraphValidator) → StateMachine → Lachesis (execute)`, with Penelope and Atropos handling mid-flight changes and failures.

**Only Clotho is non-deterministic** — every other component is pure/deterministic Python, which is the core design invariant of the system (isolate LLM unpredictability to one component).

- **Clotho** (`clotho.py`) — LLM-powered; generates YAML workflow artifacts from prompts. Stubbed in the MVP (returns a placeholder); it's the first thing Moirai is meant to build for itself.
- **Themis** (`themis.py`) — deterministic. Parses YAML (PyYAML `safe_load`), does schema/agent/command/param validation, and internally runs **GraphValidator** (DAG acyclicity via DFS, topological sort, orphan/self-loop/entry-point detection, loop-step opaqueness) to produce a `StateMachine`. GraphValidator is *not* a separate component/file — it's folded in as `Themis._graph_validator`.
- **Lachesis** (`lachesis.py`) — the scheduler. Non-blocking poll loop: dispatch ready tasks up to `max_concurrent_tasks` via `ProcessManager`, poll running tasks for completion, run periodic hang checks, handle SIGTERM for graceful shutdown, support cancellation. Delegates loop-step (dev-review-fix cycle) execution to **LoopExecutor** — loop steps are opaque single nodes to the outer DAG.
- **LoopExecutor** (`loop_executor.py`) — manages loop-step iteration: dispatches inner steps, checks `terminate_on` against leaf-step outputs (whole-word match), passes context between iterations via env vars (`MOIRAI_LOOP_ITERATION`, `MOIRAI_PREV_OUTPUT`, `MOIRAI_PREV_OUTPUTS_<STEP_ID>`), and escalates on `max_iterations` exhaustion.
- **Penelope** (`penelope.py`) — consolidates old vs. new `StateMachine` when YAML changes mid-flight (e.g. after a hang). Two-phase: compute a `ConsolidationPlan` and validate it entirely in memory first, then apply atomically. A completed task can never be silently erased — that always fails consolidation.
- **Atropos** (`atropos.py`) — kills hanging tasks by `SIGTERM` then `SIGKILL` to the whole process group (`os.killpg`, never just the parent PID), archives logs, and raises human intervention.
- **Templates** (`templates.py`) — parameterized YAML workflows (e.g. `dev-workflow`) so common flows don't need Clotho regeneration each run. This is the primary way workflows get run in the MVP, since Clotho is stubbed.

Shared foundations everything else depends on: `types.py` (dataclasses/enums — `TaskDef`, `StateMachine`, `ExecutionState`, `LoopTaskState`, etc.) and `protocols.py` (`LLMClient`, `PersistenceBackend`, `ProcessManager`, `HumanNotifier`, `TimeProvider`, `TaskInvestigator`, `LoopExecutor` protocols) — all component boundaries are Protocol interfaces so fakes can be swapped in for tests.

Persistence for the MVP is in-memory only (`MemoryBackend`); file-based persistence is post-MVP (§18).

Full detail — data structures, YAML schema, per-component I/O contracts, error handling, config, observability — lives in `docs/architecture/initial-build/SPEC.md`. Treat it as authoritative over this summary; skim its section headers (`grep '^##' docs/architecture/initial-build/SPEC.md`) rather than assuming this file captured everything.

## Development conventions

These apply to every agent (human or AI) committing to this repo — see `CONTRIBUTING.md` and SPEC.md §24 for the full versions:

- Commit and push **every** doc or code change individually — don't batch unrelated changes into one commit.
- Work directly off `main`; no feature branches for doc changes, agents work sequentially to avoid merge conflicts.
- Each agent sets its own git identity before committing. `CONTRIBUTING.md`'s agent git authorship table is the single source of truth for which identity maps to which agent/profile — check there rather than assuming.
- Commit messages reference the GitHub issue and a `[Phase N]` tag, e.g. `[Phase 1] Implement YAML schema validation in Themis (#3)`.
- Spec is at `docs/architecture/initial-build/SPEC.md`; its review history is `docs/architecture/initial-build/comments.md`. Future architecture docs go under `docs/architecture/<topic>/`. Implementation code lives at repo root (`moirai/`, `tests/`).
- Self-improvement loop context (GitHub Issues backlog, phase tracking, project board) is in `SELF_IMPROVEMENT.md`.
