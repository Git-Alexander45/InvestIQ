<#
.SYNOPSIS
    Creates a verified database backup and, by default, proves it restores into a temporary database.

.DESCRIPTION
    Backups are written to the backup folder (INVESTIQ_BACKUP_DIR, default backups\) with a SHA-256
    checksum and a manifest. They are never deleted automatically; copy them to another drive or
    cloud folder you trust. -Export also writes every table as CSV files in a zip (data\exports).
#>
[CmdletBinding()]
param(
    [switch]$NoRestoreTest,
    [switch]$Export
)

. "$PSScriptRoot\common.ps1"

$values = Import-InvestIQEnv
if (Test-UsesDocker $values) { Start-Database }

Write-Step 'Backing up the database'
$cliArgs = @('backup')
if (-not $NoRestoreTest) { $cliArgs += '--restore-test' }
Invoke-Checked $InvestIQ $cliArgs $Backend

if ($Export) {
    Write-Step 'Exporting data as CSV'
    Invoke-Checked $InvestIQ @('export') $Backend
}
Write-Host 'Backup complete.' -ForegroundColor Green
