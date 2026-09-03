#!/usr/bin/env bash
# Orchestrates the per-service *-down.sh scripts in local-dev/services/ — the reverse
# of pods-up.sh's start order, since eval-service depends on fluxnova/mlflow, and those
# depend on postgres, so they should be torn down first.
#
# Idempotent: safe to re-run (or run when nothing is up) — the underlying *-down.sh
# scripts already no-op cleanly via `podman pod stop/rm ... || true`.
#
# Usage (from this directory):
#   ./pods-down.sh                    # stop/remove all pods (reverse order)
#   ./pods-down.sh mlflow             # stop/remove only mlflow
#   ./pods-down.sh --delete-data      # also delete postgres' data volume / mlflow's
#                                      # artifact files (fluxnova/eval-service have none)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Per-service scripts live in the services/ subfolder.
SERVICES_DIR="services"
ALL_PODS=(postgres mlflow fluxnova eval-service observability)
# Teardown order: the reverse of pods-up.sh's start order.
TEARDOWN_ORDER=(observability eval-service fluxnova mlflow postgres)

usage() {
  cat <<EOF
Usage: ./pods-down.sh [--delete-data] [pod ...]

Stops and removes one or more of the local-dev pods via their respective
services/*-down.sh scripts, always in reverse-dependency order (observability,
then eval-service, then fluxnova, then mlflow, then postgres) regardless of the
order given on the command line. Idempotent — safe to re-run, or run when
nothing is up.

With no pod names given, stops/removes all pods: ${ALL_PODS[*]}.

Options:
  --delete-data  Also delete persistent data: postgres' PGDATA volume and
                 mlflow's artifact files. Fluxnova, eval-service and
                 observability have no data of their own (fluxnova's state lives
                 in postgres) — the flag is a no-op for them.

Pods:
  postgres      PostgreSQL (services/postgres-down.sh)
  mlflow        MLflow tracking server (services/mlflow-down.sh)
  fluxnova      Fluxnova engine + OTel Collector (services/fluxnova-down.sh)
  eval-service  Eval-service worker (services/eval-service-down.sh)
  observability Prometheus + Grafana (services/observability-down.sh)

Examples:
  ./pods-down.sh                    # stop/remove all
  ./pods-down.sh mlflow             # stop/remove only mlflow
  ./pods-down.sh --delete-data      # stop/remove all AND wipe their data
EOF
}

DELETE_DATA=false
selected=()

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
    --delete-data) DELETE_DATA=true ;;
    postgres|mlflow|fluxnova|eval-service|observability) selected+=("$arg") ;;
    *)
      echo "Unknown argument: '$arg' (expected --delete-data or one of: ${ALL_PODS[*]})" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [ "${#selected[@]}" -eq 0 ]; then
  selected=("${ALL_PODS[@]}")
fi

for pod in "${TEARDOWN_ORDER[@]}"; do
  for sel in "${selected[@]}"; do
    if [ "$sel" = "$pod" ]; then
      echo "=== ${pod} ==="
      if [ "$DELETE_DATA" = "true" ]; then
        "./${SERVICES_DIR}/${pod}-down.sh" --delete-data
      else
        "./${SERVICES_DIR}/${pod}-down.sh"
      fi
      echo
      break
    fi
  done
done

echo "Done."
