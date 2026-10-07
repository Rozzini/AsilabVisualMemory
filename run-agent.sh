#!/usr/bin/env bash
# Starts the device agent, installing uv / Python deps if missing.
# Usage: bash run-agent.sh [--webcam [INDEX] | --video FILE] [--server URL] [--device-id ID] ...

source "$(dirname "$0")/scripts/common.sh"

ensure_uv

case " $* " in
  *" --webcam"*|*" --video "*) ;;
  *) set -- --webcam "$@" ;;
esac

step "Starting device agent (first run downloads Python + packages)"
exec uv run visual-memory-agent "$@"
