# Packaging — Game Zero launch candidates (F7)

How to build, verify and hand off every Game Zero platform build. Owner: Fabric. Spec: ASSETFABRIC_SPEC §3 Layer A
(PWAPipeline), §4.5 (ShuttleLine, BoltPack), §13 F7; GAME_SPEC §3, §5, §6.2 (G-WEB-01, G-SAVE-01, G-NET-01, G-A11Y-01).

> **Unsigned / debug builds only.** No public releases (producer direction). Code-signing, store signing and
> store listings are TODO (see [§Signing & stores](#signing--stores-todo)).

## TL;DR

```bash
source .venv/bin/activate
uv pip install -e ".[dev,package]"         # playwright (drives the system Chrome; no browser download)
forge templates status                     # Godot / templates / JDK / Android SDK / Chrome / wine / bwrap
forge templates fetch                      # once: Godot 4.3-stable templates (≈1 GB, sha256-pinned) → .fabric/godot-home
forge build --target all                   # every target → dist/<target>/ + dist/bolt/*.fabricbolt
forge build --target web --skip-smoke      # one target, no smoke runs
forge accept F7                            # full acceptance (≈ 1.7–2.5 min on 8 vCPU) → docs/acceptance-tests/results/F7.json
FORGE_ACCEPT_FAST=1 forge accept F7 --no-write   # static subset (CI / no templates)
```

## Targets

| `--target` | Preset | Mode | Artifact (`dist/<target>/`) | Verified by |
|---|---|---|---|---|
| `desktop-linux` | `desktop-linux` | release | `GameZero.x86_64` + `GameZero.pck` | exported binary boots headless (`--net-report`); full slice run in `forge accept F7` (no network namespace) |
| `desktop-windows` | `desktop-windows` | release | `GameZero.exe` + `GameZero.console.exe` + `GameZero.pck` | PE32+ x86-64 header (GUI + console subsystems); pck file set == Linux and every data file byte-identical. **No runtime smoke** (no wine on the build host — run `GameZero.console.exe --headless -- --net-report` on Windows) |
| `android` | `android` | **debug** | `GameZero-debug.apk` | `aapt dump badging/permissions` (package, versionCode 7, minSdk 21 / targetSdk 34, `arm64-v8a`, launchable, **no INTERNET**), `apksigner verify` (v1+v2+v3, debug key), `apkanalyzer apk download-size`; the APK's packed content runs the full slice on the desktop runtime (no device/emulator — no KVM) |
| `web` | `web` | release (threads) | `index.html` + `index.{js,wasm,pck,worker.js,audio.worklet.js,service.worker.js,manifest.json,offline.html}` + icons + `_headers` | PWAPipeline: G-WEB-01 budget, SW cache list, headless-Chrome smoke (COOP/COEP, isolation, SW, offline reload, header-less host via SW shim) |
| `web-nothreads` | `web-nothreads` | release (single thread, D-001 / ADR-0019) | `index.{html,js,wasm,pck,audio.worklet.js,service.worker.js,manifest.json,offline.html}` + icons + `_headers` (no COOP/COEP) — no `worker.js` | PWAPipeline: budget, SW cache list (+ `patch_sw` fix for Godot 4.3's stale `index.worker.js` entry), headless-Chrome smoke on a header-less host: not isolated, boots, SW + offline boot, swap advisor serial path, IndexedDB save round-trip |

Every target dir also gets `BUILD.json` (command, toolchain, sizes, SHA-256 of every file, smoke results),
`shuttle.json` (ShuttleLine contract check), `sbom.cdx.json` and `LICENSES/` (BoltPack), and a
`dist/bolt/GameZero-<version>-<target>.fabricbolt`. `dist/` is gitignored.

Measured sizes / SHA-256 of the accepted build: [acceptance-tests/F7.md](acceptance-tests/F7.md#measured).

## Toolchain

| Need | Where forge looks | Notes |
|---|---|---|
| Godot 4.3-stable | `GODOT_BIN`, `PATH` (`godot`, `godot4`), `godot-bin/godot` | must report `4.3.stable` |
| Export templates 4.3.stable | `.fabric/godot-home/data/godot/export_templates/4.3.stable/` | `forge templates fetch [--tpz file]`: uses `--tpz`, `$FORGE_TEMPLATES_TPZ`, `.fabric/cache/…tpz`, else downloads `Godot_v4.3-stable_export_templates.tpz` and checks sha256 `f5f10dba…7b922`; only the 14 templates the targets need are extracted (~510 MB) |
| JDK 17 (Android) | `JAVA_HOME`, `.fabric/jdk/jdk-17*`, `/workspace/jdk/jdk-17*`, `java` on PATH | apksigner/keytool need it on PATH; forge adds it |
| Android SDK | `ANDROID_HOME`, `ANDROID_SDK_ROOT`, `companions/pocketloom/local.properties` `sdk.dir`, `/workspace/android-sdk` | needs `build-tools` (aapt, apksigner, zipalign) + `platform-tools`; Godot 4.3 picks build-tools 34 |
| Chrome | `google-chrome` / `chromium` on PATH | PWAPipeline smoke + G-SAVE-01 web hop (Playwright `executable_path`, SwiftShader WebGL2) |
| bwrap | `PATH` | runs the desktop slice in a network-less namespace (G-NET-01) |
| wine (optional) | `PATH` | if present, smokes `GameZero.console.exe` |

Godot runs **hermetically**: `XDG_CONFIG_HOME/DATA_HOME/CACHE_HOME` → `.fabric/godot-home/{config,data,cache}`.
forge writes `editor_settings-4.3.tres` there (SDK path, JDK path, debug keystore) and generates a **debug keystore**
(`.fabric/godot-home/debug.keystore`, alias `androiddebugkey`, the standard Android debug password `android`).
Nothing in `.fabric/godot-home`, `.fabric/cache`, `dist/`, `*.keystore` is committed.

## How a build works

1. **Stage** — `games/game-zero` is copied to `dist/.stage/game-zero` (no `.godot/`). Fabric output in
   `assets/generated/` is runtime-loaded by design (F1: no editor import, `.gdignore`), and Godot never exports
   a `.gdignore`d folder. In the stage only, the `.gdignore` is removed and every PNG/WAV gets an
   `importer="keep"` stub, so the files ship byte-for-byte; then `godot --headless --import` [INFERENCE F7-2].
2. **Export** — `godot --headless --path dist/.stage/game-zero --export-<mode> <preset> dist/<target>/<artifact>`
   with the checked-in presets (`games/game-zero/export_presets.cfg`: `include_filter` ships
   `assets/generated/*`, `data/generated/*`, `locale/*.json`; scripts exported as binary tokens).
   Log: `dist/.logs/<target>.log`.
3. **Verify** — per target (table above).
4. **ShuttleLine** — `dist/<target>/shuttle.json`: every registry file is in the shipped PCK/APK, byte-identical
   (`keep` files) or as a converted resource behind its `.remap` (`.tres` abilities), plus the required runtime
   data (`fabric_assets.json`, `game_data.json`, `world.json`, `locale/en.json`).
5. **BoltPack** — SBOM (CycloneDX 1.5) + license audit + `LICENSES/` + `.fabricbolt` (unsigned).

## PWAPipeline (Web)

* Godot's PWA output (service worker, manifest, offline page, `ensure_cross_origin_isolation_headers`) +
  **threads** build. COOP/COEP are required for `SharedArrayBuffer`; the swap advisor uses `WorkerThreadPool`.
  The SW shim injects COOP/COEP on hosts that cannot send headers (first visit reloads once) [INFERENCE F7-3].
* Post-steps: `index.html` gets an opt-in QA hook — engine args from the URL fragment
  `#fabric-args=<url-encoded JSON array>` (fragments never reach the server or the SW cache key);
  `_headers` (Netlify / Cloudflare Pages format) is written next to the build.
* **G-WEB-01 budget**: sum of gzip-9 sizes of every file < 45 000 000 bytes (decimal MB, stricter) [INFERENCE F7-4].
* Smoke (local `http.server` + headless Chrome): response headers on html/wasm/pck, `crossOriginIsolated` +
  `SharedArrayBuffer`, game boots with 0 script errors, SW registered and controlling, wasm/pck in the SW cache,
  **offline reload** (context offline) boots from cache, and a header-less host reaches isolation via the SW.
* **Single-thread fallback (`web-nothreads`, ADR-0019)** for hosts or embedders that cannot be cross-origin isolated:
  Godot 4.3 `web_nothreads_*` templates, PWA on, no isolation shim, no COOP/COEP needed — any static host works.
  The swap advisor runs its serial path (`OS.has_feature("nothreads")`). Post-step `patch_sw` drops install-time SW
  cache entries the export did not produce: 4.3-stable lists a non-existent `index.worker.js`, which otherwise makes
  the SW install fail (no offline play). Serve `dist/web` where you control headers, `dist/web-nothreads` elsewhere.

Hosting with nginx:

```nginx
location /gamezero/ {
    add_header Cross-Origin-Opener-Policy same-origin always;
    add_header Cross-Origin-Embedder-Policy require-corp always;
    location ~ \.(service\.worker\.js|html)$ { add_header Cache-Control no-cache; add_header Cross-Origin-Opener-Policy same-origin always; add_header Cross-Origin-Embedder-Policy require-corp always; }
    types { application/wasm wasm; }
}
```

## ShuttleLine (multi-target import contract)

`forge shuttle contract [--check]` prints `shuttleline.contract/1` (assets, kinds, generator, files + SHA-256, per-adapter
import rule). Adapters: `godot` (real, F1), `generic-folder` (real, F7: `forge shuttle export` → `dist/shuttle/generic-folder/<kind>/<asset>/<file>` + `shuttle.json`),
`unity` / `unreal` **not built** (contract describes their import rule) [INFERENCE F7-6].

## BoltPack (SBOM + license manifest)

Components per target: `godot-engine 4.3-stable` (MIT, SHA-256 of the exact template used), every third-party
component compiled into the engine as reported by the binary (`Engine.get_copyright_info()`, ~80), Android
`libc++_shared` (Apache-2.0 WITH LLVM-exception) + Godot Android lib, Web Emscripten runtime (MIT OR NCSA), and
`game-zero` (LicenseRef-Proprietary, asset/generator provenance). Audit: every license atom on the allow-list, any
GPL/LGPL/AGPL/SSPL/EUPL fails; MPL-2.0 (Mozilla CA certificates in the engine) is reported as weak copyleft.
Python/forge dependencies do not ship in the game and are not in its SBOM.

## Saves across platforms (G-SAVE-01)

One format everywhere: Player State v4, canonical JSON + SHA-256 (`autoload/save.gd` ≡ `forge/save.py`). Save dir:
`user://saves` — Linux `~/.local/share/godot/app_userdata/Game Zero/saves`, Windows `%APPDATA%\Godot\app_userdata\Game Zero\saves`,
Android app-private storage, Web IndexedDB (`/userfs`). `--scene=savecheck --import-b64=<base64> [--rewrite]` imports a
save from another device. On Web, Godot persists `user://` to IndexedDB from the main loop, so the game waits a few
frames before quitting after a save (`Save.quit_after_persist`) [INFERENCE F7-5]. Cloud sync is out of scope (GAME_SPEC §5).

## PocketLoom companion APK (C1–C6)

PocketLoom is a separate, native Kotlin app (not a Godot export) built with Gradle from `companions/pocketloom/`:

```bash
forge accept C1-C6     # builds + verifies + records results; copies the APK to dist/pocketloom/pocketloom-0.1.0-c6-debug.apk
# or by hand:
cd companions/pocketloom && ./gradlew :fabriccore:test :fabriccore:fatJar :app:assembleDebug :app:lintDebug
```

| | |
|---|---|
| Toolchain | Gradle 8.9 (wrapper, committed), AGP 8.7.3, Kotlin 2.0.21, JDK 17 (same discovery as above), Android SDK `platforms;android-35` + build-tools 35 |
| SDK path | `ANDROID_HOME` / `ANDROID_SDK_ROOT`, or `companions/pocketloom/local.properties` (`sdk.dir=…`, **gitignored**) |
| Output | `app/build/outputs/apk/debug/app-debug.apk` → `dist/pocketloom/` (both gitignored), ≈ 0.89 MB, no native libs |
| Signing | Android Gradle **debug** keystore (`~/.android/debug.keystore`, auto-created) — so the APK SHA-256 differs per machine. Release keystore / AAB / Play listing: TODO (below) |
| Verify | `aapt dump badging`, `apksigner verify`, Android lint (0 errors, 0 i18n issues), dex contains FabricCore — see docs/acceptance-tests/C1-C6.md |
| Install | `adb install -r dist/pocketloom/pocketloom-0.1.0-c6-debug.apk` (not yet done on hardware — no device on the build box) |

Unlike the Game Zero APK (no `INTERNET`), PocketLoom requests `INTERNET` — used only after the user pairs with a desktop
(LoomLink, INFERENCES C-7). It requests no camera/storage permissions.

## Signing & stores (TODO)

- [ ] Windows Authenticode signing (`codesign/enable`, rcedit for icon/version resources) — needs a code-signing cert.
- [ ] Linux: AppImage/Flatpak packaging + signature.
- [ ] macOS (out of scope for v1 targets; needs notarisation).
- [ ] PocketLoom release signing (own release keystore via env, `signingConfigs`), AAB, Play listing.
- [ ] Android release keystore (never committed; `GODOT_ANDROID_KEYSTORE_RELEASE_*` env), AAB via gradle build, Play listing, D-002 device test on the Redmi Note 12 Pro 5G.
- [ ] Web: host choice + HTTPS + headers; itch.io/own host listing.
- [ ] BoltPack detached signature over `bolt.json` (release key).
- [ ] Store listings (copy, screenshots, ratings) — Producer.

## CI

Exports are **local-only** for now: the templates are ≈1 GB, the APK needs JDK 17 + Android SDK and the full F7
acceptance takes ≈ 2.5 min on top of a ≈ 14 min pytest job. CI runs the F7 **fast** subset inside pytest (presets,
targets, ShuttleLine vs sources, BoltPack SBOM/audit, network-API scan, editor save/remap round-trip). A separate
cached `package` job is a TODO once a runner budget is agreed.

PocketLoom **does** build in CI: job `pocketloom` (setup-java 17 + Gradle cache + the runner's Android SDK) runs
`forge accept C1-C6 --no-write` — Gradle with warm caches is ≈ 1 min, so it stays cheap.
