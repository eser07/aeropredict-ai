# Installs an hourly HH:15 Turkey-time local AeroPredict AI refresh task.
# Usage from WSL:
# powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w scripts/install_hourly_task.ps1)" -Distribution Ubuntu-24.04 -LinuxUser eser -LinuxProjectPath /home/eser/aeropredict-ai
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
$TaskName = 'AeroPredict AI Hourly Refresh'

$Zone = (Get-TimeZone).Id
if ($Zone -ne 'Turkey Standard Time') {
    throw "Expected Windows time zone 'Turkey Standard Time', got '$Zone'. Scheduling aborted."
}

$WslExe = Join-Path $env:WINDIR 'System32\wsl.exe'
if (-not (Test-Path -LiteralPath $WslExe)) {
    throw "WSL executable not found: $WslExe"
}

$Runner = "$LinuxProjectPath/scripts/hourly_refresh_runner.py"
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

# Task Scheduler starts an interactive wsl.exe in a visible console by default.
# A small user-local Windows Script Host launcher runs WSL with window style 0
# (hidden) and waits for exit, so the task still records WSL's real exit code.
$WScriptExe = Join-Path $env:WINDIR 'System32\wscript.exe'
if (-not (Test-Path -LiteralPath $WScriptExe)) {
    throw "Windows Script Host unavailable: $WScriptExe. Hourly task not changed."
}
$LauncherDir = Join-Path $env:LOCALAPPDATA 'AeroPredictAI'
New-Item -ItemType Directory -Path $LauncherDir -Force | Out-Null
$LauncherPath = Join-Path $LauncherDir 'hourly-refresh-hidden.vbs'
$Command = '"' + $WslExe + '" ' + $Arguments
$EscapedCommand = $Command.Replace('"', '""')
$LauncherContents = @"
Option Explicit
Dim shell, exitCode
Set shell = CreateObject("WScript.Shell")
exitCode = shell.Run("$EscapedCommand", 0, True)
WScript.Quit exitCode
"@
Set-Content -LiteralPath $LauncherPath -Value $LauncherContents -Encoding Ascii
$Action = New-ScheduledTaskAction -Execute $WScriptExe -Argument ('"' + $LauncherPath + '"')
# Start on the upcoming HH:15 boundary and repeat hourly for ten years.
# Task Scheduler's Once/repetition trigger is independent of Ubuntu cron.
$Now = Get-Date
$At = $Now.Date.AddHours($Now.Hour).AddMinutes(15)
if ($At -le $Now) { $At = $At.AddHours(1) }
$Trigger = New-ScheduledTaskTrigger -Once -At $At `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$WindowsUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal -UserId $WindowsUser -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Description `
    'Read-only Aerodrome expanded FEES, BRIBES and USD research refresh in WSL, every hour at HH:15 Turkey time.' `
    -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null

# Replace our former Thursday-only task if it was ever installed.
$OldTask = Get-ScheduledTask -TaskName 'AeroPredict AI Weekly Refresh' -ErrorAction SilentlyContinue
if ($null -ne $OldTask) {
    Unregister-ScheduledTask -TaskName 'AeroPredict AI Weekly Refresh' -Confirm:$false
    Write-Output "Removed previous Thursday-only AeroPredict AI task."
}

$Registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$Info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop

Write-Output "REGISTERED: $($Registered.TaskName)"
Write-Output "Run as Windows user: $WindowsUser (must be logged in)"
Write-Output "WSL: $Distribution / $LinuxUser"
Write-Output "Scheduled: Every hour at HH:15 (Turkey Standard Time)"
Write-Output "Next scheduled run: $($Info.NextRunTime)"
Write-Output "State: $($Registered.State)"
Write-Output "Window: Hidden (no extra WSL terminal window)"
Write-Output "Launcher: $LauncherPath"
Write-Output "Log directory in WSL: $LinuxProjectPath/data/hourly_refresh_logs"
Write-Output "Missed scheduled runs may start later when Windows is available."
Write-Output "The original seven-pool demo is not modified."
