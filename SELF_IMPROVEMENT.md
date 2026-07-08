# Moirai Self-Improvement Cycle

Moirai uses **recursive self-improvement**: high-level features are tracked as GitHub Issues in a backlog, and Moirai executes workflows to implement them autonomously. The goal is for Moirai to build itself — each cycle extends its own capabilities.

## Cycle Architecture

```
GitHub Issues (Backlog) 
    │
    ▼
Moirai picks up feature from backlog
    │
    ▼
User + Clotho generate YAML workflow       # Currently user provides YAML (Clotho stub)
    │
    ▼
Themis validates workflow                   # Deterministic YAML → StateMachine
    │
    ▼
Lachesis dispatches tasks:                  # Dev-review-fix loop
  ├── claude-dev → implements the feature
  ├── Themis → reviews the changes
  └── LoopExecutor → manages iterations
    │
    ▼
Moirai commits + pushes changes             # Feature is now in the codebase
    │
    ▼
Penelope consolidates state                 # Transition to next feature
    │
    ▼
Next feature from backlog starts
```

## The Bootstrap Build

The first cycle focuses on getting Moirai to the point where it can build itself. Until Clotho is implemented, you provide the YAML manually:

1. Pick an issue from the backlog
2. Write the YAML workflow (or use a template)
3. `moirai run --template dev-workflow --yaml workflow.yaml`
4. Moirai executes: implements the feature, tests it, reviews it, commits it
5. After commit, Moirai can be triggered to pull the next issue and repeat

## Implementation Phases

The backlog is organized into phases. Each phase is a self-improvement step — Moirai implements one phase, then uses its new capabilities to implement the next.

| Phase | What Moirai Gains | Self-Improvement Value |
|:-----:|-------------------|----------------------|
| 0 | Project skeleton, data structures | Foundation — nothing works without this |
| 1 | Themis + GraphValidator | Can validate its own YAML workflows |
| 2 | MemoryBackend | Can track its own state in-memory |
| 3 | Lachesis + ProcessManager | Can actually execute tasks |
| 4 | Atropos | Can clean up after itself |
| 5 | LoopExecutor | Can run dev-review-fix cycles |
| 6 | CLI + Templates | You can trigger self-improvement runs |
| 7 | Penelope | (Deferred) Can handle mid-flight changes |
| 8 | Clotho | (Deferred) Can write its own YAML — true autonomy |

## After Bootstrap

Once all phases are complete, the cycle becomes fully autonomous:
1. Moirai picks up the next GitHub Issue from the backlog
2. Clotho generates a YAML workflow from the issue description
3. Themis validates it
4. Lachesis dispatches agent tasks to implement the feature
5. LoopExecutor runs review cycles until APPROVED
6. Each agent commits with its own git identity — see `CONTRIBUTING.md`'s authorship table
7. Moirai moves the issue on the project board *(requires Issue #10)*
8. Loop — pick the next issue

## GitHub Project Board

### Creating the Project Board

Your GitHub token doesn't have `project` scope, so the board needs to be created via the web UI. One-time setup:

1. Go to **https://github.com/NamalD/moirai**
2. Click the **Projects** tab
3. Click **"Link a project"** → **"Create new project"**
4. Choose **"Board"** layout
5. Name it **"Moirai Backlog"**
6. Add columns: **Backlog** → **In Progress** → **Done**
7. Click **"Add item"** and paste each issue URL:
   - `https://github.com/NamalD/moirai/issues/1` (Phase 0)
   - `https://github.com/NamalD/moirai/issues/3` (Phase 1)
   - `https://github.com/NamalD/moirai/issues/2` (Phase 2)
   - `https://github.com/NamalD/moirai/issues/4` (Phase 3)
   - `https://github.com/NamalD/moirai/issues/5` (Phase 4)
   - `https://github.com/NamalD/moirai/issues/6` (Phase 5)
   - `https://github.com/NamalD/moirai/issues/7` (Phase 6)
   - `https://github.com/NamalD/moirai/issues/8` (Phase 7 — deferred)
   - `https://github.com/NamalD/moirai/issues/9` (Phase 8 — deferred)
8. Move Phase 0 to **In Progress** (it's the current focus)

### Labels

Issues are tagged with:
- `phase:N-name` — Which implementation phase
- `status:backlog` / `status:in-progress` / `status:done` — Current status
- `self-improvement` — Feature that Moirai will implement via self-improvement
- `blocked` — Blocked by another issue

### Workflow

1. Phase N gets tagged `status:in-progress`
2. You build Phase N (either manually or via Moirai's workflow)
3. When done, tag it `status:done`
4. Move Phase N+1 to `status:in-progress`
5. Repeat
