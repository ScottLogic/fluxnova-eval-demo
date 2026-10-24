#!/usr/bin/env bash
# Stops and removes the eval-service-local pod created by eval-service-up.sh.
# The eval-service worker keeps no local persistent data of its own (results are written
# to MLflow — see mlflow-down.sh --delete-data), so --delete-data is accepted here only
# for a consistent interface with the other *-down.sh scripts (e.g. when called from
# pods-down.sh --delete-data) and is a no-op.
#
# Usage:
#   ./eval-service-down.sh                # stop/remove the pod
#   ./eval-service-down.sh --delete-data  # same as above (no local data to delete)
set -uo pipefail

if [ -f "$(dirname "${BASH_SOURCE[0]}")/../.env" ]; then
  source "$(dirname "${BASH_SOURCE[0]}")/../.env"
fi
POD_NAME="${EVAL_SERVICE_POD_NAME:-eval-service-local}"

for arg in "$@"; do
  case "$arg" in
    --delete-data) ;; # no-op, see comment above
    -h|--help)
      echo "Usage: ./eval-service-down.sh [--delete-data]"
      exit 0
      ;;
    *)
      echo "Unknown argument: '$arg' (expected --delete-data)" >&2
      exit 1
      ;;
  esac
done

podman pod stop "$POD_NAME" 2>/dev/null || true
podman pod rm "$POD_NAME" 2>/dev/null || true

echo "Pod '$POD_NAME' stopped and removed."
