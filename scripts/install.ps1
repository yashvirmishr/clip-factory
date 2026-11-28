#Requires -Version 5.1
<#
.SYNOPSIS
    First-run setup for Clip Factory.
.DESCRIPTION
    Creates .venv, installs requirements.txt, builds the web UI and (optionally)
    drops a desktop shortcut. Safe to re-run: it only fills in what is missing.
.PARAMETER SkipBuild
    Skip the npm install and UI build (useful when only the Python side changed).
.PARAMETER NoShortcut
    Do not create the desktop shortcut.
#>
param(
    [switch]$SkipBuild,
    [switch]$NoShortcut
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Treat native stderr as text instead of a terminating error (PS 7.3+).
$PSNativeCommandUseErrorActionPreference = $false

$repoRoot = Split-Path -Parent $PSScriptRoot
# OneDrive can make the default TEMP folder refuse writes, which leaves pip
# and Vite spinning. Keep temporary files inside the checkout from the start.
$tempDir = Join-Path $repoRoot '.buildtmp'
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
$env:TEMP = $tempDir
$env:TMP = $tempDir
$venvDir = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$requirements = Join-Path $repoRoot 'requirements.txt'
$webDir = Join-Path $repoRoot 'web'

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor Green
}

function Write-Hint {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor Yellow
}

# Run a native program and stop with context when it exits non-zero.
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

# Try python, then the py launcher; return the first one that reports a version.
function Get-PythonCandidate {
    $candidates = @(
        [pscustomobject]@{ Exe = 'python'; Prefix = @() },
        [pscustomobject]@{ Exe = 'py'; Prefix = @('-3') }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command -Name $candidate.Exe -ErrorAction SilentlyContinue)) {
            continue
        }
        $prefix = $candidate.Prefix
        try {
            # Ask for a bare version number so there is nothing to parse around.
            $text = & $candidate.Exe @prefix -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
            $exitCode = $LASTEXITCODE
        }
        catch {
            continue
        }
        if ($exitCode -ne 0) {
            continue
        }
        $line = @($text | Where-Object { $_ -match '^\d+\.\d+(\.\d+)?$' }) | Select-Object -First 1
        if (-not $line) {
            continue
        }
        return [pscustomobject]@{
            Exe     = $candidate.Exe
            Prefix  = $prefix
            Version = [version]$line
        }
    }
    return $null
}

function Main {
    Write-Host ""
    Write-Host "Clip Factory - first-run setup" -ForegroundColor Cyan
    Write-Host "Repository: $repoRoot"

    if (-not (Test-Path -LiteralPath $requirements)) {
        throw "Could not find requirements.txt in $repoRoot. Run this script from a Clip Factory checkout."
    }

    Write-Step "Checking Python (3.11 or newer)"
    $python = Get-PythonCandidate
    if (-not $python -or $python.Version -lt [version]"3.11") {
        $found = if ($python) { "found $($python.Version)" } else { "no python or py launcher on PATH" }
        throw "Clip Factory needs Python 3.11 or newer ($found). Install it from https://www.python.org/downloads/ (tick Add python.exe to PATH) and run this script again."
    }
    Write-Ok "Python $($python.Version) via $($python.Exe)"

    Write-Step "Checking Node (20 or newer)"
    if (-not (Get-Command -Name node -ErrorAction SilentlyContinue)) {
        throw "Node.js was not found on PATH. Install Node 20 or newer from https://nodejs.org/ and run this script again."
    }
    $nodeOutput = @(& node -p "process.versions.node" 2>$null)
    if ($LASTEXITCODE -ne 0 -or $nodeOutput.Count -eq 0) {
        throw "Could not read the Node.js version. Reinstall Node 20 or newer from https://nodejs.org/."
    }
    $nodeVersion = [version](([string]$nodeOutput[0]).Trim())
    if ($nodeVersion -lt [version]"20.0") {
        throw "Clip Factory needs Node 20 or newer (found $nodeVersion). Install a newer Node from https://nodejs.org/ and run this script again."
    }
    Write-Ok "Node $nodeVersion"

    Write-Step "Checking ffmpeg (optional)"
    if (Get-Command -Name ffmpeg -ErrorAction SilentlyContinue) {
        Write-Ok "ffmpeg found on PATH."
    }
    else {
        Write-Hint "ffmpeg is not on PATH. Clip Factory still starts, but rendering and caption burn-in need it."
        Write-Hint "Install it later (for example: winget install Gyan.FFmpeg) and reopen your terminal."
    }

    Write-Step "Preparing the Python virtual environment"
    if (Test-Path -LiteralPath $venvPython) {
        Write-Ok ".venv already exists - reusing it."
    }
    else {
        $prefix = $python.Prefix
        $venvArgs = @($prefix) + @("-m", "venv", $venvDir)
        Invoke-Native -Exe $python.Exe -Arguments $venvArgs -What "Creating .venv"
        if (-not (Test-Path -LiteralPath $venvPython)) {
            throw "The virtual environment was created but $venvPython is missing. Delete .venv and try again."
        }
        Write-Ok "Created .venv"
    }

    Write-Step "Installing Python dependencies"
    # No pip self-upgrade: it re-checks the package index even when pip is
    # current, and that check can stall for minutes on a slow network.
    Invoke-Native -Exe $venvPython -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-r", $requirements) -What "Installing requirements.txt"
    Write-Ok "Python dependencies are up to date."

    if ($SkipBuild) {
        Write-Step "Skipping the web UI (-SkipBuild)"
        Write-Hint "Run the script again without -SkipBuild before the first launch."
    }
    else {
        Write-Step "Installing and building the web UI"
        $nodeModules = Join-Path $webDir "node_modules"
        $buildTmp = $tempDir
        Push-Location -LiteralPath $webDir
        try {
            if (Test-Path -LiteralPath $nodeModules) {
                Write-Ok "node_modules already present - skipping npm ci."
            }
            else {
                Invoke-Native -Exe "npm" -Arguments @("ci") -What "npm ci"
            }

            Invoke-Native -Exe "npm" -Arguments @("run", "build") -What "npm run build"
            Write-Ok "Web UI built into web\dist."
        }
        finally {
            Pop-Location
            if (Test-Path -LiteralPath $buildTmp) {
                Remove-Item -LiteralPath $buildTmp -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }

    if ($NoShortcut) {
        Write-Step "Skipping the desktop shortcut (-NoShortcut)"
    }
    else {
        Write-Step "Creating the desktop shortcut"
        $launchCmd = Join-Path $PSScriptRoot "launch.cmd"
        $desktop = [Environment]::GetFolderPath("Desktop")
        if (-not (Test-Path -LiteralPath $launchCmd)) {
            Write-Hint "scripts\launch.cmd is missing - skipping the shortcut."
        }
        elseif (-not $desktop) {
            Write-Hint "Could not locate the Desktop folder - skipping the shortcut."
        }
        else {
            try {
                $shortcutPath = Join-Path $desktop "Clip Factory.lnk"
                $shell = New-Object -ComObject WScript.Shell
                $shortcut = $shell.CreateShortcut($shortcutPath)
                $shortcut.TargetPath = $launchCmd
                $shortcut.WorkingDirectory = $repoRoot
                $shortcut.Description = "Clip Factory"
                $iconPath = Join-Path $repoRoot "desktop\build\icon.ico"
                if (Test-Path -LiteralPath $iconPath) {
                    $shortcut.IconLocation = "$iconPath,0"
                }
                $shortcut.Save()
                Write-Ok "Shortcut created: $shortcutPath"
            }
            catch {
                Write-Hint "Could not create the desktop shortcut: $($_.Exception.Message)"
            }
        }
    }

    Write-Host ""
    Write-Host "Clip Factory is ready." -ForegroundColor Green
    Write-Host "Next steps:"
    Write-Host "  scripts\run.cmd     build the UI, serve on http://127.0.0.1:8756 and open the browser"
    Write-Host "  scripts\launch.cmd  same thing, for double-clicking or the desktop shortcut"
    Write-Host ""
    Write-Host "Re-running this script is safe - it only fills in what is missing."
}

try {
    Main
}
catch {
    Write-Host ""
    Write-Host "Setup stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Fix the problem above and re-run scripts\install.ps1 - it is safe to re-run."
    exit 1
}
