# setup_schedule.ps1
# Registers two Windows Task Scheduler tasks to run the CLARA test harness
# at 8:00 AM and 8:00 PM IST daily.
# Run once as Administrator:
#   powershell -ExecutionPolicy Bypass -File setup_schedule.ps1

$ProjectRoot = "E:\ML PROJECTS\AGENT_ZERO"
$PythonExe   = "$ProjectRoot\jarvis_v2\Scripts\python.exe"
$Harness     = "$ProjectRoot\tests\test_harness.py"

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable

$ActionMorning = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$Harness`" --session morning" `
    -WorkingDirectory $ProjectRoot

$TriggerMorning = New-ScheduledTaskTrigger -Daily -At "08:00AM"

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
