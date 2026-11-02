# Registers (or removes) a Windows scheduled task that emails the daily brief.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_brief.ps1 -Time 08:00
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_brief.ps1 -Remove
#
# The task runs `python -m app.brief` from the project folder and appends its output to briefs\brief.log.
# If the PC is off at that time, it runs as soon as the PC is on again.

param(
    [string]$Time = "08:00",
    [string]$TaskName = "SolarNewsBrief",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    return
}

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python not found at $python. Create the venv first (see README)."
}
New-Item -ItemType Directory -Force (Join-Path $root "briefs") | Out-Null

$command = "`"$python`" -m app.brief >> briefs\brief.log 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $command" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Emails the daily solar news impact brief (agentic-news-impact-researcher)." -Force | Out-Null

Write-Host "Scheduled '$TaskName' every day at $Time."
Write-Host "Test it now with:  Start-ScheduledTask -TaskName $TaskName   (log: briefs\brief.log)"
