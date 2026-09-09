#!/usr/bin/env bash
# Capture gen_ai.* metrics for one model run as compact JSON.
# The OTel Collector republishes cumulative metrics in Prometheus text format
# at :8889. Metrics are cumulative-since-engine-start, so we snapshot and store
# the raw gen_ai_* lines; per-run deltas are computed by diffing a before/after pair.
#
# Usage:
#   ./capture-metrics.sh <model> <phase>
#     <model>  e.g. gemma4:e2b  (used only for the filename / json field)
#     <phase>  before | after  (snapshot label)
#
# Example flow per model:
#   ./capture-metrics.sh gemma4:e2b before
#   fluxnova-run ...
#   ./capture-metrics.sh gemma4:e2b after
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

MODEL="${1:?usage: capture-metrics.sh <model> <phase>}"
PHASE="${2:?usage: capture-metrics.sh <model> <phase>}"
OTEL="${OTEL_METRICS_URL:-http://localhost:8889/metrics}"

SAFE_MODEL="${MODEL//[:\/]/_}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${SAFE_MODEL}-${PHASE}-${STAMP}.json"

# Grab the raw exposition text, keep only gen_ai_* sample lines (drop # HELP/# TYPE),
# and wrap into a JSON document with the raw lines as an array plus metadata.
RAW="$(curl -s "$OTEL" | grep '^gen_ai_' || true)"

if [ -z "$RAW" ]; then
  echo "WARNING: no gen_ai_* metrics returned from $OTEL (is the stack up? has any run happened?)" >&2
fi

# Build JSON safely with jq: feed raw text on stdin (arg list would be too long),
# slurp into lines with -R, then wrap with metadata.
printf '%s\n' "$RAW" | jq -R -s \
  --arg model "$MODEL" \
  --arg phase "$PHASE" \
  --arg stamp "$STAMP" \
  --arg source "$OTEL" \
  '{
     model: $model,
     phase: $phase,
     captured_at: $stamp,
     source: $source,
     samples: (split("\n") | map(select(length > 0)))
   }' > "$OUT"

echo "Wrote $OUT ($(echo "$RAW" | grep -c . 2>/dev/null || echo 0) gen_ai_ samples)"
