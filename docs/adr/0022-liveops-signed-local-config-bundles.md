# ADR-0022 — LiveOps readiness = signed, local-only config bundles (flags + balance knobs), never content, never network

| Field | Value |
|---|---|
| Status | **accepted** (F9, `0.9.0+f9`) |
| Date | 2026-11-27 |
| Deciders | Recharged Ideas (Producer direction t59u "then do F8 and F9"; F9 readiness only); agent implementation |

## Context

SPEC §13 F9 is "LiveOps foundation — readiness only"; §12 asks for "remote config / feature flags (launch content
deferred)"; GAME_SPEC §5 puts live seasonal content out of scope ("remote config readiness OK") and §8 asks for "remote
config hooks for balance knobs". G-NET-01 requires a solo offline launch with the networking stack dormant, and Game
Zero v1 has no server (dedicated servers and cloud saves are deferred). F4 already has a validated, range-limited
numeric overlay for game data (live tune, ADR-0012 store + atomic reload).

## Decision

1. **Unit of change = a signed config bundle**: kill-switch flags + numeric balance patches. The knob table *is* the F4
   live-tune table (`content/tune/limits.yaml`, minus `sim.*`); the game validates with the same LiveChannel code.
   Bundles may not carry content, code, or consent flags — any unknown key is refused.
2. **Authenticity**: RSA-2048 PKCS#1 v1.5 / SHA-256 over the exact payload bytes, public key pinned in the build
   (`data/liveops/pubkey.pem`); test keys only via a debug-build argument. Godot 4.3's built-in mbedTLS `Crypto.verify`
   does the check, so the game needs no new dependency. Monotonic `serial` defeats replay/downgrade; `build_min/max`
   bound compatibility.
3. **Delivery is out of the game**: bundles reach `user://liveops/inbox.json` inside a platform update (or
   `forge liveops install` for QA). The game never fetches. G-NET-01 stays strictly green.
4. **Safety**: no bundle or any failure ⇒ manifest defaults ⇒ exactly the shipped behaviour. Rejected bundles go to
   `rejected/`; on-disk tamper or a downgrade swap of `active.json` ⇒ defaults; a boot sentinel quarantines a bundle
   after 2 crashed boots and restores `previous.json`. Rollback is roll-forward (new serial, old content).
5. **Privacy**: consent flags (diagnostics) default off and are only the player's decision; diagnostics are local,
   scrubbed by `forge liveops diag-export`, and never uploaded (there is no endpoint).
6. **Saves are untouched by bundles** (overlay in memory only). A save from a newer build is read-only on an older
   build (never migrated down, never overwritten) so build rollback cannot lose progress.

## Consequences

* A real LiveOps service (CDN, staged rollout, analytics) can be added later behind the same bundle format without a
  game change other than a delivery path — that is a Producer decision and would need its own network-policy ADR.
* Until the Producer pins a production key, every release build ignores every bundle (`forge liveops readiness`
  reports `production_public_key: user_gated`).
* Balance knobs inherit F4's ranges; widening a range is a content change (`forge build` + release), by design.
