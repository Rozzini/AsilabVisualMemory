# Starts the backend, installing whatever is missing (uv, Python deps, Ollama on request).
# Usage: run-backend.cmd [extra uvicorn args, e.g. --host 0.0.0.0 --port 8000]

. "$PSScriptRoot\common.ps1"

Ensure-Uv

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Step "Created .env from .env.example"
}

$visionUrl = Get-Setting "VISION_BASE_URL" "http://localhost:11434/v1"
if ($visionUrl -match ":11434") {
    $ollamaRoot = ($visionUrl -replace "/v1/?$", "")

    function Test-Ollama {
        try { Invoke-RestMethod "$ollamaRoot/api/version" -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
    }
    function Find-Ollama {
        $cmd = Get-Command ollama -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
        $default = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
        if (Test-Path $default) { return $default }
        return $null
    }

    if (-not (Test-Ollama)) {
        $ollama = Find-Ollama
        if (-not $ollama) {
            Write-Host ""
            Write-Host "Ollama runs the Qwen3-VL vision model locally and is not installed."
            $answer = Read-Host "Install Ollama now? [Y/n]"
            if ($answer -match "^(n|no)$") {
                Write-Host "Skipped. Install it from https://ollama.com/download, or set a hosted"
                Write-Host "VISION_BASE_URL / VISION_MODEL / VISION_API_KEY in .env (see README)."
            } else {
                Write-Step "Installing Ollama"
                if (Get-Command winget -ErrorAction SilentlyContinue) {
                    winget install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements
                } else {
                    $setup = Join-Path $env:TEMP "OllamaSetup.exe"
                    Invoke-WebRequest "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup
                    Start-Process $setup -ArgumentList "/SILENT" -Wait
                }
                $ollama = Find-Ollama
            }
        }
        if ($ollama -and -not (Test-Ollama)) {
            Write-Step "Starting Ollama"
            Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden
            for ($i = 0; $i -lt 60 -and -not (Test-Ollama); $i++) { Start-Sleep -Seconds 1 }
        }
        if (Test-Ollama) { Write-Step "Ollama is running" }
        else { Write-Step "Ollama is still starting; the backend connects to it as soon as it is up" }
    }
}

Write-Step "Starting backend (http://localhost:8000 unless --port is given; first run downloads Python + packages; the vision model downloads in the background)"
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 @args
exit $LASTEXITCODE
