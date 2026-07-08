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

There's a bootstrapping paradox: RSI means Moirai *dispatching* tasks to build itself, but dispatch requires Themis + Lachesis + ProcessManager + Atropos to already exist. Those can't be built by a system that doesn't exist yet — so Phases 0-4 are built the normal way (you + Claude Code directly), with no Moirai scheduler involved at all. RSI proper doesn't start until that foundation is in place.

### RSI Kickoff Criteria

**Manual pre-RSI phases (0-4):** Project skeleton, Themis + GraphValidator, MemoryBackend, Lachesis + ProcessManager, and Atropos are built by hand, not dispatched. This is the minimum needed for Moirai to dispatch and safely clean up after a single task — LoopExecutor (5) and CLI + Templates (6) come later, *as RSI-dispatched work*, once this foundation exists.

**Test bar before kickoff:** Each of Phases 0-4 needs a passing unit/integration test suite (per `SPEC.md §19`) before the first live dispatch — not just a manual smoke test. In particular, Atropos's kill path and Lachesis's dispatch/poll loop are the only safety net for an unattended, `bypassPermissions` agent; the first live run doesn't get a human checkpoint (see below), so this code needs to have been exercised before it's trusted with the real repo.

**Kickoff moment:** RSI kicks off at the first live dispatch, *not* the first `moirai run --template` invocation — the CLI and template system (Phase 6) don't exist yet at this point. The first dispatch is invoked by a throwaway script (not part of the shipped `moirai/` package) that calls `Themis.parse()` on a hand-written, single-task YAML file (no `loop` step — `LoopExecutor` doesn't exist yet either) and hands the resulting `StateMachine` to `Lachesis` directly.

**First task:** The first RSI-dispatched task builds Phase 5 (`LoopExecutor`), run by `claude-dev` with full `--permission-mode bypassPermissions` autonomy — including committing **and pushing straight to `main`**, identical to every subsequent run. There is no special human gate on this first run: if the Phase 0-4 test bar above is met, the first run is trusted the same as any later one.

Once Phase 5 lands, the `dev-workflow` template's `review-loop` step becomes usable, so Phase 6 (CLI + Templates) can itself be built via a real dev-review-fix RSI cycle rather than a throwaway script.

## Implementation Phases

The backlog is organized into phases. Each phase is a self-improvement step — Moirai implements one phase, then uses its new capabilities to implement the next.

| Phase | What Moirai Gains | Self-Improvement Value | Built by |
|:-----:|-------------------|----------------------|----------|
| 0 | Project skeleton, data structures | Foundation — nothing works without this | Manual (pre-RSI) |
| 1 | Themis + GraphValidator | Can validate its own YAML workflows | Manual (pre-RSI) |
| 2 | MemoryBackend | Can track its own state in-memory | Manual (pre-RSI) |
| 3 | Lachesis + ProcessManager | Can actually execute tasks | Manual (pre-RSI) |
| 4 | Atropos | Can clean up after itself | Manual (pre-RSI) |
| 5 | LoopExecutor | Can run dev-review-fix cycles | **RSI** — first live dispatch |
| 6 | CLI + Templates | You can trigger self-improvement runs | RSI |
| 7 | Penelope | (Deferred) Can handle mid-flight changes | RSI |
| 8 | Clotho | (Deferred) Can write its own YAML — true autonomy | RSI |

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
