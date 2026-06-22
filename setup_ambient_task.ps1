# setup_ambient_task.ps1 - registers the CLARA Ambient Awareness A0 watcher (BRIEF_39).
# Run from a normal PowerShell (no admin needed for a current-user task):
#   powershell -ExecutionPolicy Bypass -File .\setup_ambient_task.ps1
# Safe to RE-RUN: it stops any existing instance first, then re-registers and restarts.
#
# Behavior: starts at every logon, restarts up to 3x on crash, never expires, runs on
# battery. Launched with pythonw.exe -> NO console window, NO taskbar button (runs in your
# interactive session so the active_window sensor still works; nothing to accidentally close).
# Kill switch: schtasks /end /tn CLARA_AmbientWatch
# Remove entirely: Unregister-ScheduledTask -TaskName CLARA_AmbientWatch -Confirm:$false
# Consent lives in core_logic/.env (AMBIENT_SENSORS) - empty it and the watcher exits at next start.

# Paths derive from THIS script's own location ($PSScriptRoot = project root, since this file
# lives there). NEVER hardcode the project path: the folder was renamed once (ML PROJECTS ->
# ML_PROJECTS, 2026-06-16) and every hardcoded path silently broke the task. $PSScriptRoot
# survives any rename or move.
$root   = $PSScriptRoot
# pythonw.exe is the console-less Python (same venv, same deps) - this removes the cmd window
# and taskbar tab. ambient_watch.py writes to logs/ambient_watch.log, so losing the console
# loses nothing (its one print() is already try/except-guarded for stdout=None).
$py     = Join-Path $root "jarvis_v2\Scripts\pythonw.exe"
$script = Join-Path $root "ambient_watch.py"
$log    = Join-Path $root "logs\ambient_watch.log"

if (-not (Test-Path $py))     { Write-Error "pythonw.exe not found at $py"; exit 1 }
if (-not (Test-Path $script)) { Write-Error "ambient_watch.py not found at $script"; exit 1 }

# Stop a previously-registered instance so re-running cleanly swaps to the new action and
# frees the single-instance socket (port 8771) the watcher holds. Ignore if not present.
try { Stop-ScheduledTask -TaskName "CLARA_AmbientWatch" -ErrorAction Stop } catch {}

# Kill any STRAY watcher (one left running before a rename, or a manual launch) so the new
# task instance is not blocked by the single-instance socket. Matched by command line, so this
# only ever touches ambient_watch.py and never the backend Python.
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*ambient_watch.py*' } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }

$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $root
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit (New-TimeSpan -Days 0) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable

Register-ScheduledTask -TaskName "CLARA_AmbientWatch" -Action $action -Trigger $trigger -Settings $settings `
    -Description "CLARA Ambient A0 perception watcher (BRIEF_39). Consent: AMBIENT_SENSORS in core_logic/.env." -Force

Start-ScheduledTask -TaskName "CLARA_AmbientWatch"
Start-Sleep -Seconds 5

$state = (Get-ScheduledTask -TaskName "CLARA_AmbientWatch").State
$rc    = (Get-ScheduledTaskInfo -TaskName "CLARA_AmbientWatch").LastTaskResult
Write-Host "Task state: $state"
Write-Host "Last run result: $rc  (0 = OK)"
Write-Host "Action exe: $py"
Write-Host "Last log lines:"
if (Test-Path $log) { Get-Content $log -Tail 3 } else { Write-Host "  (no log yet - re-check in a few seconds)" }
