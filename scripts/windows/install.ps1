<#
.SYNOPSIS
    Installs InvestIQ on this Windows computer (safe to run again: existing data and secrets are kept).

.DESCRIPTION
    1. Checks prerequisites (Python 3.12+, Node.js 20+, Docker Desktop unless -NoDocker).
    2. Creates .env from .env.example with a random database password and API token (only if .env
       does not exist yet) and restricts it to your Windows account.
    3. Starts the PostgreSQL/TimescaleDB container (bound to 127.0.0.1 only).
    4. Creates the Python environment and installs the backend.
    5. Runs database migrations (with a verified backup first when data exists) and loads the
       starter universe, portfolios and strategies.
    6. Installs and builds the dashboard.
    7. Optionally registers the daily research task (-RegisterTask).

    Nothing is purchased, no API keys are requested and nothing is exposed to the network.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -RegisterTask
#>
[CmdletBinding()]
param(
    [switch]$NoDocker,       # use an existing PostgreSQL server (set INVESTIQ_DATABASE_URL in .env yourself)
    [switch]$SkipFrontend,
    [switch]$RegisterTask,   # also register the daily research task (see register-task.ps1)
    [string]$PythonExe = ''  # explicit python.exe to create the virtual environment with
)

. "$PSScriptRoot\common.ps1"

function Find-Python {
    $ErrorActionPreference = 'Continue'  # 'py' reports a missing version on stderr; use exit codes
    if ($PythonExe) { return @($PythonExe) }
    if (Test-Command 'py') {
        & py -3.12 -c 'import sys' *> $null
        if ($LASTEXITCODE -eq 0) { return @('py', '-3.12') }
        & py -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' *> $null
        if ($LASTEXITCODE -eq 0) { return @('py', '-3') }
    }
    if (Test-Command 'python') { return @('python') }
}

# --- 1. Prerequisites ------------------------------------------------------------------------------
Write-Step 'Checking prerequisites'
$py = @(Find-Python)  # @() keeps a one-element result an array under strict mode
if ($py.Count -eq 0) { throw 'Python 3.12 or newer is required: https://www.python.org/downloads/windows/ (tick "Add to PATH").' }
$pyArgs = @()
if ($py.Count -gt 1) { $pyArgs = @($py[1..($py.Count - 1)]) }
# No double quotes inside -c: Windows PowerShell 5.1 does not escape them for native programs.
$pyVersion = "$(& $py[0] @pyArgs -c 'import sys; print(*sys.version_info[:2], sep=chr(46))')".Trim()
if ($pyVersion -notmatch '^\d+\.\d+$') { throw 'Python did not run. Install Python 3.12+ from python.org (the Microsoft Store alias is not enough).' }
if ([version]$pyVersion -lt [version]'3.12') { throw "Python 3.12 or newer is required (found $pyVersion)." }
Write-Ok "Python $pyVersion"

if (-not $SkipFrontend) {
    if (-not (Test-Command 'node')) { throw 'Node.js 20 or newer is required: https://nodejs.org/ (LTS).' }
    $nodeMajor = [int]("$(& node -p "process.versions.node.split('.')[0]")".Trim())
    if ($nodeMajor -lt 20) { throw "Node.js 20 or newer is required (found major version $nodeMajor)." }
    Write-Ok "Node.js $((& node --version).Trim())"
}
if (-not $NoDocker) {
    if (-not (Test-Command 'docker')) {
        throw 'Docker Desktop is required for the database: https://www.docker.com/products/docker-desktop/ (or use -NoDocker with your own PostgreSQL 16).'
    }
    Write-Ok ((& docker --version) -join ' ')
}

# --- 2. Configuration ------------------------------------------------------------------------------
Write-Step 'Configuration (.env)'
if (Test-Path $EnvFile) {
    Write-Ok '.env already exists: keeping it unchanged (your secrets and settings are preserved).'
} else {
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
    $dbPassword = New-RandomSecret 24
    $token = New-RandomSecret 32
    $defaults = Read-DotEnv $EnvExample
    $dbUser = $defaults['INVESTIQ_DB_USER']; $dbName = $defaults['INVESTIQ_DB_NAME']; $dbPort = $defaults['INVESTIQ_DB_PORT']
    Set-DotEnvValue $EnvFile 'INVESTIQ_DB_PASSWORD' $dbPassword
    Set-DotEnvValue $EnvFile 'INVESTIQ_DATABASE_URL' "postgresql+psycopg://${dbUser}:${dbPassword}@127.0.0.1:${dbPort}/${dbName}"
    Set-DotEnvValue $EnvFile 'INVESTIQ_API_TOKEN' $token
    if ($NoDocker) { Set-DotEnvValue $EnvFile 'INVESTIQ_PG_TOOLS_MODE' 'local' }
    Protect-File $EnvFile
    Write-Ok 'Created .env with a random database password and API token (readable by your account only).'
    if ($NoDocker) { Write-Warn2 'Edit INVESTIQ_DATABASE_URL in .env to point at your PostgreSQL server, then run this script again.' }
}
$values = Import-InvestIQEnv

# --- 3. Database -----------------------------------------------------------------------------------
if (-not $NoDocker) {
    Write-Step 'Starting the database (Docker, 127.0.0.1 only)'
    Start-Database
}

# --- 4. Backend ------------------------------------------------------------------------------------
Write-Step 'Installing the backend (Python virtual environment)'
if (-not (Test-Path $Python)) { Invoke-Checked $py[0] ($pyArgs + @('-m', 'venv', $Venv)) }
Invoke-Checked $Python @('-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip')
Invoke-Checked $Python @('-m', 'pip', 'install', '--disable-pip-version-check', '-e', "$Backend[mcp]")
Write-Ok 'Backend installed.'

# --- 5. Migrations and starter data ----------------------------------------------------------------
Write-Step 'Migrating the database and loading starter data'
# bootstrap backs up and verifies existing data before applying any migration.
Invoke-Checked $InvestIQ @('bootstrap') $Backend
Write-Ok 'Database ready.'

# --- 6. Dashboard ----------------------------------------------------------------------------------
if (-not $SkipFrontend) {
    Write-Step 'Installing and building the dashboard'
    $npm = if (Test-Command 'npm.cmd') { 'npm.cmd' } else { 'npm' }
    Invoke-Checked $npm @('ci', '--no-audit', '--no-fund') $Frontend
    Invoke-Checked $npm @('run', 'build') $Frontend
    Write-Ok 'Dashboard built.'
}

# --- 7. Scheduling ---------------------------------------------------------------------------------
if ($RegisterTask) {
    & (Join-Path $PSScriptRoot 'register-task.ps1')
}

Write-Host ''
Write-Host 'InvestIQ is installed.' -ForegroundColor Green
Write-Host '  Start:          scripts\windows\start.ps1   (then open http://127.0.0.1:3000)'
Write-Host '  Stop:           scripts\windows\stop.ps1'
Write-Host '  Daily research: scripts\windows\register-task.ps1'
Write-Host '  Backup:         scripts\windows\backup.ps1'
Write-Host ''
Write-Host 'Optional: add data provider and AI keys to .env (see docs\INSTALL.md and docs\DATA_SOURCES.md).'
Write-Host 'Without a market data key, research runs are recorded as degraded and no prices are invented.'
