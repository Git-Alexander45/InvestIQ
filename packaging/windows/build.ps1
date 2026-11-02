<#
.SYNOPSIS
    Builds InvestIQ-Setup.exe on Windows: dashboard (Next.js standalone), bundled Node.js,
    PyInstaller app folder, then the Inno Setup installer in packaging\windows\output.
    Needs Python 3.12+, Node.js 20+ and Inno Setup 6 (ISCC.exe). Used by the GitHub Actions workflow.
#>
[CmdletBinding()]
param([string]$NodeVersion = '22.20.0')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$repo = (Resolve-Path (Join-Path $here '..\..')).Path
$build = Join-Path $here 'build'

function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

Remove-Item -Recurse -Force $build, (Join-Path $here 'dist'), (Join-Path $here 'output') -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $build | Out-Null

Write-Host '==> Dashboard'
Push-Location (Join-Path $repo 'frontend')
try {
    Invoke-Native 'npm.cmd' @('ci', '--no-audit', '--no-fund')
    Invoke-Native 'npm.cmd' @('run', 'build')
} finally { Pop-Location }
$standalone = Join-Path $repo 'frontend\.next\standalone'
Copy-Item -Recurse $standalone (Join-Path $build 'dashboard')
Copy-Item -Recurse (Join-Path $repo 'frontend\.next\static') (Join-Path $build 'dashboard\.next\static')
if (Test-Path (Join-Path $repo 'frontend\public')) { Copy-Item -Recurse (Join-Path $repo 'frontend\public') (Join-Path $build 'dashboard\public') }

Write-Host "==> Node.js $NodeVersion"
$zip = Join-Path $build 'node.zip'
$base = "https://nodejs.org/dist/v$NodeVersion"
Invoke-WebRequest -UseBasicParsing "$base/node-v$NodeVersion-win-x64.zip" -OutFile $zip
$sums = (Invoke-WebRequest -UseBasicParsing "$base/SHASUMS256.txt").Content
$expected = ($sums -split "`n" | Where-Object { $_ -match "node-v$NodeVersion-win-x64\.zip$" }) -replace '\s+.*$', ''
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if (-not $expected -or $actual -ne $expected.Trim().ToLower()) { throw "Node.js download checksum mismatch ($actual vs $expected)" }
Expand-Archive $zip -DestinationPath $build
New-Item -ItemType Directory -Force -Path (Join-Path $build 'node') | Out-Null
Copy-Item (Join-Path $build "node-v$NodeVersion-win-x64\node.exe") (Join-Path $build 'node\node.exe')
Copy-Item (Join-Path $build "node-v$NodeVersion-win-x64\LICENSE") (Join-Path $build 'node\LICENSE')
Remove-Item -Recurse -Force $zip, (Join-Path $build "node-v$NodeVersion-win-x64")

Write-Host '==> Python app (PyInstaller)'
# PyInstaller's prebuilt launcher is shared by many unrelated programs, which makes antivirus tools
# flag it; compiling the launcher from source for InvestIQ avoids most of those false positives.
$env:PYINSTALLER_COMPILE_BOOTLOADER = '1'
Invoke-Native 'python' @('-m', 'pip', 'install', '--disable-pip-version-check', (Join-Path $repo 'backend'))
Invoke-Native 'python' @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-binary', 'pyinstaller', '--no-cache-dir', 'pyinstaller==6.16.0')
Push-Location $here
try { Invoke-Native 'python' @('-m', 'PyInstaller', '--noconfirm', '--clean', 'investiq.spec') } finally { Pop-Location }

Write-Host '==> Installer (Inno Setup)'
$version = (& python -c 'import investiq; print(investiq.__version__)').Trim()
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php' }
Push-Location $here
try { Invoke-Native $iscc @("/DAppVersion=$version", 'InvestIQ.iss') } finally { Pop-Location }
$sums = foreach ($f in @((Join-Path $here 'output\InvestIQ-Setup.exe'), (Join-Path $here 'dist\InvestIQ\InvestIQ.exe'), (Join-Path $here 'dist\InvestIQ\InvestIQ-Background.exe'))) {
    '{0}  {1}' -f (Get-FileHash $f -Algorithm SHA256).Hash, (Split-Path $f -Leaf)
}
$sums | Set-Content -Encoding ASCII (Join-Path $here 'output\SHA256SUMS.txt')
$sums | ForEach-Object { Write-Host "SHA-256 $_" }
Write-Host "Built $(Join-Path $here 'output\InvestIQ-Setup.exe')" -ForegroundColor Green
