#!/usr/bin/env bash
# Orchestrates the per-service *-up.sh scripts in local-dev/services/ — the four
# long-lived dev pods — starting them in the dependency order they require: postgres
# first (mlflow/fluxnova depend on it as their datasource/backend store), then mlflow,
# then fluxnova, then eval-service (which subscribes to fluxnova's external-task topic
# and scores runs against mlflow — see services/eval-service-up.sh, it needs both
# fluxnova-local and mlflow-local already running).
#
# Idempotent: safe to re-run at any time — each *-up.sh script now leaves already-running
# pods alone rather than erroring on a name clash (see their "already exists" branch).
#
# Usage (from this directory):
#   ./pods-up.sh                    # start postgres, mlflow, fluxnova, eval-service (in order)
#   ./pods-up.sh mlflow             # start only mlflow
#   ./pods-up.sh postgres fluxnova  # start only postgres and fluxnova (still in order)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Per-service scripts live in the services/ subfolder.
SERVICES_DIR="services"
# Canonical start order — also the order pods are started in when no args are given.
ALL_PODS=(postgres mlflow fluxnova eval-service)

usage() {
  cat <<EOF
Usage: ./pods-up.sh [pod ...]

Starts one or more of the local-dev pods via their respective services/*-up.sh
scripts, always in dependency order (postgres, then mlflow, then fluxnova, then
eval-service) regardless of the order given on the command line. Idempotent —
already-running pods are left untouched.

With no arguments, starts all pods: ${ALL_PODS[*]}.

Pods:
  postgres      PostgreSQL (services/postgres-up.sh)
  mlflow        MLflow tracking server (services/mlflow-up.sh)
  fluxnova      Fluxnova engine + OTel Collector (services/fluxnova-up.sh)
  eval-service  Eval-service worker (services/eval-service-up.sh)

Examples:
  ./pods-up.sh                 # start all four, in order
  ./pods-up.sh mlflow          # start only mlflow
  ./pods-up.sh postgres mlflow # start postgres then mlflow
EOF
}

if [ "$#" -gt 0 ] && { [ "$1" = "-h" ] || [ "$1" = "--help" ]; }; then
  usage
  exit 0
fi

if [ "$#" -eq 0 ]; then
  selected=("${ALL_PODS[@]}")
else
  selected=("$@")
  for pod in "${selected[@]}"; do
    case "$pod" in
      postgres|mlflow|fluxnova|eval-service) ;;
      *)
        echo "Unknown pod: '$pod' (expected one of: ${ALL_PODS[*]})" >&2
        usage >&2
        exit 1
        ;;
    esac
  done
fi

for pod in "${ALL_PODS[@]}"; do
  for sel in "${selected[@]}"; do
    if [ "$sel" = "$pod" ]; then
      echo "=== ${pod} ==="
      "./${SERVICES_DIR}/${pod}-up.sh"
      echo
      break
    fi
  done
done

echo "Done."
