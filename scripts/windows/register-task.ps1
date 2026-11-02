<#
.SYNOPSIS
    Registers (or removes) the Windows Task Scheduler tasks that keep InvestIQ's research running.

.DESCRIPTION
    "InvestIQ Daily Research" runs run-cycle.ps1 every hour and at logon. Each run only does work
    when the cycle is due (the research time is set in the dashboard, default after the market
    close), so a computer that was off or asleep catches up on the missed day when it is next on.
    The task runs as you, only while you are logged on, and stores no password.

    -WithServer also registers "InvestIQ Server", which starts the API and dashboard at logon.

.EXAMPLE
    scripts\windows\register-task.ps1 -WithServer
    scripts\windows\register-task.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string]$At = '18:05',  # first daily check (local time); hourly checks follow
    [switch]$WithServer,
    [switch]$Unregister
)

. "$PSScriptRoot\common.ps1"

$folder = '\InvestIQ\'
$cycleTask = 'InvestIQ Daily Research'
$serverTask = 'InvestIQ Server'

if ($Unregister) {
    foreach ($name in @($cycleTask, $serverTask)) {
        if (Get-ScheduledTask -TaskPath $folder -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskPath $folder -TaskName $name -Confirm:$false
            Write-Ok "Removed '$name'."
        }
    }
    return
}

$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

function New-ScriptAction([string]$Script, [string]$Extra = '') {
    $path = Join-Path $PSScriptRoot $Script
    $arg = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$path`" $Extra".Trim()
    return New-ScheduledTaskAction -Execute $powershell -Argument $arg -WorkingDirectory $Root
}

Write-Step "Registering '$cycleTask'"
$daily = New-ScheduledTaskTrigger -Daily -At $At
$daily.Repetition = (New-ScheduledTaskTrigger -Once -At $At -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Hours 23)).Repetition
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$logon.Delay = 'PT5M'  # give Docker Desktop time to start
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3) -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskPath $folder -TaskName $cycleTask -Action (New-ScriptAction 'run-cycle.ps1') `
    -Trigger @($daily, $logon) -Settings $settings -Principal $principal -Force `
    -Description 'Runs the InvestIQ research cycle when due and catches up missed days. Research only: never trades.' | Out-Null
Write-Ok "Checks daily from $At, hourly after that, and 5 minutes after logon."

if ($WithServer) {
    Write-Step "Registering '$serverTask'"
    $logon2 = New-ScheduledTaskTrigger -AtLogOn -User $user
    $logon2.Delay = 'PT2M'
    $settings2 = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskPath $folder -TaskName $serverTask -Action (New-ScriptAction 'start.ps1') `
        -Trigger $logon2 -Settings $settings2 -Principal $principal -Force `
        -Description 'Starts the InvestIQ API and dashboard (127.0.0.1 only) at logon.' | Out-Null
    Write-Ok 'Starts 2 minutes after logon.'
}

Write-Host ''
Write-Host "Tasks are in Task Scheduler under '$folder'. Remove them with: scripts\windows\register-task.ps1 -Unregister"
