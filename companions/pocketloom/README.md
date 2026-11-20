# PocketLoom — Android companion (companion track C1–C6)

PocketLoom is the **standalone, offline** Android edition of AssetFabric (SPEC §8: two *equal* editions, not
phone-as-peripheral). Everything below works with **nothing else connected**; pairing with a desktop only adds
offload and sync.

**State (2026-11-12):** C1–C6 accepted as a **debug APK** (`0.1.0-c6`, ≈ 0.89 MB, arm-agnostic, no native code).
Verified with `aapt`, `apksigner`, Android lint and JVM unit tests; the shared FabricCore code is exercised end to end
on the JVM against the real desktop LoomLink server. **Not yet run on a phone or emulator** (no device, no KVM on the
build box) — first on-device run is a TODO (Redmi Note 12 Pro 5G, D-002).

| ID | Delivers | Where |
|---|---|---|
| C1 | **FabricCore** (pure Kotlin/JVM, no third-party runtime deps): `JobSpec`/`JobExecutor` contract, `LocalExecutor`, `Dispatcher` (run here or queue), content-addressed `AssetStore` with version vectors, `OffloadQueue` journal, `Telemetry`, `PocketLoomCore` facade, CLI | `fabriccore/` |
| C2 | **LocalForge** on-device generation: CA caves (solvability + floor-ratio gates) and mirrored 8-bit sprites (palette-locked, symmetric, fill gates), gate → retry on derived sub-seeds, PatternVault palettes bundled at build time. Backend ladder `onnx-small → CPU procedural`; the ONNX rung is an **honest stub** (runtime not bundled) so the CPU rung always runs. `ModelCache` with byte-budget LRU eviction + pins | `LocalForge.kt`, `Models.kt` |
| C3 | **Standalone UI** (platform widgets, no AndroidX): Generate · Library · Capture · Link · Telemetry. All strings in `res/values/strings.xml` (+ plurals); lint 0 errors / 0 i18n issues | `app/` |
| C4 | **Local capture**: system camera intent (writes through a private `CaptureProvider`, no CAMERA permission) or document-picker import → sniffed (JPEG/PNG/WebP) + dimensions → store as `capture` with telemetry → `recon.capture` job queued for the desktop. Reconstruction itself (C10–C12) is **not built** | `Capture.kt`, `CaptureProvider.kt` |
| C5 | **Pairing (LoomLink)**: 8-char one-time code, `loomlink://pair?u=…&c=…` URI (QR from `forge link serve`; any camera app opens PocketLoom via the intent filter, the user confirms), Tailscale = just use the desktop's 100.x address. HMAC-SHA256 mutual proof (code never sent), per-device key, capability intersection, signed requests (ts window + monotonic, replay refused) | `LoomLink.kt`, `forge/loomlink.py` |
| C6 | **Offload + sync**: durable `OffloadQueue` drains when paired (offline-safe: unsent jobs stay); captures expanded from the store at send time. Library sync by version vectors: dominate → copy, identical bytes → merge vectors, concurrent edits → **keep both** (`<id>~<phone id>` on both sides); a second round is a no-op | `Sync.kt`, `Jobs.kt` |

## Build

```bash
# needs JDK 17 (JAVA_HOME or /workspace/jdk/jdk-17*) and an Android SDK with platforms;android-35 + build-tools
cd companions/pocketloom
echo "sdk.dir=$ANDROID_HOME" > local.properties     # gitignored; or just export ANDROID_HOME
./gradlew :fabriccore:test :fabriccore:fatJar :app:assembleDebug :app:lintDebug
# → app/build/outputs/apk/debug/app-debug.apk   (forge accept copies it to dist/pocketloom/, gitignored)
```

Or from the repo root: `forge accept C1-C6` (builds once, verifies, records `docs/acceptance-tests/results/C*.json`).

Install on a phone (USB debugging): `adb install -r dist/pocketloom/pocketloom-0.1.0-c6-debug.apk`.

## Pair with a desktop

```bash
forge link serve --bind <LAN-or-Tailscale-IP> --port 8765     # prints code, loomlink:// URI, QR if `qrcode` is installed
```

Scan the QR with the phone camera (or type the address + code on the Link tab) → **Pair**. The desktop grants
`offload,sync` by default (`--allow` to change). Then *Send queued jobs* / *Sync library*.

## FabricCore CLI (same code as the APK)

```bash
java -jar fabriccore/build/libs/fabriccore-all.jar gen --home /tmp/pl --kind cave --seed 1 --count 4
java -jar fabriccore/build/libs/fabriccore-all.jar capture --home /tmp/pl --file photo.jpg
java -jar fabriccore/build/libs/fabriccore-all.jar pair --home /tmp/pl --uri 'loomlink://pair?u=…&c=…'
java -jar fabriccore/build/libs/fabriccore-all.jar drain|sync|status --home /tmp/pl
```

## Not built yet (honest)

ONNX runtime + small models (C2 stub rung) · TLS / certificate pinning on raw LAN (HMAC integrity only; use Tailscale for
encryption) · Android Keystore wrapping of the session key (stored in app-private storage, excluded from backup) ·
in-app QR scanner (relies on the system camera app) · MirrorWeave / drive-desktop (C9) · LensForge depth / ARCore (C10–C11)
· reconstruction (C12) · Kotlin Multiplatform targets for FabricCore (JVM only) · release signing / Play listing.
See `docs/INFERENCES.md` §C and `TODO.md`.
