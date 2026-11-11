# CLAUDE.md

## Agent tree (cost-efficient delegation)

The main session is the **root / orchestrator** (Fable 5.2, medium effort — set in
`.claude/settings.json`). It plans, delegates on demand, then integrates and verifies
the results itself.

```text
root / orchestrator  (Fable 5.2 · medium)
        │  delegate on demand
        ├── explorer     Haiku 5.5          finds files
        ├── worker       Opus 5.5 · medium  edits code
        └── tester       Haiku 5.5          runs tests
        │
root integrates + verifies  (Fable 5.2 · medium)
        ┆  only if it's stuck
        └── deep-solver  Fable 5.2 · high
```

The subagents are defined in `.claude/agents/`:

| Agent | Model | Use it for |
| --- | --- | --- |
| `explorer` | Haiku 5.5 | Locating files, symbols and usages; read-only. Returns paths and line numbers, not file dumps. |
| `worker` | Opus 5.5 (medium) | Implementing a well-scoped code change from a precise brief. |
| `tester` | Haiku 5.5 | Running tests / scripts / checks and reporting pass or fail with the relevant output. Does not edit code. |
| `deep-solver` | Fable 5.2 (high) | Escalation only — when the root has already tried and is stuck. |

### Rules

- **Split useful work. Don't spawn every role.** Delegate only when it saves cost or
  context; do small or single-file tasks directly in the root session.
- Skip `explorer` when the location is already known; skip `worker` for trivial edits;
  skip `tester` when one quick command is enough.
- Give each subagent a self-contained brief: goal, relevant paths, constraints, and
  what "done" looks like. They start without the conversation's context.
- Run independent subagents in parallel; run dependent ones in sequence
  (explorer → worker → tester).
- The root always integrates and verifies: read the diff and the tester's output
  before reporting success. Never relay a subagent's claim unchecked.
- Spawn `deep-solver` only after a real attempt has failed (e.g. the same fix failed
  twice, or the root cause is still unclear). Include what was tried and why it failed.
