#!/usr/bin/env bash
# First-time setup for the shared host virtual environment.
#
# Creates one venv under `.venv` at the repo root and installs all five of this
# repo's local Python packages editable into it.
#
# Idempotent: safe to re-run — reuses an existing `.venv` and lets pip skip
# already-satisfied requirements.
#
# Usage (from anywhere):
#   ./setup.sh                 # create .venv and install all packages
#
# Override the interpreter used to create the venv (must be Python 3.11+):
#   PYTHON=python3.11 ./setup.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -z "${PYTHON:-}" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  done
fi
if [ -z "${PYTHON:-}" ] || ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo 'Python 3.11+ is required. Install it or run PYTHON=python3.11 ./setup.sh.' >&2
  exit 1
fi
VENV_DIR=".venv"

if [ -d "$VENV_DIR" ]; then
  echo "=== Reusing existing $VENV_DIR ==="
else
  echo "=== Creating $VENV_DIR with '$PYTHON' ==="
  "$PYTHON" -m venv "$VENV_DIR"
fi

# The venv's Python lives in Scripts/ on Windows (Git Bash) and bin/ elsewhere.
if [ -x "$VENV_DIR/Scripts/python.exe" ]; then
  VENV_PY="$VENV_DIR/Scripts/python.exe"
  ACTIVATE="$VENV_DIR/Scripts/activate"
else
  VENV_PY="$VENV_DIR/bin/python"
  ACTIVATE="$VENV_DIR/bin/activate"
fi

"$VENV_PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
  echo 'The existing .venv requires Python 3.11+. Recreate it with a supported interpreter.' >&2
  exit 1
}
"$VENV_PY" -m pip --version >/dev/null 2>&1 || "$VENV_PY" -m ensurepip --upgrade

echo "=== Upgrading pip ==="
"$VENV_PY" -m pip install --upgrade pip

echo "=== Installing editable packages ==="
"$VENV_PY" -m pip install \
  -e "fluxnova-mlflow-dataset[dev]" \
  -e "fluxnova-runner[dev]" \
  -e "eval-service-worker[dev]" \
  -e "eval-trace-listener[dev]" \
  -e "ui-api[dev]"

echo "=== Installing regression suite's extra dependencies ==="
"$VENV_PY" -m pip install -r regression/requirements.txt

echo
echo "Done. Activate the environment with:"
echo "  source $ACTIVATE"
