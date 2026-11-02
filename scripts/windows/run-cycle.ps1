<#
.SYNOPSIS
    Runs the daily research cycle if it is due (or catches up a missed day), then the backup check.
    This is what the scheduled task calls; it is safe to run at any time and as often as you like.

.DESCRIPTION
    The cycle only runs when the research time set in the dashboard has passed and the day has not
    completed yet. A backup is taken when the last one is older than 20 hours. Output is appended to
    data\logs\scheduled-YYYY-MM.log.
#>
[CmdletBinding()]
param([switch]$Force)  # run today's cycle again even if it already completed

. "$PSScriptRoot\common.ps1"

$values = Import-InvestIQEnv
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$log = Join-Path $LogDir ("scheduled-{0}.log" -f (Get-Date -Format 'yyyy-MM'))

function Write-Log([string]$Text) {
    Add-Content -LiteralPath $log -Value ("[{0}] {1}" -f (Get-Date -Format 's'), $Text) -Encoding UTF8
}

$ErrorActionPreference = 'Continue'  # native stderr goes to the log; failures are read from exit codes
try {
    if (Test-UsesDocker $values) { Start-Database *>> $log }
    $cliArgs = if ($Force) { @('run-cycle', '--force') } else { @('run-cycle', '--if-due') }
    Write-Log "investiq $($cliArgs -join ' ')"
    Push-Location $Backend
    try { & $InvestIQ @cliArgs *>> $log; $code = $LASTEXITCODE } finally { Pop-Location }
    Write-Log "exit code $code"
    exit $code
} catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    exit 1
}
