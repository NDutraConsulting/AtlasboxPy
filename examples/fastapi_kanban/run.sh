#!/usr/bin/env bash
# Runs the Kanban demo regardless of which directory you invoke it from.
#
# Usage:
#   ./examples/fastapi_kanban/run.sh
#   (or, from inside examples/fastapi_kanban/)  ./run.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
PORT="${PORT:-8000}"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment at $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if ! python3 -c "import fastapi, validator_gateway" >/dev/null 2>&1; then
  echo "Installing validator_gateway[fastapi] into $VENV_DIR..."
  pip install -q -e "$REPO_ROOT[fastapi]"
fi

# uvicorn needs `examples.fastapi_kanban.main:app` to be importable, which
# requires the repo root (not this script's own directory) on sys.path.
cd "$REPO_ROOT"

echo "Starting Kanban demo at http://127.0.0.1:$PORT/"
exec uvicorn examples.fastapi_kanban.main:app --reload --port "$PORT"
