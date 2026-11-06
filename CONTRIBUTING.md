# CONTRIBUTING.md

Humans and agents follow the same rules (`AGENTS.md`).

## Setup

```bash
git clone <repo>   # or use /workspace/assetfabric on the shared box
cd assetfabric
./scripts/bootstrap.sh
source .venv/bin/activate
forge doctor && forge status
pytest
```

Godot 4.3+ recommended for editor / headless smoke. Structure tests run without it.

## PR checklist

- [ ] Task is in current milestone (`TODO.md`) — **no F1 code during F0**
- [ ] Acceptance test added/updated
- [ ] `forge status` healthy
- [ ] Docs / HANDOVER / TODO updated in same commit if state changed
- [ ] No hard-coded user strings or absolute host paths
- [ ] No Out-of-Scope features
- [ ] `[INFERENCE]` marked where inventing beyond chatgrab

## Team roles `[INFERENCE: names TBD]`

Producer (scope), Factory Lead (architecture), Game Design, Eng, ML, QA, TA — fill names when staffed.
