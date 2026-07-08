# Contributing to Moirai

## Prerequisites

Before you can build or run Moirai, you'll need:

- **Python 3.11+** — the runtime
- **[uv](https://docs.astral.sh/uv/)** — Python package manager and project tool (v0.4+)

`uv` handles dependency resolution, virtual environment management, and task running. It replaces both `pip`/`pip-tools` and `poetry`. Install it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Or via pip: pip install uv
# Or via brew: brew install uv
```

## Setup

```bash
git clone https://github.com/NamalD/moirai.git
cd moirai
uv sync          # Creates venv and installs all dependencies
```

## Dependency Management

Moirai uses `uv` in project mode with a `pyproject.toml`. To add a dependency:

```bash
uv add <package>
```

This updates both `pyproject.toml` and `uv.lock`. Commit both files.

Key dependencies:
- **PyYAML** — YAML parsing and emission (used by Themis and Clotho's output pipeline)
- Everything else is Python stdlib

## Running

```bash
uv run moirai --help                  # CLI help
uv run moirai run --prompt "..."      # Run a workflow
uv run python -m pytest tests/        # Run tests (when test suite exists)
```

## Version Tracking Convention

All agents working on this project follow these rules:

1. **Every document change is committed and pushed individually.** Spec update → commit + push. Comment added → commit + push.
2. **Work off `main` branch.** No feature branches for doc changes.
3. **Agents run sequentially.** This avoids merge conflicts and ensures each agent works off the latest state.
4. **Descriptive commit messages.** Each commit references what changed and why (e.g. "v5: Add template workflows (§7.7)").

## File Layout

```
moirai/
├── docs/architecture/initial-build/   # SPEC.md and comments.md
├── clotho.py                          # LLM-powered YAML generation
├── themis.py                          # Deterministic validation + GraphValidator
├── lachesis.py                        # Deterministic scheduler
├── penelope.py                        # Deterministic consolidation
├── atropos.py                         # Process cleanup
├── loop_executor.py                   # Loop iteration management
├── types.py                           # Shared data structures
├── protocols.py                       # Interface protocols
├── config.py                          # Configuration loading/validation
├── templates.py                       # Template workflow system
└── cli.py                             # CLI command handlers
```

## Bootstrapping Goal

The first real Moirai workflow should be a dev-review loop that builds Moirai itself. The `dev-workflow` template (§7.7 of the spec) defines this: Clotho generates YAML from a prompt, Themis validates, Lachesis dispatches tasks to Hephaestus (dev) and Themis (review) in a loop.

See [`docs/architecture/initial-build/SPEC.md`](docs/architecture/initial-build/SPEC.md) for the full specification.
