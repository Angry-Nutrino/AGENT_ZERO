# setup_ambient_task.ps1 — registers the CLARA Ambient Awareness A0 watcher (BRIEF_39).
# Run ONCE from a normal PowerShell (no admin needed for a current-user task):
#   powershell -ExecutionPolicy Bypass -File .\setup_ambient_task.ps1
#
# Behavior: starts at every logon, restarts itself up to 3x on crash, never expires,
# runs on battery. Kill switch: schtasks /end /tn CLARA_AmbientWatch
# Remove entirely: Unregister-ScheduledTask -TaskName CLARA_AmbientWatch -Confirm:$false
# Consent lives in core_logic/.env (AMBIENT_SENSORS) — empty it and the watcher
# exits on its own at next start.

$py     = "e:\ML PROJECTS\AGENT_ZERO\jarvis_v2\Scripts\python.exe"
$script = "e:\ML PROJECTS\AGENT_ZERO\ambient_watch.py"

$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory "e:\ML PROJECTS\AGENT_ZERO"
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit (New-TimeSpan -Days 0) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable

Register-ScheduledTask -TaskName "CLARA_AmbientWatch" -Action $action -Trigger $trigger -Settings $settings `
    -Description "CLARA Ambient A0 perception watcher (BRIEF_39). Consent: AMBIENT_SENSORS in core_logic/.env." -Force

Start-ScheduledTask -TaskName "CLARA_AmbientWatch"
Start-Sleep -Seconds 5
"Task state: $((Get-ScheduledTask -TaskName 'CLARA_AmbientWatch').State)"
"Last log lines:"
Get-Content "e:\ML PROJECTS\AGENT_ZERO\logs\ambient_watch.log" -Tail 3
