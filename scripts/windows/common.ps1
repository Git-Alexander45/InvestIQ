# Shared helpers for the InvestIQ Windows scripts. Dot-source it: . "$PSScriptRoot\common.ps1"
# Works with Windows PowerShell 5.1 and PowerShell 7.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:EnvFile = Join-Path $Root '.env'
$script:EnvExample = Join-Path $Root '.env.example'
$script:Backend = Join-Path $Root 'backend'
$script:Frontend = Join-Path $Root 'frontend'
$script:Venv = Join-Path $Backend '.venv'
$script:Python = Join-Path $Venv 'Scripts\python.exe'
$script:InvestIQ = Join-Path $Venv 'Scripts\investiq.exe'
$script:RunDir = Join-Path $Root 'data\run'
$script:LogDir = Join-Path $Root 'data\logs'

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "    $Message" -ForegroundColor Green }
function Write-Warn2([string]$Message) { Write-Host "    $Message" -ForegroundColor Yellow }

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function New-RandomSecret([int]$Bytes = 32) {
    # URL-safe random secret (no characters that need escaping in a database URL or .env file).
    $buf = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buf) } finally { $rng.Dispose() }
    return ([Convert]::ToBase64String($buf)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Read-DotEnv([string]$Path = $script:EnvFile) {
    # Parses KEY=VALUE lines; ignores blank lines and comments. Values may be wrapped in quotes.
    $values = [ordered]@{}
    if (-not (Test-Path $Path)) { return $values }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        $key = $t.Substring(0, $i).Trim()
        $val = $t.Substring($i + 1).Trim()
        if ($val.Length -ge 2 -and (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'")))) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        $values[$key] = $val
    }
    return $values
}

function Import-InvestIQEnv {
    # Loads .env into this process only, so child processes (API, dashboard, docker compose) see it.
    if (-not (Test-Path $script:EnvFile)) {
        throw ".env not found at $($script:EnvFile). Run scripts\windows\install.ps1 first."
    }
    $values = Read-DotEnv
    foreach ($k in $values.Keys) {
        if ($values[$k] -ne '') { [Environment]::SetEnvironmentVariable($k, $values[$k], 'Process') }
    }
    if (-not $env:INVESTIQ_API_URL) {
        $apiPort = if ($values.Contains('INVESTIQ_API_PORT') -and $values['INVESTIQ_API_PORT']) { $values['INVESTIQ_API_PORT'] } else { '8765' }
        $env:INVESTIQ_API_URL = "http://127.0.0.1:$apiPort"
    }
    return $values
}

function Set-DotEnvValue([string]$Path, [string]$Key, [string]$Value) {
    # Replaces KEY=... (commented or not) or appends it. Writes UTF-8 without BOM.
    $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)
    $pattern = '^\s*#?\s*' + [regex]::Escape($Key) + '\s*='
    $done = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if (-not $done -and $lines[$i] -match $pattern) { $lines[$i] = "$Key=$Value"; $done = $true }
    }
    if (-not $done) { $lines += "$Key=$Value" }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, [string[]]$lines, $utf8)
}

function Protect-File([string]$Path) {
    # Restrict a secrets file to the current user (and SYSTEM / Administrators) on Windows.
    if ($env:OS -ne 'Windows_NT') { return }
    $user = "$env:USERDOMAIN\$env:USERNAME"
    & icacls.exe $Path /inheritance:r /grant:r "${user}:(M)" '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "Could not restrict permissions on $Path (icacls exit $LASTEXITCODE)." }
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments, [string]$WorkingDirectory = $script:Root) {
    Push-Location $WorkingDirectory
    try {
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
    } finally { Pop-Location }
}

function Test-UsesDocker([System.Collections.IDictionary]$Values) {
    return ($Values.Contains('INVESTIQ_PG_TOOLS_MODE') -and $Values['INVESTIQ_PG_TOOLS_MODE'] -eq 'docker')
}

function Start-Database {
    # Native tools write progress to stderr; with 'Stop', Windows PowerShell 5.1 would treat redirected
    # stderr as a terminating error, so failures are detected from exit codes instead.
    $ErrorActionPreference = 'Continue'
    if (-not (Test-Command 'docker')) { throw 'Docker is not installed or not on PATH. Start Docker Desktop first.' }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker is installed but not running. Start Docker Desktop and try again.' }
    Invoke-Checked 'docker' @('compose', '-f', (Join-Path $script:Root 'docker-compose.yml'), 'up', '-d', 'db')
    Write-Step 'Waiting for the database to become healthy'
    for ($i = 0; $i -lt 60; $i++) {
        $state = (& docker inspect --format '{{.State.Health.Status}}' investiq-db 2>$null)
        if ($state -eq 'healthy') { Write-Ok 'Database is healthy.'; return }
        Start-Sleep -Seconds 2
    }
    throw 'The database container did not become healthy within 2 minutes (docker logs investiq-db).'
}

function Get-PidFile([string]$Name) { return Join-Path $script:RunDir "$Name.pid" }

function Get-RunningProcess([string]$Name) {
    # Returns the recorded process only if it is still alive and is the program we started.
    $file = Get-PidFile $Name
    if (-not (Test-Path $file)) { return $null }
    $parts = (Get-Content -LiteralPath $file -Raw).Trim() -split '\|'
    $p = Get-Process -Id ([int]$parts[0]) -ErrorAction SilentlyContinue
    if ($null -eq $p) { return $null }
    if ($parts.Count -gt 1 -and $p.StartTime.ToUniversalTime().ToString('o') -ne $parts[1]) { return $null }
    return $p
}

function Save-ProcessId([string]$Name, [System.Diagnostics.Process]$Process) {
    New-Item -ItemType Directory -Force -Path $script:RunDir | Out-Null
    $stamp = $Process.StartTime.ToUniversalTime().ToString('o')
    Set-Content -LiteralPath (Get-PidFile $Name) -Value "$($Process.Id)|$stamp" -Encoding ASCII
}

function Stop-ProcessTree([int]$ProcessId) {
    if ($env:OS -eq 'Windows_NT') {
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
        foreach ($c in @($children)) { if ($c) { Stop-ProcessTree ([int]$c.ProcessId) } }
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Wait-Http([string]$Url, [int]$Seconds = 60) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -lt 500) { return $true }
        } catch { Start-Sleep -Seconds 1 }
    }
    return $false
}
