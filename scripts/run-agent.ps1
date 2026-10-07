# Starts the device agent, installing uv / Python deps if missing.
# Usage: run-agent.cmd [--webcam [INDEX] | --video FILE] [--server URL] [--device-id ID] ...

. "$PSScriptRoot\common.ps1"

Ensure-Uv

$agentArgs = @($args)
if (-not ($agentArgs -contains "--webcam" -or $agentArgs -contains "--video")) {
    $agentArgs = @("--webcam") + $agentArgs
}

Write-Step "Starting device agent (first run downloads Python + packages)"
uv run visual-memory-agent @agentArgs
exit $LASTEXITCODE
