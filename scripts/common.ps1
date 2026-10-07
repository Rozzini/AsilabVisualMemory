# Shared helpers for the Windows launchers (dot-sourced by run-backend.ps1 / run-agent.ps1).

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# uv manages Python 3.12 and every Python dependency; it is the only thing we install for Python.
function Ensure-Uv {
    $localBin = Join-Path $env:USERPROFILE ".local\bin"
    if (Test-Path (Join-Path $localBin "uv.exe")) { $env:Path = "$localBin;$env:Path" }
    if (Get-Command uv -ErrorAction SilentlyContinue) { return }

    Write-Step "Installing uv (Python package manager; user-level, no admin rights)"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$localBin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv installation failed. Install it manually: https://docs.astral.sh/uv/"
    }
}

# Value from the environment, else from .env, else the default.
function Get-Setting($name, $default) {
    $fromEnv = [Environment]::GetEnvironmentVariable($name)
    if ($fromEnv) { return $fromEnv }
    if (Test-Path ".env") {
        $line = Select-String -Path ".env" -Pattern "^\s*$name\s*=" | Select-Object -Last 1
        if ($line) { return ($line.Line -split "=", 2)[1].Trim() }
    }
    return $default
}
