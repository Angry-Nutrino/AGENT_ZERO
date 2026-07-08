# Start the full CLARA stack from PowerShell.
# Why this exists: typing `bash start_clara.sh` in PowerShell resolves `bash` to the WSL
# launcher (C:\Windows\System32 / WindowsApps), and the Windows venv cannot run under WSL —
# the .sh guard rejects it. This wrapper invokes GIT BASH explicitly, so from PowerShell:
#     .\start_clara.ps1
$gitBash = @(
    "C:\Program Files\Git\bin\bash.exe",
    "C:\Program Files (x86)\Git\bin\bash.exe",
    "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $gitBash) {
    Write-Host "[CLARA] ERROR: Git Bash not found (looked in standard install paths). Install Git for Windows." -ForegroundColor Red
    exit 1
}
& $gitBash "$PSScriptRoot\start_clara.sh"
exit $LASTEXITCODE
