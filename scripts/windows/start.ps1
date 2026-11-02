<#
.SYNOPSIS
    Starts InvestIQ: database (Docker), local API on 127.0.0.1:8765 and dashboard on 127.0.0.1:3000.

.DESCRIPTION
    Processes run hidden in the background; their output goes to data\logs. Running it again while
    InvestIQ is already running does nothing. Stop everything with stop.ps1.
#>
[CmdletBinding()]
param(
    [switch]$Open,        # open the dashboard in the default browser
    [switch]$ApiOnly      # start the API (and its scheduler) without the dashboard
)

. "$PSScriptRoot\common.ps1"

$values = Import-InvestIQEnv
if (-not $env:INVESTIQ_API_TOKEN) { throw 'INVESTIQ_API_TOKEN is empty in .env. Run: backend\.venv\Scripts\investiq.exe gen-token' }
if (-not (Test-Path $InvestIQ)) { throw 'The backend is not installed. Run scripts\windows\install.ps1 first.' }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (Test-UsesDocker $values) {
    Write-Step 'Database'
    Start-Database
}

$apiUrl = $env:INVESTIQ_API_URL
Write-Step "API ($apiUrl)"
if (Get-RunningProcess 'api') {
    Write-Ok 'Already running.'
} else {
    $p = Start-Process -FilePath $InvestIQ -ArgumentList 'serve' -WorkingDirectory $Backend -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir 'api.out.log') -RedirectStandardError (Join-Path $LogDir 'api.err.log')
    Save-ProcessId 'api' $p
    if (-not (Wait-Http "$apiUrl/api/health" 60)) {
        throw "The API did not start. See $(Join-Path $LogDir 'api.err.log')."
    }
    Write-Ok "Started (process $($p.Id))."
}

if (-not $ApiOnly) {
    Write-Step 'Dashboard (http://127.0.0.1:3000)'
    if (Get-RunningProcess 'dashboard') {
        Write-Ok 'Already running.'
    } else {
        $next = Join-Path $Frontend 'node_modules\next\dist\bin\next'
        if (-not (Test-Path (Join-Path $Frontend '.next\BUILD_ID'))) { throw 'The dashboard is not built. Run scripts\windows\install.ps1 first.' }
        $node = (Get-Command node).Source
        $p = Start-Process -FilePath $node -ArgumentList "`"$next`"", 'start', '-H', '127.0.0.1', '-p', '3000' `
            -WorkingDirectory $Frontend -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $LogDir 'dashboard.out.log') -RedirectStandardError (Join-Path $LogDir 'dashboard.err.log')
        Save-ProcessId 'dashboard' $p
        if (-not (Wait-Http 'http://127.0.0.1:3000/' 60)) {
            throw "The dashboard did not start. See $(Join-Path $LogDir 'dashboard.err.log')."
        }
        Write-Ok "Started (process $($p.Id))."
    }
    if ($Open) { Start-Process 'http://127.0.0.1:3000/' }
}

Write-Host ''
Write-Host 'InvestIQ is running. Dashboard: http://127.0.0.1:3000   Stop: scripts\windows\stop.ps1' -ForegroundColor Green
