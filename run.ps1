param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsList
)

if ($ArgsList -contains "ui" -or $ArgsList -contains "-ui") {
    & "$PSScriptRoot\run_ui.ps1"
    exit
}

# IncuBrix Prompt-Based Video Editing Engine Automated Launcher
Write-Host "Starting IncuBrix Automated Pipeline..." -ForegroundColor Cyan
python "$PSScriptRoot\run_all.py" $ArgsList
