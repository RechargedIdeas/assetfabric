# verify-hardware

One-command checks for the hardware the build box does not have. Full guide: [docs/hardware-verification.md](../../docs/hardware-verification.md).

| Script | Target |
|---|---|
| `verify-windows.ps1` | Windows `.exe` smoke + timed human playtest (PowerShell 5.1 / 7) |
| `verify_android.py` | Game Zero + PocketLoom APKs on a real phone via `adb` |
| `verify_web.py` | `web` + `web-nothreads` on a public HTTPS host (headless Chrome) |
| `hwreport.py` | `check` / `answer` the JSON reports (stdlib only) |
| `checklists.json` | the manual items each report carries |

Reports land in `hw-reports/` (gitignored).
