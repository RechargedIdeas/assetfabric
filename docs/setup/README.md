# Setup

## Requirements

| Tool | Version | Required for |
|---|---|---|
| Python | ≥ 3.11 | `forge`, tests |
| uv | recent | venv + install (`pip` works too) |
| git | any | — |
| Godot | 4.3+ (standard, not .NET) | headless boot, editor (optional for structure tests) |
| PySide6 | ≥ 6.6 | Studio GUI only (`pip install -e ".[studio]"`), not needed for F0 |

No GPU is required. Acceptance hardware is **2 cores, no GPU** (see `docs/hardware-fleet.md`).

## Steps

```bash
git clone https://github.com/RechargedIdeas/assetfabric.git && cd assetfabric
./scripts/bootstrap.sh            # uv venv .venv && uv pip install -e ".[dev]"
source .venv/bin/activate
forge doctor && forge status
pytest -q
./scripts/smoke_godot.sh
```

Without `uv`: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`.

## Godot

The smoke script looks for Godot in this order: `$GODOT_BIN`, `godot` / `godot4` on `PATH`, then `./godot-bin/godot` (gitignored local download). To fetch the official Linux binary into `godot-bin/`:

```bash
mkdir -p godot-bin && cd godot-bin
curl -LO https://github.com/godotengine/godot/releases/download/4.3-stable/Godot_v4.3-stable_linux.x86_64.zip
unzip Godot_v4.3-stable_linux.x86_64.zip && mv Godot_v4.3-stable_linux.x86_64 godot && rm *.zip
```

Windows/macOS: install Godot 4.3 and set `GODOT_BIN`. `REQUIRE_GODOT=1 ./scripts/smoke_godot.sh` fails if no binary is found.

## Local data (never committed)

`.venv/`, `godot-bin/`, `.fabric/` (jobs DB, telemetry), `store/objects/**`, `store/manifests/**`, `store/index.sqlite`, Godot `.godot/` cache, `.env*`, keystores.
