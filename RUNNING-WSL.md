# Running the stack on WSL (rootless Podman)

> An **alternative** local-run walkthrough to the Windows / Git Bash flow in [README.md](README.md).
> This one covers **WSL with rootless (user-side) Podman**, and captures the few gotchas hit when
> bringing the Postgres-backed stack up from a fresh checkout. A colleague is drafting a separate
> alternative guide too, so this lives as its own file rather than being folded into the README.

## Assumptions

- A WSL distro with **Podman** (`podman --version`). These instructions were written against a
  **rootless (user-side) Podman** setup — that's optional, not required, but it's what the commands
  below assume. With rootless Podman on Linux/WSL there's no `podman machine init/start`, Podman runs
  directly, and `localhost:5000` / `localhost:8080` / `localhost:5432` work without any VM-IP fallback.
- **Python 3.11+** (and [uv](https://docs.astral.sh/uv/) or plain `venv`/`pip`) for the harness.
- **[Ollama](https://ollama.com)** running in the same WSL distro, reachable from containers at
  `host.containers.internal:11434`. This setup runs **`gemma4:e2b` for both the agent and the judge**
  (`ollama pull gemma4:e2b`) — see [Models](#models) for where to point each. (The upstream defaults
  are `llama3.1` agent / `llama3.2` judge; you can skip those pulls if you're only using gemma.)
- The Fluxnova engine image — pull the public one: `podman pull ghcr.io/dogle-scottlogic/fluxnova-edd-platform:1.0.0`
  and make sure `local-dev/.env`'s `FLUXNOVA_IMAGE` points at it.

## Models

This setup runs a single small model, **`gemma4:e2b`**, for *both* roles (`ollama pull gemma4:e2b`).
There are three places to point at it:

- **Agent** (the tool-calling loop) — in the BPMN `agent:config` near line 10 of
  [bpmn/loan-assesment.bpmn](bpmn/loan-assesment.bpmn) (and
  [bpmn/loan-assesment-eval.bpmn](bpmn/loan-assesment-eval.bpmn)):
  `<agent:config provider="ollama" model="gemma4:e2b" ...>`. `fluxnova-run` re-deploys the BPMN, so no
  rebuild is needed. The agent model must support Ollama tool calling — confirm with
  `ollama show gemma4:e2b` (look for `tools` under Capabilities).
- **Judge, offline (`mlflow-eval`)** — set `_NATIVE_JUDGE_MODEL` / `_JUDGE_MODEL` in
  [harness/src/mlflow_eval/main.py](harness/src/mlflow_eval/main.py) to `ollama:/gemma4:e2b`.
- **Judge, online (`eval-service-worker`)** — repoint the `fluxnova-judge` MLflow AI Gateway endpoint
  at `gemma4:e2b`.

## Gotchas to handle first

These bit me on a clean checkout — handle them before bringing anything up.

> Minor, being fixed upstream: if a `./*.sh` fails with **exit code 126** (`is not an executable file`),
> the scripts just lack the executable bit — `chmod +x local-dev/*.sh local-dev/postgres-init/*.sh`.

> Being fixed upstream (PR #3): on PostgreSQL 15+, `postgres-init/init.sh`'s two `GRANT ALL ON SCHEMA
> public` statements use `psql -c`, which doesn't do `:"var"` interpolation, so they error on first
> init (`syntax error at or near ":"`) and the `mlflow`/`fluxnova` roles can't create tables. The fix
> moves them to heredocs. If you hit it before that lands, apply the change locally, then
> `./postgres-down.sh && podman volume rm postgres-local-data` and re-run `postgres-up.sh`.

### 1. (If present) the `userlib` bind-mount in `fluxnova-up.sh`

The current `fluxnova-up.sh` in this repo has **no** `userlib` mount, so there's nothing to do here.
But if you're on a version that bind-mounts a host `userlib` into
`/fluxnova/configuration/userlib`, **comment that `-v ...userlib:ro` line out** when running from the
published GHCR image: the OTel/agentic plugin JARs are already baked into the image, and mounting an
empty/absent host dir over them shadows the bundled JARs and breaks startup with a
`NoClassDefFoundError` on OpenTelemetry classes. Keep the mount only if you're actively iterating on
plugin JARs and pointing it at a fully populated `userlib`. Leave the tracked script unchanged —
just comment locally.

## Python environment (uv)

The harness (`fluxnova-run`, `mlflow-eval`, etc.) runs on the host in a venv under `harness/.venv`.

```bash
cd harness
uv venv                              # creates .venv (add --python 3.11 to pin the interpreter)

# Install ALL THREE local packages in ONE command.
uv pip install -e ".[dev]" -e "../fluxnova-mlflow-dataset[dev]" -e "../fluxnova-runner[dev]"
```

> **Install all three together — this is not optional.** `harness`, `fluxnova-mlflow-dataset`, and
> `fluxnova-runner` depend on each other and none are published to PyPI, so uv has to resolve them in
> a single pass. Running just `uv pip install -e ".[dev]"` fails with
> *"fluxnova-mlflow-dataset was not found in the package registry"* because it tries to fetch the
> siblings remotely instead of using the local checkouts.

Notes:

- `uv pip install` does **not** need the venv activated — uv auto-detects `.venv` in the current
  directory. Activation (`source .venv/bin/activate`) only matters for calling the console
  scripts directly; otherwise use `uv run <script> ...` from `harness/`.
- This installs the console scripts: `fluxnova-run`, `fluxnova-run-mock-workers`, `mlflow-eval`,
  `mlflow-judges`, `eval-service-worker`, and `deep-eval` (deprecated).

## Bring the stack up (order matters)

Postgres backs **both** MLflow and Fluxnova, so it must start first.

```bash
cd local-dev

./postgres-up.sh            # PostgreSQL — start FIRST (mlflow + fluxnova databases)
MLFLOW_OPEN_BROWSER=false ./mlflow-up.sh   # MLflow tracking server + UI (drop the env var to auto-open the browser)
./fluxnova-up.sh            # Fluxnova engine + OTel Collector
```

Endpoints once up:

- Postgres: `localhost:5432` (sibling pods reach it as `postgres-local:5432`)
- MLflow UI: `http://localhost:5000`
- Fluxnova REST: `http://localhost:8080/engine-rest`

### If a pod name is "in use"

Stale pods from a previous session block a fresh `*-up.sh` with e.g.
`Error: adding pod to state: name "mlflow-local" is in use: pod already exists`. Bring the matching
pod down first, then up again:

```bash
./mlflow-down.sh && MLFLOW_OPEN_BROWSER=false ./mlflow-up.sh
./fluxnova-down.sh && ./fluxnova-up.sh
```

### Note: Postgres readiness can log a false-positive warning

On a first run `postgres-up.sh` may print *"PostgreSQL doesn't seem to be responding yet"* while the
container is still doing first-time init — it usually is fine a second or two later. Confirm with the
logs (see below) rather than trusting the warning.

## Verify

```bash
# all three pods Running
podman pod ps

# Postgres init ran cleanly (expect CREATE DATABASE / CREATE ROLE / GRANT lines, no ERROR)
podman logs postgres 2>&1 | grep -iE "ERROR|CREATE DATABASE|CREATE ROLE|GRANT|ready to accept"

# MLflow up and connected to Postgres
curl -sf http://localhost:5000/version

# Fluxnova booted and using the Postgres datasource
podman logs fluxnova 2>&1 | grep -iE "HikariPool|activiti.postgres|Tomcat started|ERROR"
curl -sf http://localhost:8080/engine-rest/engine        # -> [{"name":"default"}]

# Fluxnova created its schema in the fluxnova database (~49 tables)
podman exec postgres psql -U postgres -d fluxnova -tc \
  "select count(*) from information_schema.tables where table_schema='public';"
```

## Tear down

Reverse order; Postgres data persists in the `postgres-local-data` volume across `postgres-down.sh`.

```bash
cd local-dev
./fluxnova-down.sh
./mlflow-down.sh
./postgres-down.sh

# to also wipe Postgres data (forces init.sh to re-run next time):
# podman volume rm postgres-local-data
```
