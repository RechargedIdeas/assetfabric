# Hardware verification kit (post-F9, 0.9.1)

Everything up to F9 + C1–C12 is proven on the build box (Linux, 8 vCPU, no GPU, no phone, no Windows). What is left
needs **your** hardware: the Windows PC (Shivati), a real Android phone (reference: Redmi Note 12 Pro 5G, D-002) and a
public HTTPS host. This kit turns each of those into one command that writes a machine-checkable report, plus a short
checklist for the things only a person can judge.

| Script (`scripts/verify-hardware/`) | Runs on | Proves automatically | Asks a person |
|---|---|---|---|
| `verify-windows.ps1` | the Windows PC (PowerShell 5.1 or 7) | files == `BUILD.json` SHA-256 · headless `--net-report` (G-NET-01) · full headless slice autoplay · its save loads back · LiveOps diagnostics default Off · windowed boot through the real GPU driver (renderer line recorded) | `-Playtest`: times your session from launch to quit, then the F6 playtest checklist (length 15–20 min, HUD, controls, gamepad, Settings incl. diagnostics toggle, music, art, threat, save/resume, D-005 names/numbers) |
| `verify_android.py` | any desktop with `adb` + the phone on USB debugging | ABI arm64 · both APKs install · Game Zero versionName == its BUILD.json · Game Zero requests **no INTERNET** · headless `--net-report` + full slice autoplay **on the phone** (engine args via intent extra — see note) · both apps launch and stay alive with no crash / `SCRIPT ERROR` in logcat · screenshots | Game Zero: landscape launch, gamepad play, resume after swipe-away, frame pacing. PocketLoom: offline generate, QR pairing, drain + sync, Camera2, MediaProjection, AccessibilityService input, ARCore, timings — every `real_unverified_on_device` path |
| `verify_web.py` | any desktop with the forge venv (`package` extra) + Chrome | per build (`web`, `web-nothreads`): HTTPS + valid certificate · runtime files 200 · wasm MIME · COOP/COEP (threads build) · boots in headless Chrome with 0 script errors · cross-origin isolated (threads) · service worker + runtime cached · swap advisor serial path (nothreads) · IndexedDB save round-trip · offline reload | Firefox, Safari, install as PWA + offline after closing the browser, save survives closing the tab |
| `hwreport.py` | anywhere (stdlib Python) | `check <report.json>` validates + recomputes the verdict (exit 0 pass / 2 incomplete / 1 fail) | `answer <report.json>` walks the open checklist items |

A report is **pass** only when every automated check passed *and* every checklist item is answered (no "no"). Reports
go to `hw-reports/` (gitignored); your user folder is written as `~`, nothing is uploaded. To record a run in the repo,
copy the report to `docs/acceptance-tests/results/hardware/` and say which device it was in the commit message.

## Windows (Shivati)

1. Build or copy the Windows export: `forge build --target desktop-windows` on the build box produces
   `dist/desktop-windows/` (`GameZero.exe`, `GameZero.console.exe`, `GameZero.pck`, `BUILD.json`, …). Copy the whole
   folder plus `scripts/verify-hardware/` to the PC (or clone the repo there).
2. In PowerShell, from the repo root:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\verify-hardware\verify-windows.ps1 -BuildDir dist\desktop-windows
   # then the human playtest (opens the game; quit when you reach the open-world exit):
   powershell -ExecutionPolicy Bypass -File scripts\verify-hardware\verify-windows.ps1 -BuildDir dist\desktop-windows -Playtest
   ```

   The builds are **unsigned**: SmartScreen will warn ("More info → Run anyway"). Authenticode signing is user-gated
   (docs/packaging.md §Signing & stores).
3. `python scripts\verify-hardware\hwreport.py check hw-reports\windows-<stamp>.json`.

Script self-test on the build box: the same script runs under PowerShell 7 on Linux against the Linux export
(`-BuildDir dist/desktop-linux -Exe GameZero.x86_64 -GuiExe GameZero.x86_64`, windowed boot under Xvfb) — all 7
automated checks pass there. That proves the script, **not** Windows.

## Android phone

1. Phone: Settings → About → tap *MIUI/OS version* 7× → Developer options → **USB debugging** on; connect USB, accept
   the RSA prompt. Desktop: Android platform-tools (`adb`) on PATH or `ANDROID_HOME` set.
2. APKs: `dist/android/GameZero-debug.apk` (`forge build --target android`) and
   `dist/pocketloom/pocketloom-0.1.0-c6-debug.apk` (`forge accept C1-C6`). Both are **debug-signed**.
3. Run:

   ```bash
   python scripts/verify-hardware/verify_android.py            # --serial <id> if several devices, --no-autoplay to skip the slice run
   python scripts/verify-hardware/hwreport.py answer hw-reports/android-<stamp>.json
   ```

4. For the PocketLoom pairing items run `forge link serve` on the desktop (same LAN or Tailscale) and scan its QR.
   MirrorWeave input needs PocketLoom's AccessibilityService enabled by hand in system settings; screen capture asks
   for the MediaProjection consent dialog — both are Android policy, not something a script may click.

Note [INFERENCE C-100]: engine arguments reach Godot 4.3's Android activity through the `command_line_params`
string-array intent extra (`am start --esa command_line_params --,--net-report`). If a build does not pick them up,
the two headless checks are reported as `null` (not failed) and the slice is verified by the manual playtest instead.
The flow and parsing are unit-tested against a scripted fake `adb` (tests/test_hw_verification.py) — never against a
phone, so the first real run is the proof.

## Web on a public HTTPS host

1. Upload `dist/web/` (threads) to a host that can send headers — e.g. Netlify / Cloudflare Pages read the generated
   `_headers` file; nginx: see docs/packaging.md §PWAPipeline — and `dist/web-nothreads/` to any static HTTPS host
   (GitHub Pages works: no COOP/COEP needed). Both must be served over HTTPS (service workers require it off localhost).
2. Run from the repo's forge venv (`uv pip install -e ".[dev,package]"`, system Chrome):

   ```bash
   python scripts/verify-hardware/verify_web.py --web https://<host>/gamezero/ --nothreads https://<host>/gamezero-st/
   python scripts/verify-hardware/hwreport.py answer hw-reports/web-<stamp>.json     # Firefox / Safari / PWA items
   ```

`python scripts/verify-hardware/verify_web.py --self-test` serves the local `dist/` builds on loopback HTTP and runs
every check except HTTPS/certificate (reported `null`) — 19/19 automated checks pass on the build box (0.9.1). That
proves the script and the builds, not a public host or another browser engine.

## What stays unproven until you run these

Windows execution and GPU driver, real-phone behaviour of every `real_unverified_on_device` path, on-device timings,
public-host headers/certificates, Firefox/Safari, and the human playtest (length vs 15–20 min, feel, D-005 sign-off).
The kit does not change any of those statuses by itself — a passing report does.
