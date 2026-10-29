#!/usr/bin/env bash
# Stops and removes the observability-local pod created by observability-up.sh
# (Prometheus + Grafana). Both run with ephemeral in-container storage — there is no
# persistent host data to remove, so --delete-data is accepted (for symmetry with the
# other *-down.sh scripts and pods-down.sh) but is a no-op here.
#
# Usage:
#   ./observability-down.sh                # stop/remove the pod
#   ./observability-down.sh --delete-data  # same (no persistent data to delete)
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -f ../.env ]; then source ../.env; fi
POD_NAME="${OBSERVABILITY_POD_NAME:-observability-local}"

for arg in "$@"; do
  case "$arg" in
    --delete-data) : ;;  # no-op: Prometheus/Grafana have no persistent host data here
    -h|--help)
      echo "Usage: ./observability-down.sh [--delete-data]"
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
