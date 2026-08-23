# setup_schedule.ps1
# Registers two Windows Task Scheduler tasks to run the CLARA test harness
# at 8:00 AM and 8:00 PM IST daily.
# Run once as Administrator (the tasks use -RunLevel Highest):
#   cd E:\ML_PROJECTS\AGENT_ZERO
#   powershell -ExecutionPolicy Bypass -File .\setup_schedule.ps1
#
# Paths derive from THIS script's own location ($PSScriptRoot = the project root, since this
# file lives there). NEVER hardcode the project path: the folder was renamed once
# (ML PROJECTS -> ML_PROJECTS, 2026-06-16) and the old hardcoded space-path silently broke both
# crons (0x80070002 file-not-found). $PSScriptRoot survives any rename or move. -StartWhenAvailable
# means a run missed while the laptop is off (e.g. 2026-06-17 morning) catches up on next wake.

$ProjectRoot = $PSScriptRoot
$PythonExe   = Join-Path $ProjectRoot "jarvis_v2\Scripts\python.exe"
$Harness     = Join-Path $ProjectRoot "tests\test_harness.py"

if (-not (Test-Path $PythonExe)) { Write-Error "python.exe not found at $PythonExe"; exit 1 }
if (-not (Test-Path $Harness))   { Write-Error "test_harness.py not found at $Harness"; exit 1 }

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable

$ActionMorning = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$Harness`" --session morning" `
    -WorkingDirectory $ProjectRoot

# 10:00 IST, NOT 08:00 (changed 2026-08-15). From 16 Aug 2026 the model provider bills peak/off-peak,
# with peak at DOUBLE the off-peak rate. Peak is 01:00-04:00 and 06:00-10:00 UTC, which in IST is
# 06:30-09:30 and 11:30-15:30. The old 08:00 IST start = 02:30 UTC sat in the middle of the first peak
# block and paid 2x for every morning run (~$0.24 wasted per run on measured token counts). 10:00 IST =
# 04:30 UTC lands in the gap BETWEEN the two peak blocks, with ~2h of margin on the far side so a long
# run cannot drift into the 11:30 IST peak. The evening run at 20:00 IST = 14:30 UTC was already
# off-peak and is unchanged.
$TriggerMorning = New-ScheduledTaskTrigger -Daily -At "10:00AM"

Register-ScheduledTask `
    -TaskName "CLARA_Test_Morning" `
    -Action $ActionMorning `
    -Trigger $TriggerMorning `
    -Settings $Settings `
    -Description "CLARA daily morning stress test" `
    -RunLevel Highest `
    -Force

Write-Host "Morning task registered."

$ActionEvening = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$Harness`" --session evening" `
    -WorkingDirectory $ProjectRoot

$TriggerEvening = New-ScheduledTaskTrigger -Daily -At "08:00PM"

Register-ScheduledTask `
    -TaskName "CLARA_Test_Evening" `
    -Action $ActionEvening `
    -Trigger $TriggerEvening `
    -Settings $Settings `
    -Description "CLARA daily evening stress test" `
    -RunLevel Highest `
    -Force

Write-Host "Evening task registered."
Write-Host "Done. Verify in Task Scheduler > Task Scheduler Library."
