#!/usr/bin/env bash
# Stops and removes the frontend-local pod created by frontend-up.sh.
# The frontend keeps no local persistent data of its own, so --delete-data is
# accepted here only for a consistent interface with the other *-down.sh scripts
# (e.g. when called from pods-down.sh --delete-data) and is a no-op.
#
# Usage:
#   ./frontend-down.sh                # stop/remove the pod
#   ./frontend-down.sh --delete-data  # same as above (no local data to delete)
set -uo pipefail

POD_NAME="${FRONTEND_POD_NAME:-frontend-local}"

for arg in "$@"; do
  case "$arg" in
    --delete-data) ;; # no-op, see comment above
    -h|--help)
      echo "Usage: ./frontend-down.sh [--delete-data]"
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
