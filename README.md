# Moirai — Deterministic Agent Task Graph Scheduler

Moirai orchestrates multi-step agent workflows — from a natural-language prompt to a validated state machine to deterministic task execution.

**Named after the Moirai** (the three Fates of Greek mythology): Clotho spins the YAML, Lachesis measures execution, Atropos cuts hanging tasks.

## Quick Start

```bash
# Prerequisites: Python 3.11+, uv
uv sync
uv run moirai run --prompt "Implement logging in my project"
```

## Project State

The spec is **v5 complete** — all 15 user design comments have been addressed and checked off. See [`docs/architecture/initial-build/SPEC.md`](docs/architecture/initial-build/SPEC.md) for the full specification and [`docs/architecture/initial-build/comments.md`](docs/architecture/initial-build/comments.md) for the review history.

## Prerequisites

| Tool | Version | Required For |
|------|---------|-------------|
| Python | 3.11+ | Runtime |
| [uv](https://docs.astral.sh/uv/) | 0.4+ | Dependency management, project sync, task runner |

## Setup

```bash
# Clone and enter the repo
git clone https://github.com/NamalD/moirai.git
cd moirai

# Sync dependencies (reads pyproject.toml)
uv sync

# Run the CLI
uv run moirai --help
```

## Architecture

Only one component is LLM-powered:
- **Clotho** — generates YAML workflow artifacts from natural language prompts

Everything else is deterministic Python:
- **Themis** (incl. GraphValidator) — validates YAML, generates state machines
- **Lachesis** — DAG scheduler executing tasks in dependency order
- **Penelope** — consolidates old vs new state machines during mid-flight changes
- **Atropos** — cleans up hanging tasks via process-group kill
- **LoopExecutor** — manages dev-review-fix loop iteration lifecycle

## Development

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for contribution guidelines, version tracking conventions, and the bootstrapping workflow.

## Self-Improvement

Moirai is designed to build itself. See [`SELF_IMPROVEMENT.md`](SELF_IMPROVEMENT.md) for the recursive self-improvement cycle, GitHub Issues backlog, and how features flow from the project board into autonomous implementation workflows.
