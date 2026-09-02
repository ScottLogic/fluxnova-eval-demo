#!/usr/bin/env bash
# Stops and removes the fluxnova-local pod created by fluxnova-up.sh.
# Fluxnova itself keeps no local persistent data (its state lives in postgres-local's
# "fluxnova" database — see postgres-down.sh --delete-data to remove that instead), so
# --delete-data is accepted here only for a consistent interface with the other
# *-down.sh scripts (e.g. when called from pods-down.sh --delete-data) and is a no-op.
#
# Usage:
#   ./fluxnova-down.sh                # stop/remove the pod
#   ./fluxnova-down.sh --delete-data  # same as above (no local data to delete)
set -uo pipefail

POD_NAME="${POD_NAME:-fluxnova-local}"

for arg in "$@"; do
  case "$arg" in
    --delete-data) ;; # no-op, see comment above
    -h|--help)
      echo "Usage: ./fluxnova-down.sh [--delete-data]"
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
