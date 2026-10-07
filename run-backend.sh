#!/usr/bin/env bash
# Starts the backend, installing whatever is missing (uv, Python deps, Ollama on request).
# Usage: bash run-backend.sh [extra uvicorn args, e.g. --host 0.0.0.0 --port 8000]

source "$(dirname "$0")/scripts/common.sh"

ensure_uv

if [ ! -f .env ]; then
  cp .env.example .env
  step "Created .env from .env.example"
fi

VISION_URL="$(get_setting VISION_BASE_URL http://localhost:11434/v1)"
if [[ "$VISION_URL" == *":11434"* ]]; then
  OLLAMA_ROOT="${VISION_URL%/v1}"
  ollama_up() { download "$OLLAMA_ROOT/api/version" >/dev/null 2>&1; }

  if ! ollama_up; then
    if ! command -v ollama >/dev/null 2>&1; then
      echo
      echo "Ollama runs the Qwen3-VL vision model locally and is not installed."
      answer="n"
      if [ -t 0 ]; then read -r -p "Install Ollama now? [Y/n] " answer; answer="${answer:-y}"; fi
      if [[ "$answer" =~ ^[Yy] ]]; then
        if [[ "$(uname -s)" == "Darwin" ]]; then
          if command -v brew >/dev/null 2>&1; then
            step "Installing Ollama with Homebrew"
            brew install ollama
          else
            echo "Please install the Ollama app from https://ollama.com/download/mac, then run this script again."
            exit 1
          fi
        else
          step "Installing Ollama (the official installer may ask for your sudo password)"
          download https://ollama.com/install.sh | sh
        fi
      else
        echo "Skipped. Install it from https://ollama.com/download, or set a hosted"
        echo "VISION_BASE_URL / VISION_MODEL / VISION_API_KEY in .env (see README)."
      fi
    fi
    if command -v ollama >/dev/null 2>&1 && ! ollama_up; then
      step "Starting Ollama"
      mkdir -p storage
      nohup ollama serve >storage/ollama.log 2>&1 &
      for _ in $(seq 1 60); do ollama_up && break; sleep 1; done
    fi
    if ollama_up; then step "Ollama is running"; else step "Ollama is not up yet; the backend connects to it as soon as it is"; fi
  fi
fi

step "Starting backend (http://localhost:8000 unless --port is given; first run downloads Python + packages; the vision model downloads in the background)"
exec uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 "$@"
