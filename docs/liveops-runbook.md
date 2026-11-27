# LiveOps runbook — Game Zero (F9, readiness only)

**Status:** readiness only (ASSETFABRIC_SPEC §13 F9). There is **no live service, no delivery endpoint and no launch**.
Everything below runs on a workstation against local files. Spec basis: §12 "LiveOps readiness: remote config / feature
flags (launch content deferred)", GAME_SPEC §5 "Live seasonal content (remote config readiness OK)", §8 "Remote config
hooks for balance knobs", G-NET-01 "Solo offline launch with networking stack dormant". Inferences: `docs/INFERENCES.md` §F9.

What a config bundle can do: switch **kill switches** off/on and set **balance knobs** (the numeric leaves and ranges of
`content/tune/limits.yaml`, minus `sim.*`). What it can never do: add or change content (areas, quests, items, art,
seasonal events), set a **consent** flag, run code, or make the game talk to a network.

## Key ceremony

1. The Producer generates the production keypair on an offline machine: `forge liveops keygen --out <offline dir> --name prod`.
   RSA-2048, PKCS#1 v1.5 / SHA-256 (what Godot 4.3 `Crypto.verify` supports — INFERENCES F9-2).
2. The **public** key is pinned at `games/game-zero/data/liveops/pubkey.pem`; add `data/liveops/*` to every preset's
   `include_filter` in `games/game-zero/export_presets.cfg` (the `*.pem` gitignore rule needs a `!` exception for that
   one file). Until then every build ignores every bundle (`forge liveops readiness` lists it as `user_gated`).
3. The **private** key never enters git, CI or the box; `forge liveops readiness` fails if any PEM/private key is tracked.
   Dev/QA keys live in `.fabric/liveops/` (gitignored). Release builds trust only the pinned key; `--liveops-pubkey=`
   works in debug builds only.
4. Key rotation = a new build with the new pinned key (bundles carry `key_id`; a mismatch is refused).

## Issue a bundle

```bash
forge liveops bundle --serial 7 --flag adaptive_music=off --set enemies.emberling.stats.hp=26 \
    --build-min 0.9.0 --channel qa --key .fabric/liveops/dev.key.pem --out bundles/7.json
```

* `serial` must be strictly greater than any serial a device has seen (anti-replay / anti-downgrade).
* `build_min` / `build_max` bound the game builds that may apply it.
* forge validates before signing (same rules as the game) and refuses unknown keys/flags/knobs, out-of-range values,
  `sim.*` knobs and consent flags.

## Verify

`forge liveops verify bundles/7.json --pub <pinned pub.pem> [--min-serial N]` — signature, key id, payload rules,
build range. CI-style proof: `forge accept F9` (forge and the game make the same decision for every case).

## Deliver

Readiness only: a bundle reaches a device **inside a platform update** (store patch / installer) or, for dev/QA, via
`forge liveops install bundles/7.json --dir <device liveops dir>` (writes `inbox.json`). The game never downloads
anything. Device dir: `user://liveops` (desktop: Godot's user data dir; Android: app-private storage; Web: IndexedDB).

## Rollback

Devices never accept an older serial, so rollback is **roll-forward**:
`forge liveops rollback --to bundles/5.json --serial 8 --key …` re-signs bundle 5's content as serial 8;
`--to defaults` issues an empty bundle (= shipped behaviour). `forge accept F9` proves the rollback restores the exact
baseline F2 combat state hash.

## Crash-loop quarantine

On every boot that applies a bundle the game writes `boot.json`; a clean exit removes it. If the game boots
`max_boot_fails` (2) times with the same bundle and dies each time, the next boot moves the bundle to `quarantine/`
and restores `previous.json` (the last good bundle). Inspect with `forge liveops status --dir <device dir>`.

## Kill switch

Kill switches (`content/liveops/flags.yaml`, kind `kill_switch`) default **on**; a bundle can turn one off:
`retro_styles` (F8 display styles → modern), `adaptive_music` (exploration mix only), `remote_balance` (ignore the
bundle's balance patches). Each flag names the code it gates. New flags: add to `flags.yaml` + locale keys, `forge build`.

## Diagnostics

Consent flag `diagnostics` defaults **off** and is the player's decision (`consent.json`, never a bundle). With consent
the game keeps a local session record (`diag/session.json`: build, platform, LiveOps state, whether the previous boot
crashed — no paths or ids). `forge liveops diag-export --consent FILES… --out diag.json` scrubs home paths, user/host
names, e-mails, IPs, MACs and long tokens and validates `forge/schemas/diag_bundle.schema.json`. Nothing is uploaded.
Since 0.9.1 the player sets consent in the in-game Settings screen ("Diagnostics (kept on this device)", default Off; turning it off deletes the local record; mirrored into the save profile — INFERENCES F9-12). The privacy text is a placeholder marked `[PLACEHOLDER — LEGAL REVIEW REQUIRED]` until legal review (`forge liveops readiness` → `privacy_text_legal_review: user_gated`).

## Save compatibility

Config bundles never touch saves (balance patches live in memory). Saves migrate forward v1→v4 (F5/F6). A save written
by a **newer** build is read-only on an older build: not migrated down, not replaced by its `.bak`, never overwritten
(`save.gd` `newer_than_build`, `forge/save.py` `classify`). Rolling a device back to an older build cannot destroy progress.

## Readiness checklist

`forge liveops readiness` — manifest valid + locale keys, game manifest in sync, no network API in game scripts, no
signing key in git, key dir gitignored, runbook complete, save forward-compat guard, privacy defaults. `user_gated`:
production public key (Producer key ceremony) and the live service itself (out of scope for F9).
