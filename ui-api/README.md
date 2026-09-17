# ui-api

FastAPI backend for the demo UI (`frontend/`). There's no HTTP API for regression, the BPMN runner, or the eval
services elsewhere in this repo — to keep those core folders (`regression/`, `fluxnova-runner/`,
`eval-trace-listener/`, `eval-service-worker/`) purely about *how you'd build this for real* rather than cluttered
with UI-only plumbing, this API lives on its own and wraps them as a library/CLI instead of embedding API code inside
them. See `UI_PROPOSAL.md` at the repo root for the full plan.

One router per concern: `regression.py`, `workflow.py`, `evals.py` (all under `src/ui_api/routers/`, currently
empty — see the proposal's steps 5, 7-9 for what fills them in).

## Run locally

```bash
cd ui-api
pip install -e ".[dev]"
ui-api                    # serves on http://127.0.0.1:8090
UI_API_PORT=8091 ui-api   # override host/port via UI_API_HOST / UI_API_PORT env vars, or --host/--port flags
```

CORS is open to the Vite dev server's origin (`http://localhost:5173`, see `frontend/vite.config.ts`) by default —
override with a comma-separated `UI_API_CORS_ORIGINS`.

```bash
curl http://127.0.0.1:8090/health   # {"status": "ok"}
```

## Tests

```bash
pytest
```
