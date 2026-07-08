# Stop the full CLARA stack from PowerShell (see start_clara.ps1 for why Git Bash is invoked explicitly).
#     .\stop_clara.ps1
$gitBash = @(
    "C:\Program Files\Git\bin\bash.exe",
    "C:\Program Files (x86)\Git\bin\bash.exe",
    "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $gitBash) {
    Write-Host "[CLARA] ERROR: Git Bash not found (looked in standard install paths). Install Git for Windows." -ForegroundColor Red
    exit 1
}
& $gitBash "$PSScriptRoot\stop_clara.sh"
exit $LASTEXITCODE
