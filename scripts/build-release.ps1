#Requires -Version 5.1
<#
.SYNOPSIS
    Build the Windows installer for Clip Factory.
.DESCRIPTION
    Prepares a self-contained release in three steps: build the web UI, unpack a
    portable Python runtime with the backend requirements, then package the
    Electron shell with electron-builder (NSIS, per-user install).

    The output is dist-installer\ClipFactory-Setup-<version>.exe. Nothing in
    .build-release is committed; it is rebuilt from these inputs.
.PARAMETER SkipWeb
    Reuse the existing web\dist instead of rebuilding the UI.
.PARAMETER SkipPython
    Reuse the existing .build-release\python runtime.
.PARAMETER NoInstall
    Skip npm install in desktop (use when node_modules is already current).
#>
param(
    [switch]$SkipWeb,
    [switch]$SkipPython,
    [switch]$NoInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$repoRoot = Split-Path -Parent $PSScriptRoot
$releaseDir = Join-Path $repoRoot '.build-release'
$pythonDir = Join-Path $releaseDir 'python'
$pythonExe = Join-Path $pythonDir 'python.exe'
$buildTmp = Join-Path $releaseDir 'tmp'

$pythonVersion = '3.12.10'
$pythonUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-embed-amd64.zip"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor Green
}

function Invoke-Native {
    param(
        [string]$Exe,
        [string[]]$Arguments,
        [string]$What
    )
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed with exit code $LASTEXITCODE."
    }
}

# OneDrive and synced folders can refuse writes to the default TEMP; keep every
# temporary file inside the checkout so pip and npm both work there.
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
New-Item -ItemType Directory -Path $buildTmp -Force | Out-Null
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
$env:TEMP = $buildTmp
$env:TMP = $buildTmp

try {
    if (-not $SkipWeb) {
        Write-Step "Building the web UI"
        Push-Location -LiteralPath (Join-Path $repoRoot 'web')
        try {
            Invoke-Native -Exe 'npm' -Arguments @('run', 'build') -What 'npm run build'
        }
        finally {
            Pop-Location
        }
        Write-Ok "web\dist is current."
    }

    if (-not $SkipPython) {
        if (-not (Test-Path -LiteralPath $pythonExe)) {
            Write-Step "Unpacking Python $pythonVersion (embeddable)"
            $zip = Join-Path $releaseDir 'python-embed.zip'
            if (-not (Test-Path -LiteralPath $zip)) {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest -Uri $pythonUrl -OutFile $zip -UseBasicParsing
            }
            Expand-Archive -LiteralPath $zip -DestinationPath $pythonDir -Force

            # The embeddable build disables site by default; pip needs it.
            $pth = Join-Path $pythonDir 'python312._pth'
            (Get-Content -LiteralPath $pth) -replace '^#import site$', 'import site' |
                Set-Content -LiteralPath $pth -Encoding Ascii

            $getPip = Join-Path $releaseDir 'get-pip.py'
            if (-not (Test-Path -LiteralPath $getPip)) {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getPip -UseBasicParsing
            }
            Invoke-Native -Exe $pythonExe -Arguments @($getPip, '--disable-pip-version-check', '--no-cache-dir') -What 'Bootstrapping pip'
        }
        else {
            Write-Step "Reusing the portable Python runtime"
        }

        Write-Step "Installing backend requirements into the portable runtime"
        Invoke-Native -Exe $pythonExe -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir',
            '-r', (Join-Path $repoRoot 'requirements.txt')
        ) -What 'Installing requirements'
        Write-Ok "Portable runtime ready at .build-release\python."
    }

    if (-not $SkipWeb -and -not (Test-Path -LiteralPath (Join-Path $repoRoot 'web\dist\index.html'))) {
        throw "web\dist is missing. Run without -SkipWeb."
    }

    Write-Step "Packaging the desktop app"
    Push-Location -LiteralPath (Join-Path $repoRoot 'desktop')
    try {
        if (-not $NoInstall) {
            $builder = Join-Path $repoRoot 'desktop\node_modules\electron-builder\package.json'
            if (-not (Test-Path -LiteralPath $builder)) {
                Invoke-Native -Exe 'npm' -Arguments @('install') -What 'npm install (desktop)'
            }
            else {
                Write-Ok "electron-builder is already installed."
            }
        }
        Invoke-Native -Exe 'npm' -Arguments @('run', 'dist') -What 'electron-builder'
    }
    finally {
        Pop-Location
    }

    $setup = Get-ChildItem -LiteralPath (Join-Path $repoRoot 'dist-installer') -Filter 'ClipFactory-Setup-*.exe' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($setup) {
        Write-Host ""
        Write-Host "Installer: $($setup.FullName)" -ForegroundColor Green
    }
    else {
        Write-Host ""
        Write-Host "electron-builder finished but no installer was found in dist-installer." -ForegroundColor Yellow
    }
}
finally {
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
    Remove-Item -LiteralPath $buildTmp -Recurse -Force -ErrorAction SilentlyContinue
}
