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
  `host.containers.internal:11434`. This setup runs **`gemma4:e2b` for the agent (and the offline
  `mlflow-eval` judge) and `qwen2.5:1.5b` for the online judge**
  (`ollama pull gemma4:e2b && ollama pull qwen2.5:1.5b`) — see [Models](#models) for where to point each. (The upstream
  defaults are `llama3.1` agent / `llama3.2` judge.)
- The Fluxnova engine image — pull the public one: `podman pull ghcr.io/dogle-scottlogic/fluxnova-edd-platform:1.0.0`
  and make sure `local-dev/.env`'s `FLUXNOVA_IMAGE` points at it.

## Models

This setup runs **`gemma4:e2b`** for the agent and the offline judge, and **`qwen2.5:1.5b`** for the online judge
(`ollama pull gemma4:e2b && ollama pull qwen2.5:1.5b`). There are three places to point them:

- **Agent** (the tool-calling loop) — in the BPMN `agent:config` near line 10 of
  [bpmn/loan-assesment.bpmn](bpmn/loan-assesment.bpmn) (and
  [bpmn/loan-assesment-eval.bpmn](bpmn/loan-assesment-eval.bpmn)):
  `<agent:config provider="ollama" model="gemma4:e2b" ...>`. `fluxnova-run` re-deploys the BPMN, so no
  rebuild is needed. The agent model must support Ollama tool calling — confirm with
  `ollama show gemma4:e2b` (look for `tools` under Capabilities).
- **Judge, offline (`mlflow-eval`)** — set `_NATIVE_JUDGE_MODEL` / `_JUDGE_MODEL` in
  [fluxnova-mlflow-dataset/src/fluxnova_mlflow_dataset/scorers.py](fluxnova-mlflow-dataset/src/fluxnova_mlflow_dataset/scorers.py)
  to `ollama:/gemma4:e2b`.
- **Judge, online (`eval-service-worker`)** — repoint the `fluxnova-judge` MLflow AI Gateway endpoint
  at `qwen2.5:1.5b`. The endpoint's model is stored in MLflow's Postgres, not the repo — see
  [local-dev/README.md](local-dev/README.md).

## Gotcha to watch for

### (If present) the `userlib` bind-mount in `fluxnova-up.sh`

The current `local-dev/services/fluxnova-up.sh` in this repo has **no** `userlib` mount, so there's
nothing to do here.
But if you're on a version that bind-mounts a host `userlib` into
`/fluxnova/configuration/userlib`, **comment that `-v ...userlib:ro` line out** when running from the
published GHCR image: the OTel/agentic plugin JARs are already baked into the image, and mounting an
empty/absent host dir over them shadows the bundled JARs and breaks startup with a
`NoClassDefFoundError` on OpenTelemetry classes. Keep the mount only if you're actively iterating on
plugin JARs and pointing it at a fully populated `userlib`. Leave the tracked script unchanged —
just comment locally.

## Python environment (uv)

The harness (`fluxnova-run`, `mlflow-eval`, etc.) runs on the host in a venv under `.venv` at the repo root.

```bash
uv venv                              # creates .venv (add --python 3.11 to pin the interpreter)

# Install ALL THREE local packages in ONE command.
uv pip install -e "harness[dev]" -e "fluxnova-mlflow-dataset[dev]" -e "fluxnova-runner[dev]"
```

> **Install all three together — this is not optional.** `harness`, `fluxnova-mlflow-dataset`, and
> `fluxnova-runner` depend on each other and none are published to PyPI, so uv has to resolve them in
> a single pass. Running just `uv pip install -e ".[dev]"` fails with
> *"fluxnova-mlflow-dataset was not found in the package registry"* because it tries to fetch the
> siblings remotely instead of using the local checkouts.

Notes:

- `uv pip install` does **not** need the venv activated — uv auto-detects `.venv` in the current
  directory. Activation (`source .venv/bin/activate`) only matters for calling the console
  scripts directly; otherwise use `uv run <script> ...` from the repo root.
- This installs the console scripts: `fluxnova-run`, `fluxnova-run-mock-workers`, `mlflow-eval`,
  `mlflow-judges`, `eval-service-worker`, and `deep-eval` (deprecated).

## Bring the stack up (order matters)

Postgres backs **both** MLflow and Fluxnova, so it must start first. `pods-up.sh` handles the ordering
(postgres → mlflow → fluxnova) for you and is idempotent — already-running pods are left alone.

```bash
cd local-dev
MLFLOW_OPEN_BROWSER=false ./pods-up.sh postgres mlflow fluxnova
```

- Bare `./pods-up.sh` (no args) also starts the optional `eval-service` worker, which needs the
  MLflow AI Gateway judge endpoint configured — omit it here for the core stack.
- Drop `MLFLOW_OPEN_BROWSER=false` to auto-open the MLflow UI in your browser.
- To start one service on its own, call it directly, e.g. `./services/mlflow-up.sh`.

### Alternative: one `podman compose` file

If you'd rather not use the `pods-up.sh`/`pods-down.sh` scripts, `local-dev/compose.yaml` brings up the **same**
stack from a single file, reusing the identical `.env`, `postgres/init.sh`, `default.yml`, and
`otel-collector-config.yaml` (so nothing here has to change). It's an alternative, not a replacement — use whichever
you prefer, but not both at once. On rootless Podman this needs a compose provider (`podman compose`, backed by
`podman-compose`).

```bash
cd local-dev
podman compose up -d                    # core stack: postgres, mlflow, otel-collector, fluxnova
podman compose --profile eval up -d     # also build + start the eval worker (opt-in)
podman compose --profile grafana up -d  # also start Prometheus + Grafana (opt-in)
podman compose down                     # stop/remove (keeps the postgres volume; add -v to wipe it)
```

Start order is handled by health-gated `depends_on`, so you don't get the false-positive readiness warning noted
above. See [local-dev/README.md](local-dev/README.md#alternative-a-single-podman-compose-file) for the full details
(service-name/hostname mapping, the shared fluxnova↔otel network namespace, and the `down -v` vs `--delete-data`
difference for MLflow artifacts).

Compose commands address services by their **service name** — every service is named `<container>-local`
(`postgres-local`, `mlflow-local`, `otel-collector-local`, `fluxnova-local`, plus `prometheus-local`/`grafana-local`
under the `grafana` profile), *not* the container name — e.g. `podman compose logs -f fluxnova-local`, not
`... fluxnova`. For status, `podman compose ps` is the provider-agnostic equivalent of `podman pod ps`. The
plain-`podman` verification commands in the [Verify](#verify) section below still work under compose as-is, since each
service sets a matching short `container_name` (`podman logs postgres` / `podman exec postgres ...` /
`podman logs fluxnova`).

#### Note: the optional `eval` container waits for Fluxnova to be *ready*

Only relevant with `--profile eval`, so it's easy to miss when testing just the core stack. The
`eval-service-worker` polls Fluxnova's REST API (`fetchAndLock`) the moment it starts, so compose gates it on
Fluxnova being **healthy** (`condition: service_healthy`), not merely *started* — otherwise its first poll races
Tomcat's ~30–40s boot and logs `[Errno 111] Connection refused`. It leans on the Fluxnova image's built-in
`HEALTHCHECK` for the readiness signal; see the comment on the `eval-service-worker-local` service in
[local-dev/compose.yaml](local-dev/compose.yaml) for the full rationale.

Endpoints once up:

- Postgres: `localhost:5432` (sibling pods reach it as `postgres-local:5432`)
- MLflow UI: `http://localhost:5000`
- Fluxnova REST: `http://localhost:8080/engine-rest`
- Grafana UI: `http://localhost:3000` and Prometheus: `http://localhost:9090` (only with the `--profile grafana`
  compose stack, or the `observability` pod)

### Note: Postgres readiness can log a false-positive warning

On a first run `pods-up.sh` may print *"PostgreSQL doesn't seem to be responding yet"* while the
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

`pods-down.sh` stops/removes all pods in reverse order. Postgres data persists in the
`postgres-local-data` volume unless you pass `--delete-data`.

```bash
cd local-dev
./pods-down.sh                  # stop/remove all pods (reverse order)

# also wipe Postgres volume + MLflow artifacts (forces init.sh to re-run next time):
# ./pods-down.sh --delete-data
```
