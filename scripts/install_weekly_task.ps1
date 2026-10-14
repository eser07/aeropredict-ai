# Installs a Thursday 03:15 Turkey-time local AeroPredict AI refresh task.
# Usage from WSL:
# powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w scripts/install_weekly_task.ps1)" -Distribution Ubuntu-24.04 -LinuxUser eser -LinuxProjectPath /home/eser/aeropredict-ai
#
# This uses an interactive Windows logon token (no password saved).
# It does not run as Administrator and does not connect a wallet.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$Distribution,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z_][a-z0-9_-]*$')]
    [string]$LinuxUser,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^/[A-Za-z0-9_./-]+$')]
    [string]$LinuxProjectPath
)

$ErrorActionPreference = 'Stop'
$TaskName = 'AeroPredict AI Weekly Refresh'

$Zone = (Get-TimeZone).Id
if ($Zone -ne 'Turkey Standard Time') {
    throw "Expected Windows time zone 'Turkey Standard Time', got '$Zone'. Scheduling aborted."
}

$WslExe = Join-Path $env:WINDIR 'System32\wsl.exe'
if (-not (Test-Path -LiteralPath $WslExe)) {
    throw "WSL executable not found: $WslExe"
}

$Runner = "$LinuxProjectPath/scripts/weekly_refresh_runner.py"
$PythonExe = "$LinuxProjectPath/.venv/bin/python"
& $WslExe --distribution $Distribution --user $LinuxUser --exec /usr/bin/test -f $Runner
if ($LASTEXITCODE -ne 0) {
    throw "Runner not found in WSL distribution '$Distribution': $Runner"
}
& $WslExe --distribution $Distribution --user $LinuxUser --exec /usr/bin/test -x $PythonExe
if ($LASTEXITCODE -ne 0) {
    throw "Executable virtualenv Python not found: $PythonExe"
}

$Arguments = "--distribution $Distribution --user $LinuxUser --exec $PythonExe $Runner"
$Action = New-ScheduledTaskAction -Execute $WslExe -Argument $Arguments
$At = (Get-Date).Date.AddHours(3).AddMinutes(15)
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday -At $At
$WindowsUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal -UserId $WindowsUser -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Description `
    'Read-only Aerodrome expanded FEES, BRIBES and USD research refresh in WSL, Thursdays at 03:15 Turkey time.' `
    -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null

$Registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$Info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop

Write-Output "REGISTERED: $($Registered.TaskName)"
Write-Output "Run as Windows user: $WindowsUser (must be logged in)"
Write-Output "WSL: $Distribution / $LinuxUser"
Write-Output "Scheduled: Thursdays 03:15 (Turkey Standard Time)"
Write-Output "Next scheduled run: $($Info.NextRunTime)"
Write-Output "State: $($Registered.State)"
Write-Output "Log directory in WSL: $LinuxProjectPath/data/weekly_refresh_logs"
Write-Output "Missed scheduled runs may start later when Windows is available."
Write-Output "The original seven-pool demo is not modified."
