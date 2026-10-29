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
MLFLOW_PORT="${MLFLOW_PORT:-5001}"
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
  openai) DEFAULT_JUDGE_MODEL=openai:/gpt-4.1-mini ;;
  ollama) DEFAULT_JUDGE_MODEL=ollama:/gemma4:e2b ;;
  *) die 'LLM_JUDGE_PROVIDER must be openai or ollama.' ;;
esac
DECISION_QUALITY_MODEL="${DECISION_QUALITY_MODEL:-$DEFAULT_JUDGE_MODEL}"
EVAL_SERVICE_JUDGE_MODEL="${EVAL_SERVICE_JUDGE_MODEL:-$DECISION_QUALITY_MODEL}"
OLLAMA_CONTAINER_URL="${OLLAMA_CONTAINER_URL:-http://host.containers.internal:11434}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"

podman network create --ignore "$DEV_NETWORK" >/dev/null

# Retry the entire CLI call: remote-client stream errors can escape Podman's
# registry-level retries. Cached images avoid both the registry and remote pull API.
ensure_image() {
  local image="$1" platform="${2:-}" attempt
  local attempts="${IMAGE_PULL_ATTEMPTS:-3}" delay="${IMAGE_PULL_RETRY_DELAY:-2}"
  local platform_args=()
  if [ -n "$platform" ]; then platform_args=(--platform "$platform"); fi
  if podman image exists "$image"; then
    if [ -z "$platform" ] || [ "$(podman image inspect --format '{{.Os}}/{{.Architecture}}' "$image")" = "$platform" ]; then
      return
    fi
  fi
  case "$attempts" in ''|*[!0-9]*|0) die 'IMAGE_PULL_ATTEMPTS must be a positive integer.' ;; esac
  case "$delay" in ''|*[!0-9]*) die 'IMAGE_PULL_RETRY_DELAY must be a non-negative integer (seconds).' ;; esac
  for ((attempt=1; attempt<=attempts; attempt++)); do
    echo "Pulling $image (attempt $attempt/$attempts)..."
    # Empty array expansion with nounset is not portable to macOS Bash 3.2.
    if podman pull --quiet --retry 2 --retry-delay 2s ${platform_args[@]+"${platform_args[@]}"} "$image"; then
      return
    fi
    podman info --format '{{.Host.Arch}}' >/dev/null 2>&1 || die "Podman disconnected while pulling $image. Check 'podman machine list' and restart the machine if needed."
    if [ "$attempt" -lt "$attempts" ]; then sleep "$delay"; fi
  done
  die "Could not pull $image after $attempts attempts. No pod was created. Retry 'podman pull $image'; for repeated 'unexpected EOF', see local-dev/README.md#image-pull-fails-with-unexpected-eof for a direct-VM pull using the same rootful/rootless storage."
}

fail_pod() {
  local pod="$1" message="$2"
  echo "$message" >&2
  case "$message" in
    *"address already in use"*|*"port is already allocated"*)
      case "$pod" in
        "$MLFLOW_POD_NAME") echo "MLflow host port $MLFLOW_PORT is occupied. Set MLFLOW_PORT to a free port in local-dev/.env (default 5001)." >&2 ;;
        "$POSTGRES_POD_NAME") echo "Set POSTGRES_PORT to a free host port in local-dev/.env." >&2 ;;
        "$FLUXNOVA_POD_NAME") echo "Check FLUXNOVA_PORT and OTEL_GRPC_PORT/OTEL_HTTP_PORT/OTEL_METRICS_PORT in local-dev/.env." >&2 ;;
        *) echo "Check the service's configured host ports in local-dev/.env." >&2 ;;
      esac
      ;;
  esac
  die "Could not start pod '$pod'. To recreate it after correcting the configuration: podman pod rm --force '$pod', then rerun pods-up.sh. Named volumes and artifact files are preserved."
}

# Only remove pods created by this invocation when container creation fails.
# Existing pods and volumes are never automatically removed. Once all containers
# are created, retain them on readiness failures so their logs remain available.
cleanup_new_pod() {
  local status=$?
  if [ "$status" -ne 0 ] && [ -n "${CREATING_POD:-}" ]; then
    echo "Removing newly-created incomplete pod '$CREATING_POD' (keeping volumes and artifacts)." >&2
    podman pod rm --force "$CREATING_POD" >/dev/null || echo "Cleanup failed; remove pod '$CREATING_POD' before retrying." >&2
  fi
  exit "$status"
}

create_pod() {
  local pod="$1" output
  shift
  if output="$(podman pod create --name "$pod" "$@" 2>&1)"; then
    CREATING_POD="$pod"
    trap cleanup_new_pod EXIT
  else
    fail_pod "$pod" "$output"
  fi
}

run_container() {
  local output
  if output="$(podman run --pull=never "$@" 2>&1)"; then
    echo "$output"
  else
    fail_pod "$CREATING_POD" "$output"
  fi
}

finish_pod_creation() {
  CREATING_POD=""
  trap - EXIT
}

container_environment_value() {
  local container="$1" key="$2" entry
  # Filter inside the pipe: diagnostic output must never dump API keys/passwords.
  podman container inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container" |
    while IFS= read -r entry; do
      case "$entry" in "$key="*) printf '%s\n' "${entry#*=}" ;; esac
    done
}

start_existing_pod() {
  local pod="$1" output port status experiment
  shift
  if podman pod exists "$pod"; then :; else
    status=$?
    if [ "$status" -eq 1 ]; then return 1; fi
    die "Could not inspect pod '$pod'; check 'podman info' before retrying."
  fi
  for container in "$@"; do
    podman container exists "$container" || die "Pod '$pod' is incomplete. Run: podman pod rm --force '$pod', then rerun pods-up.sh. Named volumes and artifacts are preserved."
  done
  if [ "$pod" = "$MLFLOW_POD_NAME" ]; then
    port="$(podman pod inspect --format '{{range (index .InfraConfig.PortBindings "5000/tcp")}}{{.HostPort}}{{end}}' "$pod")" || die "Could not inspect MLflow's port mapping."
    [ "$port" = "$MLFLOW_PORT" ] || die "Pod '$pod' publishes MLflow on port '${port:-none}', but MLFLOW_PORT=$MLFLOW_PORT. Recreate it with: podman pod rm --force '$pod', then rerun pods-up.sh. Data is preserved."
    experiment="$(container_environment_value mlflow EVAL_SERVICE_EXPERIMENT_NAME)" || die "Could not inspect MLflow's experiment configuration."
    [ "$experiment" = "$EVAL_SERVICE_EXPERIMENT_NAME" ] || die "MLflow's existing container uses experiment '${experiment:-unset}', but local-dev/.env requests '$EVAL_SERVICE_EXPERIMENT_NAME'. Restarting does not apply new environment values. Run: podman pod rm --force '$pod', then rerun pods-up.sh. Data is preserved."
  fi
  if output="$(podman pod start "$pod" 2>&1)"; then :; else fail_pod "$pod" "$output"; fi
  echo "Pod '$pod' started (existing configuration; recreate to apply changes)."
}

require_container_running() {
  local container="$1" state
  state="$(podman container inspect --format '{{.State.Status}} {{.State.ExitCode}}' "$container" 2>/dev/null)" ||
    die "Cannot inspect container '$container'. Check 'podman info' and 'podman ps -a'."
  if [ "${state%% *}" != running ]; then
    podman logs --tail 40 "$container" >&2 || true
    die "Container '$container' stopped during startup (state=${state%% *}, exit=${state#* }). See the startup error above or run: podman logs --tail 80 '$container'. If .env changed, recreate its pod to apply the new settings; data is preserved."
  fi
}

require_container_file() {
  local container="$1" path="$2" tries="${3:-90}" i
  for ((i=0; i<tries; i++)); do
    require_container_running "$container"
    if podman exec "$container" test -s "$path" >/dev/null 2>&1; then
      require_container_running "$container"
      return
    fi
    # The process can exit between inspect and exec. Report its logs immediately,
    # rather than repeating Podman's "container state improper" for three minutes.
    require_container_running "$container"
    sleep 2
  done
  podman logs --tail 40 "$container" >&2 || true
  die "$container did not initialize $path. Check the startup logs above."
}

wait_http() {
  local url="$1" container="$2" tries="${3:-120}"
  local i
  for ((i=0; i<tries; i++)); do
    require_container_running "$container"
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
