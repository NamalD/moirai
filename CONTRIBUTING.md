# Contributing to Moirai

## Prerequisites

Before you can build or run Moirai, you'll need:

- **Python 3.11+** — the runtime
- **[uv](https://docs.astral.sh/uv/)** — Python package manager and project tool (v0.4+)
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)** — autonomous AI coding agent used for implementation tasks (v2.1+)

`uv` handles dependency resolution, virtual environment management, and task running. `Claude Code` (`claude --print`) is used by Moirai's dev workflow template for implementation tasks.

Install Claude Code:
```bash
npm install -g @anthropic-ai/claude-code
# Or via the installer: curl -sS https://raw.githubusercontent.com/anthropics/claude-code/main/install.sh | sh
```

`uv` handles dependency resolution, virtual environment management, and task running. Install it:

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
3. **Agents run sequentially.** Avoids merge conflicts and ensures each agent works off the latest state.
4. **Agent git authorship (baked into profiles).** Each Hermes profile sets its own git author automatically via `terminal.shell_init_files`. Agents do not need to remember to set these manually:

   | Profile | Git Author |
   |---------|-----------|
   | `daedalus` / `default` | NamalD <namald@users.noreply.github.com> |
   | `hephaestus` | Claude Code <claude-code@namald.users.noreply.github.com> |
   | `themis` | Themis <themis@namald.users.noreply.github.com> |
   | `argus` | Argus <argus@namald.users.noreply.github.com> |
   | `atlas` | Atlas <atlas@namald.users.noreply.github.com> |

   Scripts live at `~/.hermes/scripts/set-git-author-*.sh` and are referenced in each profile's `terminal.shell_init_files` in their `config.yaml`.
5. **Structured commit messages.** Every commit references the issue number and includes a `[Phase N]` tag:
   ```
   [Phase 1] Implement YAML schema validation in Themis (#3)

   - PyYAML safe_load with structured error handling
   - Schema conformance checks per SPEC.md §5
   - Agent cross-reference validation
   - All GraphValidator structural checks integrated
   ```

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
