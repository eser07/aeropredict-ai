# Register a hidden AeroPredict AI web-dashboard task for Windows user logon.
# Usage in the project's WSL shell:
# powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w scripts/install_dashboard_autostart.ps1)" -Distribution Ubuntu-24.04 -LinuxUser eser -LinuxProjectPath /home/eser/aeropredict-ai
#
# Keeps the existing hourly data-refresh task intact.
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
$TaskName = 'AeroPredict AI Dashboard Autostart'
$WslExe = Join-Path $env:WINDIR 'System32\wsl.exe'
$WScriptExe = Join-Path $env:WINDIR 'System32\wscript.exe'
if (-not (Test-Path -LiteralPath $WslExe)) {
    throw "WSL executable not found: $WslExe"
}
if (-not (Test-Path -LiteralPath $WScriptExe)) {
    throw "Windows Script Host unavailable; cannot create a hidden task."
}

$Runner = "$LinuxProjectPath/scripts/dashboard_autostart_runner.py"
$PythonExe = "$LinuxProjectPath/.venv/bin/python"
$Server = "$LinuxProjectPath/scripts/serve_dashboard.py"
& $WslExe --distribution $Distribution --user $LinuxUser --exec /usr/bin/test -f $Runner
if ($LASTEXITCODE -ne 0) {
    throw "Dashboard supervisor not found: $Runner"
}
& $WslExe --distribution $Distribution --user $LinuxUser --exec /usr/bin/test -x $PythonExe
if ($LASTEXITCODE -ne 0) {
    throw "Python virtual environment not found: $PythonExe"
}
& $WslExe --distribution $Distribution --user $LinuxUser --exec /usr/bin/test -f $Server
if ($LASTEXITCODE -ne 0) {
    throw "Dashboard server not found: $Server"
}

# A hidden launcher keeps wsl.exe and its long-running web-server task
# invisible while allowing Task Scheduler to track its lifetime and exit code.
$LauncherDir = Join-Path $env:LOCALAPPDATA 'AeroPredictAI'
New-Item -ItemType Directory -Path $LauncherDir -Force | Out-Null
$LauncherPath = Join-Path $LauncherDir 'dashboard-autostart-hidden.vbs'
$Arguments = "--distribution $Distribution --user $LinuxUser --exec $PythonExe $Runner"
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

$WindowsUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Action = New-ScheduledTaskAction -Execute $WScriptExe -Argument ('"' + $LauncherPath + '"')
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $WindowsUser
$Principal = New-ScheduledTaskPrincipal -UserId $WindowsUser -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Description `
    'Start and supervise the read-only AeroPredict AI WSL localhost dashboard after Windows user logon; keeps hourly rewards refresher separate.' `
    -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null

$Registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
Write-Output "REGISTERED: $($Registered.TaskName)"
Write-Output "Trigger: At Windows user logon ($WindowsUser)"
Write-Output "Run as WSL user: $Distribution / $LinuxUser"
Write-Output "Mode: Hidden, interactive user session; no admin or password storage"
Write-Output "Server URL: http://localhost:8765/"
Write-Output "State: $($Registered.State)"
Write-Output "Dashboard log: $LinuxProjectPath/data/dashboard_server.log"
Write-Output "Hourly data refresh task: Unchanged"
Write-Output "The task will start automatically at the next Windows login."
Write-Output "To test now, run: Start-ScheduledTask -TaskName '$TaskName'"
