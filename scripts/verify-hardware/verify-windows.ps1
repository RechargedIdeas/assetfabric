<#
.SYNOPSIS
  Game Zero Windows smoke + playtest kit (post-F9, 0.9.1) - run on the Windows PC (Shivati) with the exported build.

.DESCRIPTION
  Automated (no window): build files present and byte-identical to BUILD.json (SHA-256), headless `--net-report`
  (networking dormant, version), a full headless vertical-slice autoplay into a temp save dir, the save it wrote loads
  back, LiveOps diagnostics default Off. Then a windowed boot through the real GPU driver (OpenGL 3.3 Compatibility
  renderer; the "Using Device" line is recorded). With -Playtest it launches the game normally, times your session
  and asks the docs/acceptance-tests/F6.md checklist when you quit.
  Writes hw-reports\windows-<stamp>.json (same format as verify_android.py / verify_web.py; check it with
  `python scripts\verify-hardware\hwreport.py check <file>`). Nothing is uploaded; your user folder is shown as "~".
  Works with Windows PowerShell 5.1 and PowerShell 7.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\verify-hardware\verify-windows.ps1 -BuildDir dist\desktop-windows
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\verify-hardware\verify-windows.ps1 -BuildDir C:\GameZero -Playtest
#>
[CmdletBinding()]
param(
    [string]$BuildDir = (Join-Path $PSScriptRoot "..\..\dist\desktop-windows"),
    [string]$Exe = "GameZero.console.exe",          # console wrapper: forwards the game's stdout (FABRIC_RESULT lines)
    [string]$GuiExe = "GameZero.exe",
    [string]$Out = (Join-Path $PSScriptRoot "..\..\hw-reports"),
    [switch]$Playtest,
    [switch]$SkipGpuBoot,
    [int]$TimeoutSec = 600
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2

$BuildDir = (Resolve-Path $BuildDir).Path
$HomeDir = [Environment]::GetFolderPath("UserProfile")
$Checks = New-Object System.Collections.ArrayList
$Device = [ordered]@{}

function Hide-Home([string]$s) {
    if ($HomeDir -and $s) { return $s.Replace($HomeDir, "~") }
    return $s
}

function Add-Check([string]$Id, $Ok, $Detail) {
    [void]$Checks.Add([ordered]@{ id = $Id; ok = $Ok; detail = $Detail })
    $mark = if ($Ok -eq $true) { "PASS" } elseif ($Ok -eq $false) { "FAIL" } else { "----" }
    Write-Host ("  [{0}] {1}" -f $mark, $Id)
}

function Invoke-Game([string[]]$GameArgs, [int]$Timeout = $TimeoutSec, [switch]$Windowed, [string]$Binary = $Exe) {
    $exePath = Join-Path $BuildDir $Binary
    $all = @()
    if (-not $Windowed) { $all += "--headless" }
    $all += "--"
    $all += $GameArgs
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exePath
    $psi.Arguments = ($all | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join " "
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.WorkingDirectory = $BuildDir
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $p = [System.Diagnostics.Process]::Start($psi)
    $so = $p.StandardOutput.ReadToEndAsync()
    $se = $p.StandardError.ReadToEndAsync()
    $done = $p.WaitForExit($Timeout * 1000)
    if (-not $done) { try { $p.Kill() } catch { } }
    $p.WaitForExit()
    $text = $so.Result + "`n" + $se.Result
    $res = $null
    foreach ($line in ($text -split "`r?`n")) {
        $i = $line.IndexOf("FABRIC_RESULT ")
        if ($i -ge 0) { try { $res = $line.Substring($i + 14) | ConvertFrom-Json } catch { } }
    }
    $scriptErrors = ([regex]::Matches($text, "SCRIPT ERROR")).Count
    return [ordered]@{ exit = $(if ($done) { $p.ExitCode } else { "timeout" }); result = $res; script_errors = $scriptErrors
                       wall_s = [math]::Round($sw.Elapsed.TotalSeconds, 1); text = $text }
}

function New-TempDir([string]$Name) {
    $d = Join-Path ([IO.Path]::GetTempPath()) ("gamezero-hw-" + $Name + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Path $d | Out-Null
    return $d.Replace("\", "/")             # Godot takes forward slashes on every platform
}

Write-Host "Game Zero hardware verification (Windows) - $BuildDir"
$Device.os = [Environment]::OSVersion.VersionString
$Device.logical_cpus = [Environment]::ProcessorCount
try {
    $Device.cpu = (Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1 -ExpandProperty Name)
    $Device.gpus = @(Get-CimInstance Win32_VideoController -ErrorAction Stop | ForEach-Object { $_.Name + " (driver " + $_.DriverVersion + ")" })
} catch {
    $Device.cpu = "unknown (no CIM on this host)"
    $Device.gpus = @()
}

# 1. files + SHA-256 against BUILD.json
$need = @($Exe, "GameZero.pck", "BUILD.json")
if ($GuiExe -and ($GuiExe -ne $Exe)) { $need += $GuiExe }
$missing = @($need | Where-Object { -not (Test-Path (Join-Path $BuildDir $_)) })
Add-Check "files_present" ($missing.Count -eq 0) @{ needed = $need; missing = $missing }
$build = $null
if (Test-Path (Join-Path $BuildDir "BUILD.json")) {
    $build = Get-Content -Raw -Encoding UTF8 (Join-Path $BuildDir "BUILD.json") | ConvertFrom-Json
    $bad = @(); $checked = 0
    foreach ($f in $build.files) {
        $fp = Join-Path $BuildDir $f.path
        if (Test-Path $fp -PathType Leaf) {
            $checked++
            $h = (Get-FileHash -Algorithm SHA256 -Path $fp).Hash.ToLower()
            if ($h -ne $f.sha256) { $bad += $f.path }
        }
    }
    Add-Check "sha256_matches_build_json" (($bad.Count -eq 0) -and ($checked -ge 2)) @{ checked = $checked; mismatched = $bad; target = $build.target }
}

# 2. headless runs (no window, CPU only)
$nr = Invoke-Game @("--net-report") 120
$ver = $null
if ($nr.result) { $ver = $nr.result.version }
Add-Check "headless_net_report" (($nr.exit -eq 0) -and ($null -ne $nr.result) -and ($nr.result.net.offline_peer -eq $true)) @{ exit = $nr.exit; version = $ver; wall_s = $nr.wall_s }

$saves = New-TempDir "saves"
$sl = Invoke-Game @("--scene=slice", "--autoplay", "--no-live", "--watchdog=$TimeoutSec", "--save-dir=$saves")
$s = $null
if ($sl.result) { $s = $sl.result.slice }
$slOk = ($sl.exit -eq 0) -and ($null -ne $s) -and ($s.completed -eq $true) -and ($s.wipes -eq 0) -and ($sl.script_errors -eq 0)
$slDetail = @{ exit = $sl.exit; script_errors = $sl.script_errors; wall_s = $sl.wall_s }
if ($s) { $slDetail.completed = $s.completed; $slDetail.wipes = $s.wipes; $slDetail.game_minutes = $s.game_minutes }
Add-Check "headless_slice_autoplay" $slOk $slDetail

$sc = Invoke-Game @("--scene=savecheck", "--save-dir=$saves") 120
$scr = $null
if ($sc.result) { $scr = $sc.result.savecheck }
Add-Check "save_written_and_loads" (($null -ne $scr) -and ($scr.last_load.ok -eq $true) -and ($null -ne $scr.loaded)) @{ exit = $sc.exit; platform = $(if ($scr) { $scr.platform } else { $null }) }

$lo = Invoke-Game @("--scene=liveopscheck", "--liveops-dir=$(New-TempDir 'liveops')") 120
$lr = $null
if ($lo.result) { $lr = $lo.result.liveops }
Add-Check "diagnostics_default_off" (($null -ne $lr) -and ($lr.flags.diagnostics -eq $false) -and ($lr.diag_written -eq $false)) @{ exit = $lo.exit }

# 3. windowed boot through the real GPU driver
if ($SkipGpuBoot) {
    Add-Check "gpu_windowed_boot" $null "skipped (-SkipGpuBoot)"
} else {
    $gb = Invoke-Game @("--net-report") 120 -Windowed
    $dev = ($gb.text -split "`r?`n" | Where-Object { $_ -match "Using Device|OpenGL API" } | Select-Object -First 2) -join " | "
    $Device.renderer = $dev
    Add-Check "gpu_windowed_boot" (($gb.exit -eq 0) -and ($gb.script_errors -eq 0) -and ($null -ne $gb.result)) @{ exit = $gb.exit; renderer = $dev; wall_s = $gb.wall_s }
}

# 4. manual checklist (+ optional timed playtest)
$lists = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot "checklists.json") | ConvertFrom-Json
$manual = New-Object System.Collections.ArrayList
foreach ($i in $lists.playtest) { [void]$manual.Add([ordered]@{ id = $i.id; ask = $i.ask; kind = $i.kind; section = "playtest"; answer = $null }) }
if ($Playtest) {
    Write-Host ""
    Write-Host "Playtest: the game opens now. Play from character select to the open-world exit, then quit (Escape -> Quit or close the window)."
    $t0 = Get-Date
    $gp = Start-Process -FilePath (Join-Path $BuildDir $GuiExe) -WorkingDirectory $BuildDir -PassThru
    $gp.WaitForExit()
    $mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    $Device.playtest_session_minutes = $mins
    Write-Host "Session: $mins minutes. Answer the checklist (Enter skips; you can answer later with hwreport.py answer)."
    foreach ($m in $manual) {
        $hint = if ($m.kind -eq "yes_no") { " [y/n]" } elseif ($m.id -eq "slice_length") { " [session was $mins min]" } else { "" }
        $a = Read-Host ($m.ask + $hint)
        if ($a) { $m.answer = $a }
    }
}

# 5. report
$checksOk = @($Checks | Where-Object { $_.ok -eq $false }).Count -eq 0
$neg = @($manual | Where-Object { $_.kind -eq "yes_no" -and $_.answer -and ($_.answer.Trim().ToLower() -in @("n", "no", "false")) }).Count
$open = @($Checks | Where-Object { $null -eq $_.ok }).Count + @($manual | Where-Object { -not $_.answer }).Count
$verdict = if ((-not $checksOk) -or ($neg -gt 0)) { "fail" } elseif ($open -gt 0) { "incomplete" } else { "pass" }
$rep = [ordered]@{
    format = "assetfabric-hw-report"; schema = 1; target = "windows"; tool = "verify-windows.ps1"
    build_version = $(if ($ver) { $ver } elseif ($build) { $build.version } else { $null })
    started = (Get-Date).ToString("o"); device = $Device; checks = $Checks; manual = $manual; verdict = $verdict
}
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$file = Join-Path $Out ("windows-" + (Get-Date).ToString("yyyyMMdd-HHmmss") + ".json")
$json = Hide-Home ($rep | ConvertTo-Json -Depth 10)
[IO.File]::WriteAllText($file, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ""
Write-Host "Verdict: $($verdict.ToUpper())   report: $file"
Write-Host "Check / finish it with: python scripts\verify-hardware\hwreport.py check $file   (or: hwreport.py answer $file)"
if ($verdict -eq "fail") { exit 1 } else { exit 0 }
