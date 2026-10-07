# Shared helpers for the macOS / Linux launchers (sourced by run-backend.sh / run-agent.sh).

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

step() { printf '\033[36m==> %s\033[0m\n' "$*"; }

download() {  # download URL to stdout with curl or wget
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1"; else wget -qO- "$1"; fi
}

# uv manages Python 3.12 and every Python dependency; it is the only thing we install for Python.
ensure_uv() {
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then return; fi
  step "Installing uv (Python package manager; user-level, no sudo)"
  download https://astral.sh/uv/install.sh | sh
  command -v uv >/dev/null 2>&1 || { echo "uv installation failed: see https://docs.astral.sh/uv/" >&2; exit 1; }
}

# Value from the environment, else from .env, else the default.
get_setting() {
  local name="$1" default="$2" value="${!1:-}"
  if [ -z "$value" ] && [ -f .env ]; then
    value="$(grep -E "^[[:space:]]*$name[[:space:]]*=" .env | tail -n 1 | cut -d= -f2- | tr -d '\r' | xargs || true)"
  fi
  echo "${value:-$default}"
}
