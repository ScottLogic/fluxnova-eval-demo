#!/usr/bin/env bash
# First-time setup for the shared host virtual environment.
#
# Creates one venv under `.venv` at the repo root and installs all three of this
# repo's local Python packages editable into it.
#
# Idempotent: safe to re-run — reuses an existing `.venv` and lets pip skip
# already-satisfied requirements.
#
# Usage (from anywhere):
#   ./setup.sh                 # create .venv and install the three packages
#
# Override the interpreter used to create the venv (must be Python 3.11+):
#   PYTHON=python3.11 ./setup.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON="${PYTHON:-python}"
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

echo "=== Upgrading pip ==="
"$VENV_PY" -m pip install --upgrade pip

echo "=== Installing editable packages ==="
"$VENV_PY" -m pip install \
  -e "fluxnova-mlflow-dataset[dev]" \
  -e "fluxnova-runner[dev]"

echo
echo "Done. Activate the environment with:"
echo "  source $ACTIVATE"
