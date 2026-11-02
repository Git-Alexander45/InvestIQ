<#
.SYNOPSIS
    Stops the InvestIQ dashboard and API started by start.ps1. With -Database also stops the database
    container. Data is never deleted: the database volume and backups are kept.
#>
[CmdletBinding()]
param([switch]$Database)

. "$PSScriptRoot\common.ps1"

foreach ($name in @('dashboard', 'api')) {
    $p = Get-RunningProcess $name
    if ($p) {
        Write-Step "Stopping $name (process $($p.Id))"
        Stop-ProcessTree $p.Id
    }
    Remove-Item -LiteralPath (Get-PidFile $name) -ErrorAction SilentlyContinue
}

if ($Database) {
    Write-Step 'Stopping the database container (data is kept in the investiq-pgdata volume)'
    # "stop" only: never "down -v", which would delete the database volume.
    Invoke-Checked 'docker' @('compose', '-f', (Join-Path $Root 'docker-compose.yml'), 'stop', 'db')
}
Write-Host 'InvestIQ stopped.' -ForegroundColor Green
