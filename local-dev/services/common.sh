#!/usr/bin/env bash
# Shared by the up scripts; compatible with macOS Bash 3.2 and Windows Git Bash.
LOCAL_DEV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && { pwd -W 2>/dev/null || pwd; })"
REPO_ROOT="$(cd "$LOCAL_DEV_DIR/.." && { pwd -W 2>/dev/null || pwd; })"
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

if [ -f "$LOCAL_DEV_DIR/.env" ]; then
  set -a
  source "$LOCAL_DEV_DIR/.env"
  set +a
fi

die() { echo "Error: $*" >&2; exit 1; }
command -v podman >/dev/null 2>&1 || die 'Install Podman first.'
command -v curl >/dev/null 2>&1 || die 'curl is required.'
podman info --format '{{.Host.Arch}}' >/dev/null 2>&1 || die 'Podman is unavailable. On macOS/Windows run: podman machine start'

DEV_NETWORK="${DEV_NETWORK:-fluxnova-dev}"
# Preserve the Windows host-network workaround unless explicitly overridden.
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) DEFAULT_NETWORK_MODE=host ;; *) DEFAULT_NETWORK_MODE=bridge ;; esac
DEV_NETWORK_MODE="${DEV_NETWORK_MODE:-$DEFAULT_NETWORK_MODE}"
case "$DEV_NETWORK_MODE" in bridge|host) ;; *) die 'DEV_NETWORK_MODE must be bridge or host.' ;; esac
POSTGRES_POD_NAME="${POSTGRES_POD_NAME:-postgres-local}"
FLUXNOVA_POD_NAME="${FLUXNOVA_POD_NAME:-${POD_NAME:-fluxnova-local}}"
MLFLOW_POD_NAME="${MLFLOW_POD_NAME:-mlflow-local}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
MLFLOW_PORT="${MLFLOW_PORT:-5000}"
FLUXNOVA_PORT="${FLUXNOVA_PORT:-8080}"
OTEL_METRICS_PORT="${OTEL_METRICS_PORT:-8889}"
OTEL_GRPC_PORT="${OTEL_GRPC_PORT:-4317}"
OTEL_HTTP_PORT="${OTEL_HTTP_PORT:-4318}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"
MLFLOW_RUNTIME_VOLUME="${MLFLOW_RUNTIME_VOLUME:-mlflow-local-runtime}"
EVAL_SERVICE_EXPERIMENT_NAME="${EVAL_SERVICE_EXPERIMENT_NAME:-fluxnova-loanAssessmentEvalProcess}"
LLM_JUDGE_PROVIDER="${LLM_JUDGE_PROVIDER:-openai}"
case "$LLM_JUDGE_PROVIDER" in
  openai) DEFAULT_JUDGE_MODEL=openai:/gpt-4o-mini ;;
  ollama) DEFAULT_JUDGE_MODEL=ollama:/gemma4:e2b ;;
  *) die 'LLM_JUDGE_PROVIDER must be openai or ollama.' ;;
esac
EVAL_SERVICE_JUDGE_MODEL="${EVAL_SERVICE_JUDGE_MODEL:-$DEFAULT_JUDGE_MODEL}"
OLLAMA_CONTAINER_URL="${OLLAMA_CONTAINER_URL:-http://host.containers.internal:11434}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"

podman network create --ignore "$DEV_NETWORK" >/dev/null

start_existing_pod() {
  local pod="$1"
  shift
  if ! podman pod exists "$pod"; then return 1; fi
  for container in "$@"; do
    podman container exists "$container" || die "Pod '$pod' is incomplete. Remove it with its down script and retry."
  done
  podman pod start "$pod" >/dev/null || die "Could not start pod '$pod'."
  echo "Pod '$pod' started (existing configuration; recreate to apply changes)."
}

wait_http() {
  local url="$1" container="$2" tries="${3:-120}"
  local i
  for ((i=0; i<tries; i++)); do
    if curl -fs -o /dev/null --max-time 2 "$url"; then return 0; fi
    sleep 2
  done
  return 1
}

require_http() {
  local url="$1" container="$2"
  READY_URL="$url"
  if wait_http "$url" "$container"; then return; fi
  # Keep the existing WSL relay fallback, using tools also available in Git Bash.
  local ip=""
  if command -v wsl.exe >/dev/null 2>&1; then
    ip="$(wsl.exe -d podman-machine-default -- ip -4 addr show eth0 2>/dev/null | grep -Eo 'inet [0-9.]+' | cut -d ' ' -f 2 || true)"
  fi
  if [ -n "$ip" ]; then
    READY_URL="${url/localhost/$ip}"
    if wait_http "$READY_URL" "$container" 10; then return; fi
  fi
  podman logs --tail 40 "$container" >&2 || true
  die "$container did not become ready at $url. See podman logs $container."
}

open_browser() {
  if command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$1" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then open "$1" || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
  fi
}
