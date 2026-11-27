# ADR-0019 — Ship a single-thread Web fallback next to the threads build (closes D-001)

| Field | Value |
|---|---|
| Status | **accepted** |
| Date | 2026-11-26 |
| Deciders | Recharged Ideas (Producer direction t59u "fix quality gaps"); agent implementation |

## Context

ADR-0008 ships the Web build with threads, which needs `SharedArrayBuffer`, so the page must be cross-origin
isolated (COOP `same-origin` + COEP `require-corp`). Hosts that cannot send those headers rely on Godot's service-worker
header shim, which costs a reload on first visit and does not work where service workers are blocked; some embedders
(iframes on portals, older Safari) cannot be isolated at all. D-001 asked whether to add a single-thread fallback.
Godot 4.3 is the first release with a supported `variant/thread_support=false` Web export and ships official
`web_nothreads_*` templates (already fetched since F7).

## Verification (headless Chrome, this box, 2026-11-26)

`forge build --target web-nothreads` exports the same content with the nothreads templates and runs the smoke on a
local static server that sends **no** COOP/COEP headers:

- boots with `crossOriginIsolated == false` and no `SharedArrayBuffer`; no `index.worker.js` is produced;
- the swap advisor runs its serial path (`tools/swapbench`, 17 freeze states, threaded == serial ranking parity);
  p95 132.6 ms / p50 43.3 ms per ranking under SwiftShader WebGL in headless Chrome (desktop native gate: < 50 ms on
  2 pinned cores — the Web fallback is slower and not gated on it);
- a save imported, rewritten and reloaded through IndexedDB is identical on an offline reload;
- the PWA installs and the game boots offline from the SW cache.

**Blocker found and fixed:** Godot 4.3-stable's nothreads export still lists `index.worker.js` in the service worker's
`CACHED_FILES`. The file does not exist, `cache.addAll` fails, the SW install is rejected and the PWA never works
offline. PWAPipeline now drops install-time cache entries the export did not produce (`forge/pwa.py: patch_sw`); it is
a no-op for the threads build. Without the patch the smoke shows `sw_registered: false`, `offline_boot: false`.

## Decision

1. Ship two Web artifacts: `dist/web` (threads + COOP/COEP + SW shim, the default, unchanged) and
   `dist/web-nothreads` (single thread, PWA on, `ensure_cross_origin_isolation_headers=false`, `_headers` without
   COOP/COEP) for hosts or embedders that cannot be isolated.
2. The swap advisor uses threads only when the build has them (`not OS.has_feature("nothreads")`); its serial and
   threaded rankings are already proven identical (F3 swapbench parity).
3. `forge accept F7` (full mode) builds both variants and gates the nothreads smoke and size budget beside G-WEB-01.
4. Choosing which artifact a host serves is a deployment choice; docs/packaging.md describes both. No automatic
   runtime switch between the two is built: [INFERENCE] a loader page that picks one by `crossOriginIsolated` is
   possible but untested, so it is not claimed.

## Consequences

- D-001 is closed. Public HTTPS hosting on real Chrome/Firefox/Safari is still untested (TODO, user-gated hosting).
- The fallback's swap ranking is slower than the native budget in headless SwiftShader (p95 132.6 ms in the first
  measurement, 68.7 ms in the recorded 0.7.14 `forge accept F7` run); real GPUs/CPUs in a browser are unmeasured.
- The SW patch must be re-checked when the Godot version changes (the bug may be fixed upstream).
