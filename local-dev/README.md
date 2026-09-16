# Local development: PostgreSQL + Fluxnova + OTel Collector + MLflow + Grafana (Podman)

This directory contains everything needed to run **PostgreSQL**, the **Fluxnova engine**, the **OTel Collector**,
(optionally) the **MLflow tracking server**, the **frontend UI**, and a **Prometheus + Grafana** GenAI-metrics
dashboard as containers for local development, using [Podman](https://podman.io) —
grouped into a single Podman pod per service (`services/postgres-up.sh` / `services/postgres-down.sh` for PostgreSQL,
`services/fluxnova-up.sh` / `services/fluxnova-down.sh` for Fluxnova + the OTel Collector, `services/mlflow-up.sh` /
`services/mlflow-down.sh` for MLflow, `services/frontend-up.sh` / `services/frontend-down.sh` for the frontend UI,
`services/observability-up.sh` / `services/observability-down.sh` for
Prometheus + Grafana — plus `services/eval-service-up.sh` / `services/eval-service-down.sh` for the
optional eval-service worker), with no compose provider required. PostgreSQL is the shared backing database for both
MLflow's tracking-server backend store and Fluxnova's process-engine datasource, replacing their previous SQLite-file
and H2-file defaults respectively.

## Quick start: `pods-up.sh` / `pods-down.sh`

`pods-up.sh` and `pods-down.sh` orchestrate the per-service scripts (which live in the `services/` subfolder) in the
correct dependency order, so you don't have to remember it or run them one at a time. Both are idempotent (safe to
re-run) and accept one or more pod names to start/stop only a subset:

```bash
cd local-dev

./pods-up.sh                    # start postgres, mlflow, fluxnova, frontend, eval-service, observability, in that order
./pods-up.sh mlflow             # start (or leave alone, if already running) only mlflow
./pods-up.sh postgres fluxnova  # start only postgres and fluxnova (still in order)

./pods-down.sh                  # stop/remove observability, eval-service, frontend, fluxnova, mlflow, postgres, in that order
./pods-down.sh mlflow           # stop/remove only mlflow
./pods-down.sh --delete-data    # stop/remove all AND delete their persistent
                                 # data (postgres' PGDATA volume, mlflow's artifact
                                 # files) — fluxnova/frontend/eval-service/observability have none of their own
```

Run `./pods-up.sh --help` / `./pods-down.sh --help` for full usage. The pod names are `postgres`, `mlflow`,
`fluxnova`, `frontend`, `eval-service`, and `observability`. The sections below describe each underlying per-service
script in the
`services/`
subfolder (`services/postgres-up.sh`/`services/postgres-down.sh` etc.) in more detail, including their own
`--delete-data` flags (`fluxnova-down.sh`/`frontend-down.sh`/`eval-service-down.sh`/`observability-down.sh` accept the
flag too, for a
consistent interface, but
are no-ops since they have no local data).

## Alternative: a single `podman compose` file

`compose.yaml` is a self-contained alternative to the `pods-up.sh`/`pods-down.sh` scripts above — it brings the **same**
stack up from one file, reusing the identical `.env`, `postgres/init.sh`, `default.yml`,
`otel-collector-config.yaml`, `prometheus.yml`, and `grafana/` provisioning. Both approaches share the
`postgres-local-data` volume and the `fluxnova-dev` network, so you can use whichever you prefer (they are not meant to
run simultaneously — pick one). Requires a compose provider (`podman compose`, backed by `podman-compose` or
`docker compose`).

```bash
cd local-dev

podman compose up -d                    # core stack: postgres, mlflow, otel-collector, fluxnova
podman compose --profile eval up -d     # also build + start the eval worker (opt-in)
podman compose --profile grafana up -d  # also start Prometheus + Grafana (opt-in)
podman compose --profile eval --profile grafana up -d   # everything
podman compose logs -f fluxnova-local   # follow one service (by service name, not the fluxnova container_name)
podman compose down                     # stop/remove everything (keeps the postgres volume)
podman compose down -v                  # also delete the postgres data volume (forces init.sh to re-run)
```

Start ordering is handled by health-gated `depends_on` (postgres → mlflow/fluxnova → eval-worker), replacing the
scripts' `wait_for_*` loops: mlflow/fluxnova wait for Postgres to pass `pg_isready`, and the eval worker
waits for fluxnova's image healthcheck (`curl .../engine-rest/engine`) so its first `fetchAndLock` doesn't race
Tomcat startup.

Notes and differences from the pod scripts:

- **Every service is named `<container>-local`** (`postgres-local`, `mlflow-local`, `otel-collector-local`,
  `fluxnova-local`, `eval-service-worker-local`, `prometheus-local`, `grafana-local`) for consistency. The short
  `container_name` (`postgres`, `fluxnova`, …) is what plain `podman logs <name>` / `podman exec <name>` use.
- **`otel-collector-local`/`fluxnova-local` run on `network_mode: host`** — see
  [`OTEL-EXPORT-INVESTIGATION.md`](../OTEL-EXPORT-INVESTIGATION.md) at the repo root: running Fluxnova in any isolated
  Podman network namespace (including this pair's own previous bridge-networked setup) silently breaks the
  OpenTelemetry Java SDK's OTLP export, with no errors anywhere — only the real host namespace works. `fluxnova-local`
  shares `otel-collector-local`'s namespace (`network_mode: "service:otel-collector-local"`, the pod analog), so it
  inherits host networking too and is no longer resolvable by service name from sibling containers — reach it via
  `localhost` from the host, or `host.containers.internal` from other containers (e.g. `eval-service-worker-local`).
  **Grafana** still shares `prometheus-local`'s namespace as before (bridge-networked, so its provisioned
  `localhost:9090` datasource keeps working unchanged).
- **`eval-service-worker-local` is opt-in** behind the `eval` compose profile (it has a build step and needs the
  MLflow AI Gateway judge endpoint configured — see "eval-service-worker" below); **Prometheus + Grafana** are opt-in
  behind the `grafana` profile. Core services carry no profile, so a bare `podman compose up -d` brings up only the
  core four, and `--profile grafana up -d` brings up the core four plus Prometheus/Grafana (Grafana →
  `http://localhost:3000`, Prometheus → `http://localhost:9090`; see the "GenAI observability dashboard" section below).
- **`down -v`** deletes the Postgres named volume but **not** MLflow's artifact files (a host bind-mount at
  `./.mlflow/artifacts`) — unlike `./pods-down.sh --delete-data`, which clears both. Remove that directory by
  hand for a fully clean slate.
- The WSL2 `localhost`-unreachable IP fallback and browser auto-open (both in the `*-up.sh` scripts) are **not**
  reproduced here; they aren't needed under rootless Podman on Linux/WSL. A benign
  `ENGINE-00009 Could not determine local IP address` warning may appear in the fluxnova logs (it can't resolve its
  own container hostname for history events) — cosmetic only; the engine and REST API work normally.

## Prerequisites

- **A local `.env`** — copy `.env.example` to `.env` (`cp .env.example .env` from `local-dev/`) and fill in
  `OPENAI_API_KEY`. `.env` is gitignored since it holds that secret; `.env.example` is the tracked template.
- **[Podman](https://podman.io/docs/installation)** installed, with a running machine/VM on Windows and macOS
  (`podman machine init && podman machine start`) — not needed on Linux. [Podman Desktop](https://podman-desktop.io)
  is recommended, though not required, for a GUI to view/manage pods, containers, and logs.
- **The Fluxnova image**, pulled from GitHub Container Registry — see "Fluxnova image" below. `podman run` (used by
  `fluxnova-up.sh`) pulls it automatically the first time if it isn't already present locally.
- **PostgreSQL running** as the `postgres-local` pod (see "PostgreSQL database" below) — start this **before**
  `mlflow-up.sh` and `fluxnova-up.sh`, both of which now depend on it.
- **The MLflow tracking server running** (either on the host — see the main README's "Running the MLflow tracking
  server" — or as the `mlflow-local` pod below) — the OTel Collector sends traces to it via `host.containers.internal`.

## PostgreSQL database

`postgres-up.sh` / `postgres-down.sh` run PostgreSQL as its own single-container `postgres-local` pod — the shared
backing database for both MLflow's backend store and Fluxnova's process-engine datasource. Run from **Git Bash**,
before starting either `mlflow-up.sh` or `fluxnova-up.sh`:

```bash
cd local-dev
# adjust .env if needed — POSTGRES_IMAGE/POSTGRES_PORT default to postgres:16 / 5432,
# and MLFLOW_POSTGRES_*/FLUXNOVA_POSTGRES_*/POSTGRES_SUPERUSER* set the DB credentials
# (see "Credentials" below)

./services/postgres-up.sh                # start it (idempotent — safe to re-run)
./services/postgres-down.sh              # stop and remove it (the named PGDATA volume is untouched)
./services/postgres-down.sh --delete-data  # stop/remove it AND delete the PGDATA volume
```

On first startup (against an empty PGDATA volume), `postgres/init.sh` is mounted into
`/docker-entrypoint-initdb.d/` and automatically creates two databases/roles, using credentials passed through
as env vars (never hardcoded in the script — see "Credentials" below):

| Database   | Role       | Used by                                               |
|------------|------------|-------------------------------------------------------|
| `mlflow`   | `mlflow`   | MLflow tracking server backend store (`mlflow-up.sh`) |
| `fluxnova` | `fluxnova` | Fluxnova process-engine datasource (`default.yml`)    |

### Credentials

All database passwords (the Postgres superuser plus the `mlflow`/`fluxnova` roles) live in `local-dev/.env` as plain
env vars — `POSTGRES_SUPERUSER`/`POSTGRES_SUPERUSER_PASSWORD`, `MLFLOW_POSTGRES_USER`/`MLFLOW_POSTGRES_PASSWORD`/
`MLFLOW_POSTGRES_DB`, and `FLUXNOVA_POSTGRES_USER`/`FLUXNOVA_POSTGRES_PASSWORD`/`FLUXNOVA_POSTGRES_DB`. Each script
(`postgres-up.sh`, `mlflow-up.sh`, `fluxnova-up.sh`) sources `.env` and passes the relevant vars through to its
container with `-e` — none of them are hardcoded in `postgres/init.sh`, `mlflow-up.sh`'s
`--backend-store-uri`, or `default.yml`'s `spring.datasource` (which uses Spring's `${VAR:default}` placeholder
syntax, resolved from the container's own env vars at startup). Change the values in `.env` before the first
`./postgres-up.sh` run — they're baked into the database on creation; changing them afterwards requires either
removing the `postgres-local-data` volume to re-initialise, or running `ALTER USER ... WITH PASSWORD ...` against
the running database directly.

PGDATA lives in a Podman **named volume** (`postgres-local-data` by default, override with `POSTGRES_VOLUME` in
`.env`) rather than a host bind-mount — bind-mounting PGDATA on Windows/macOS fails during `initdb` ("Operation not
permitted" on `chown`/`chmod`) because the mount is proxied through the Podman VM's 9p/virtiofs filesystem, which
doesn't support the ownership changes Postgres needs; a named volume is real storage inside the VM itself, so this
works normally. It survives `postgres-down.sh` / pod recreation — run `./postgres-down.sh --delete-data` (or
`podman volume rm postgres-local-data`) to force `init.sh` to re-run from scratch. Other pods on the shared
`fluxnova-dev` network reach it at `postgres-local:5432`
(by pod name, same as `mlflow-local:5000` for
MLflow); from the host it's `localhost:5432` (or your configured `POSTGRES_PORT`).

## Starting Fluxnova + the OTel Collector

`fluxnova-up.sh` starts both containers grouped in a single **Podman pod**. Run it from **Git Bash** on Windows (see
the main README's "A note on shells (Windows)"). Requires `postgres-up.sh` to already be running, since
`default.yml`'s `spring.datasource` now points at PostgreSQL (`localhost:5432/fluxnova`) instead of the old H2
file default.

```bash
cd local-dev
# adjust .env if needed — FLUXNOVA_IMAGE defaults to the public GHCR image (see "Fluxnova image" below)

./services/fluxnova-up.sh      # start the pod
./services/fluxnova-down.sh    # stop and remove it
```

This creates a `fluxnova-local` pod on `--network host` (see
[`OTEL-EXPORT-INVESTIGATION.md`](../OTEL-EXPORT-INVESTIGATION.md) at the repo root — running Fluxnova in any isolated
Podman network namespace silently breaks the OpenTelemetry Java SDK's OTLP export, with no errors anywhere; only the
real host namespace works). Both containers still share one network namespace, so they reach each other via
`localhost` — that's why `default.yml` (mounted by the pod script) points `exporterEndpoint` at
`http://localhost:4317` — but with host networking that's also true for the *host* and for reaching sibling pods, no
port mapping needed or possible (`podman pod create --network host` rejects `-p`).

- **`fluxnova`** — the Fluxnova engine, on `http://localhost:8080` (matching `fluxnova_url` in the runner's
  workflow config files), with `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at the collector container.
- **`otel-collector`** — an `otlp` receiver (gRPC `4317` / HTTP `4318`, bound directly on the host) piped through an
  `otlphttp` exporter to the MLflow tracking server (`http://localhost:5000`, reaching `mlflow-local`'s own published
  host port since it isn't resolvable by pod name from this host-networked pod — override
  `MLFLOW_OTLP_ENDPOINT` in `.env` for a different port/host-run MLflow), auto-suffixed with `/v1/traces`. Make sure
  the MLflow tracking server is already running before starting the pod.

See `default.yml` and `otel-collector-config.yaml` for details and adjust image names, ports, or the collector
pipeline as your actual Fluxnova image requires.

### Fluxnova image

`FLUXNOVA_IMAGE` in `.env` points at a versioned image on GitHub Container Registry (GHCR):
`ghcr.io/dogle-scottlogic/fluxnova-edd-platform:<tag>`. The package is **public**, so `podman run` (via
`fluxnova-up.sh`) pulls it automatically on first use with no login required — you don't need to build it yourself
for normal local dev.

**Publishing a new version:** the Fluxnova image is built from the separate `fluxnova-bpm-platform` source (not this
repo). After building it locally there (`podman build -t fluxnova-edd-platform:<new-tag> .`), tag and push it to GHCR:

```bash
podman login ghcr.io -u <github-username>   # needs classic PAT with write:packages (+ repo if private)
podman tag fluxnova-edd-platform:<new-tag> ghcr.io/dogle-scottlogic/fluxnova-edd-platform:<new-tag>
podman push ghcr.io/dogle-scottlogic/fluxnova-edd-platform:<new-tag>
```

Then bump `FLUXNOVA_IMAGE` in `.env` (and this README's example tag above, if it's a new default) to the new tag so
everyone picks it up.

### BPMN agent LLM provider (OpenAI default, Ollama alternative)

The BPMN agent (the `AdHocSubProcess_LoanAssessmentAgent` element in `bpmn/loan-assesment.bpmn`) uses **OpenAI by
default**. The Fluxnova image bundles Spring AI support for both OpenAI and Ollama, and two things together decide
which one actually runs:

1. **`default.yml`'s `spring.ai.model.chat`** — `openai` (the default) or `ollama`. Only one can be active at a time;
   this is what makes the corresponding Spring AI `ChatModel` bean available in the engine.
2. **The BPMN's own `provider` attribute** — the `agent:config` element in `bpmn/loan-assesment.bpmn` (around line 10)
   hardcodes `provider="openai" model="gpt-4o"`. The agentic-subprocess plugin validates this against whichever
   provider is currently active, so the two settings must always agree.

**To switch the agent to Ollama:**

1. In `default.yml`, change `spring.ai.model.chat: openai` to `spring.ai.model.chat: ollama`.
2. In `bpmn/loan-assesment.bpmn`, change `provider="openai" model="gpt-4o"` to `provider="ollama" model="gemma4:e2b"`
   (or another Ollama model you've pulled — confirm tool-calling support with `ollama show <model>`, looking for
   `tools` under Capabilities).
3. Restart Fluxnova so it picks up the new `default.yml` (`podman restart fluxnova`, or re-run `fluxnova-up.sh`) —
   `fluxnova-run` redeploys the BPMN automatically on its next run, no rebuild needed.
4. `OPENAI_API_KEY` in `.env` is no longer needed; make sure `spring.ai.ollama.base-url` in `default.yml` reaches
   your Ollama instance (`http://host.containers.internal:11434` if it's running on the host).

**Gotcha — switching providers with an existing deployment:** if the BPMN was already deployed under the *other*
provider (e.g. you're switching from OpenAI to Ollama after already having run the OpenAI version), `fluxnova-run`'s
pre-deploy cleanup step tries to delete that old deployment — and deleting requires the engine to re-parse it, which
fails with `Invalid provider reference(s) ... references unavailable provider 'openai'` once only `ollama` is active.
To clear it: temporarily set `spring.ai.model.chat` back to match the **old** deployment's provider, restart
Fluxnova, delete the stale deployment (either re-run `fluxnova-run` so its cleanup step succeeds, or call
`DELETE /engine-rest/deployment/<id>?cascade=true` directly — find `<id>` via
`GET /engine-rest/deployment?name=<deployment_name>`), then flip `spring.ai.model.chat` back to the provider you
actually want and restart Fluxnova again before redeploying for real.

Once Fluxnova responds, `fluxnova-up.sh` opens the Fluxnova web UI (`/fluxnova-welcome/index.html`) in your default
browser automatically — same behaviour as `mlflow-up.sh` below, including the `localhost`-unreachable fallback (see
"Troubleshooting"). Set `FLUXNOVA_OPEN_BROWSER=false` to skip the auto-open.

### Troubleshooting: fluxnova-up does not start the fluxnova container

Make sure that you have not manually created the container from the fluxnova-edd-platform image, but instead rely on the
script to create this for you.

If you manually create the container the script will sometimes skip over this step. Remove the container entirely and
re-run the fluxnova-up script.

## Optional: run the MLflow tracking server in its own Podman pod

`mlflow-up.sh` / `mlflow-down.sh` run the MLflow tracking server (see the main README's "Running the MLflow
tracking server") as a container instead of a host process, as its own single-container `mlflow-local` pod — kept
separate from `fluxnova-local` since it's a longer-lived dev service you likely want to start/stop independently of
any one Fluxnova run. Requires `postgres-up.sh` to already be running. Run from **Git Bash**:

```bash
cd local-dev
# adjust .env if you haven't already; set MLFLOW_IMAGE/MLFLOW_PORT/MLFLOW_ARTIFACT_DIR if needed

./services/mlflow-up.sh      # start it
./services/mlflow-down.sh    # stop and remove it (the PostgreSQL backend store and local artifacts are untouched)
```

This uses the official `ghcr.io/mlflow/mlflow` image, backed by PostgreSQL (`postgres-local` pod's `mlflow`
database — see "PostgreSQL database" above) for its metadata backend store, so an MLflow client on the host and
this container see identical data — you can freely switch between running MLflow as a host process and as this
container, as long as both point at the same PostgreSQL database. Artifacts (e.g. logged models/files) still live on
a bind-mounted host directory (`local-dev/.mlflow/artifacts` by default, override with `MLFLOW_ARTIFACT_DIR`), since
Postgres only stores metadata, not blobs. The OTel Collector's `otlphttp` exporter
(`http://host.containers.internal:5000`) reaches it exactly as it would a host-run server, since the pod's port is
published to the host either way.

Once the container is up, `mlflow-up.sh` waits for it to respond, then opens the UI in your default browser
automatically (see "Troubleshooting" below for what it does if `localhost` isn't reachable). Set
`MLFLOW_OPEN_BROWSER=false` to skip the auto-open.

### Troubleshooting: `localhost:5000` unreachable from Windows, but the container is running

On some Windows/WSL2 setups, MLflow's Python server is unreachable via `localhost`/`127.0.0.1` from *outside* WSL —
`podman ps` shows it running, and it responds fine to requests made *inside* the Podman machine, but everything
through the WSL2 `localhost`-forwarding relay silently resets (`curl` reports "Empty reply from server"). This
reproduced consistently in testing even across a full `wsl --shutdown` + restart, while other containers (e.g.
`nginx`, the Fluxnova/Java container above) were unaffected on the same machine — so it appears specific to this
Python server plus this Windows/WSL2 networking configuration, not a bug in the pod script or the MLflow image
itself.

`mlflow-up.sh` handles this automatically: if `http://localhost:$MLFLOW_PORT` doesn't respond within a few
seconds, it looks up the Podman machine's own IP (`wsl -d podman-machine-default -- ip -4 addr show eth0`), checks
that it's reachable, and uses it instead — both for the printed URLs and for the browser it opens. If you're doing
this manually (e.g. pointing the OTel Collector's `otlphttp` exporter somewhere), the same commands are:

```bash
wsl -d podman-machine-default -- ip -4 addr show eth0   # note the inet address, e.g. 172.28.x.x
curl http://<that-ip>:5000/version                       # works even when localhost:5000 doesn't
```

That IP can change on VM restart, so re-run `mlflow-up.sh` (or the `wsl` command above) if it stops working. If
you don't hit this on your machine, `http://localhost:5000` works as documented above.

## MLflow AI Gateway endpoint for automatic evaluation judges

MLflow's built-in AI Gateway (`http://localhost:5000/#/gateway`, part of the same `mlflow-local` pod/server — no
separate service to run) is required for **automatic evaluation** judges (`Scorer.register()` + `Scorer.start()`),
which — unlike offline/EDD judges — must reference a `gateway:/<endpoint-name>` model URI rather than calling Ollama
directly. Here's how to reproduce a working local `fluxnova-judge` endpoint backed by a host-run Ollama:

1. Make sure Ollama itself is listening on all interfaces, not just `127.0.0.1` — the `mlflow-local` container needs
   to reach it from outside the Windows host's own loopback, which is not the default. Set `OLLAMA_HOST` and
   restart Ollama:
   ```powershell
   [System.Environment]::SetEnvironmentVariable('OLLAMA_HOST', '0.0.0.0:11434', 'User')
   ```
   Setting the variable alone does **not** reconfigure an already-running Ollama process, and relaunching it via its
   tray icon may not help either — Explorer (and anything it spawns) only picks up new User environment variables
   after you log off/on or reboot. To apply it immediately, quit Ollama and relaunch it from a shell that already
   has `OLLAMA_HOST` set in its own process environment:
   ```powershell
   Stop-Process -Name "ollama app" -Force
   Stop-Process -Name "ollama" -Force
   $env:OLLAMA_HOST = "0.0.0.0:11434"
   Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
   ```
   Confirm it worked: `Get-NetTCPConnection -LocalPort 11434 | Select LocalAddress` should show `::` (or
   `0.0.0.0`), not `127.0.0.1`. See "Troubleshooting" below if the container still can't reach it after this.
2. Make sure `mlflow-local` is running (`./services/mlflow-up.sh`) with the `--add-host
   host.containers.internal:host-gateway` flag included at pod-create time (already the default in this script).
3. Open `http://localhost:5000/#/gateway` and click **Create Endpoint**.
4. Name it `fluxnova-judge`, select provider **Ollama**.
5. Pick a model from the picker — at time of writing only `llama3.1` was offered here even though `llama3.2` was
   already pulled locally (`ollama list`); `llama3.1` works fine, though this repo's `fluxnova-judge` example endpoint
   now uses `qwen2.5:1.5b` (a small, fast judge chosen so CPU-only judging stays under the gateway timeout). Note
   this means the automatic-evaluation judge model may differ from the `ollama/gemma4:e2b` model the existing
   hand-rolled `_llm_judge()` offline scorers use, unless reconciled later.
6. Create a new connection for it:
    - **Base URL**: try `http://host.containers.internal:11434/v1` first — it works out of the box for most setups.
      On some Windows/Podman-machine/WSL2 setups it doesn't, though: if the Podman machine uses rootless `pasta`
      networking, the `host.containers.internal` alias resolves to the WSL VM's *own* loopback rather than the
      Windows host, so the connection fails no matter how Ollama/the firewall are configured (see "Troubleshooting"
      below for how to tell the difference from an Ollama/firewall problem). If you hit that, fall back to the
      Podman machine's actual default-gateway IP instead, found with:
      ```bash
      wsl.exe -d podman-machine-default -- ip route show default   # note the "via <ip>" address
      ```
      e.g. `http://172.17.112.1:11434/v1`. The `/v1` suffix is required either way — MLflow's `OllamaProvider`
      appends `/chat/completions` directly onto whatever base URL is configured, with no separate `/v1` insertion, so
      omitting it causes every request to 404 (you'll see Ollama's own literal
      `{"detail":{"message":"404 page not found"}}` body passed through — this looks like an MLflow failure at first
      glance but is actually Ollama's router rejecting the wrong path). That gateway IP can change across reboots or
      Podman machine resets — re-run the `wsl.exe` command above and update the endpoint if it stops connecting.
    - **API key name/value**: any placeholder (e.g. `OLLAMA_API_KEY` / `unused`) — local Ollama needs no real
      authentication, but the UI form requires something be entered.
7. Save. There's no in-place "edit the base URL" option once an endpoint/connection is created in this MLflow
   version — to fix a mistake, delete and recreate rather than editing.
8. Verify with the OpenAI-compatible unified endpoint (works with `curl` or the OpenAI Python SDK):
   ```python
   from openai import OpenAI

   client = OpenAI(
       base_url="http://localhost:5000/gateway/mlflow/v1",
       api_key="unused",  # not validated for a local Ollama-backed endpoint
   )
   response = client.chat.completions.create(
       model="fluxnova-judge",  # the endpoint name, not the underlying Ollama model name
       messages=[{"role": "user", "content": "How are you?"}],
   )
   print(response.choices[0].message)
   ```
   A real completion coming back (rather than a 404/500) confirms the endpoint is wired up correctly.

### Troubleshooting: gateway endpoint returns a 500 with an Ollama connection error

If step 8 above (or a real judge run) returns a 500 with a traceback ending in something like
`ClientConnectorError: Cannot connect to host ...` or `ConnectionRefusedError`, work through these in order — each
was hit in turn getting this working on a Windows/Podman-machine/WSL2 setup:

1. **Ollama isn't listening on all interfaces.** Check on the Windows host:
   ```powershell
   Get-NetTCPConnection -LocalPort 11434 | Select-Object LocalAddress,LocalPort,State
   ```
   `LocalAddress` of `127.0.0.1` means Ollama only accepts loopback connections — nothing outside the Windows
   host's own localhost, including containers, can reach it. Fix as in step 1 above, making sure to relaunch Ollama
   from a shell that already has `OLLAMA_HOST` set (a registry-only User env var change doesn't reach
   already-running or already-spawned process trees).

2. **Windows Firewall is silently dropping the inbound connection.** Even with Ollama listening on `0.0.0.0`/`::`,
   the container's connection attempt can still time out if nothing allows inbound TCP 11434 from the WSL2 virtual
   network. A timeout (as opposed to an instant refusal) from inside the Podman VM's own network namespace is the
   signature of this:
   ```bash
   wsl.exe -d podman-machine-default -- sh -c "curl -sv --max-time 5 http://<gateway-ip>:11434/api/version"
   ```
   Fix with a standard inbound allow rule (run as Administrator):
   ```powershell
   New-NetFirewallRule -DisplayName "Ollama TCP 11434 (WSL)" -Direction Inbound -Protocol TCP -LocalPort 11434 -Action Allow -Profile Any
   ```
   Note: on newer Windows builds the WSL vEthernet adapter shows up as `vEthernet (WSL (Hyper-V firewall))`, which
   might suggest the newer per-VM `New-NetFirewallHyperVRule` cmdlet is the right tool — in testing on this repo it
   wasn't: `Get-NetFirewallHyperVPort` showed no live VM port for such a rule to bind to, and it had no effect even
   after a full `wsl --shutdown` + restart. The plain `New-NetFirewallRule` above is what actually worked.

3. **If 1 and 2 are both fixed and it's still failing, `host.containers.internal` may not resolve to the Windows
   host at all on your setup.** This only affects some rootless/pasta-networked Podman machines — plenty of setups
   work fine with `host.containers.internal` and never hit this. If yours doesn't, an endpoint configured against
   `host.containers.internal` will keep failing no matter how Ollama/the firewall are configured; point it at the
   Podman machine's actual default-gateway IP instead (`wsl.exe -d podman-machine-default -- ip route show
   default`) — see the Base URL bullet above.

If you're not on Windows, or your Podman machine uses a different networking backend (e.g. rootful mode, or a
`gvproxy`-backed `host.containers.internal` that actually reaches the host), your mileage on 2–3 may vary — the
underlying goal is just "the `mlflow-local` container can reach `<something>:11434` on the host machine"; adapt the
diagnostic commands to whatever your container runtime's host-networking mechanism actually is.

## Toggling automatic evaluation judges on/off

Once the `fluxnova-judge` gateway endpoint exists (see above), use the `mlflow-judges` CLI (installed by
`fluxnova-mlflow-dataset` — run `pip install -e .` in `fluxnova-mlflow-dataset/` after pulling if it's missing) to
register and toggle automatic judges for a given experiment. It targets every judge returned by
`fluxnova_mlflow_dataset.automatic_judges()` (currently
`decision_quality`):

```bash
# Register + start automatic sampling (registers on first run automatically)
mlflow-judges --experiment fluxnova-loanAssessmentProcess start --sample-rate 0.1

# Stop sampling (judge stays registered; cheap to restart later)
mlflow-judges --experiment fluxnova-loanAssessmentProcess stop

# Show current registration/sampling state
mlflow-judges --experiment fluxnova-loanAssessmentProcess status
```

`--tracking-uri` defaults to `http://localhost:5000` (the running `mlflow-local` server) — this **must** be an
HTTP (S) address, not a direct `postgresql://...` path, because gateway-backed judges route through the server process
itself. Add `--filter-string` to `start` to restrict which traces get scored (e.g. to exclude EDD regression runs).

## Targeting a different MLflow experiment

By default, workflow runs/records use a single experiment named `fluxnova-<process_key>` (e.g.
`fluxnova-loanAssessmentProcess`) — no dev/prod split (a `dev`/`prod` environment-suffix scheme was tried and then
reverted; not needed for this demo's scope). To point at a different experiment without changing any code, set an
explicit override in the workflow config:

```yaml
mlflow_dataset:
  enabled: true
  experiment_name: fluxnova-loanAssessmentProcess-demo   # any name you like
```

If omitted, it defaults to `fluxnova-<process_key>` as before — existing configs don't need any changes.

If you need to rename an existing experiment/dataset in place (e.g. after changing this override), use:

```python
import mlflow

mlflow.set_tracking_uri("postgresql://mlflow:mlflow@localhost:5432/mlflow")
client = mlflow.MlflowClient()
client.rename_experiment("<experiment_id>", "<new-name>")
```

`mlflow.genai.datasets.EvaluationDataset` has no public rename API — if needed, update the `name` column directly in
the `evaluation_datasets` table of the PostgreSQL tracking store instead (safe for local dev data; the `dataset_id`,
schema, and records are untouched, only the lookup name changes).

## eval-service-worker: scoring completed subprocess runs

`eval-service-worker` (see `eval-service-worker/` and `EVAL-SERVICE-WORKER-PLAN.md` at the repo root) is a standalone
BPMN external-task worker that scores a just-completed agentic subprocess run against the `decision_quality` MLflow
judge plus a set of trace-only deterministic scorers (`required_tools_called`, `no_tool_errors`,
`definitive_decision_stated`), reading data purely from MLflow's trace store (no BPMN parsing, no Fluxnova REST
history calls). All scorers' `Feedback` are logged back onto the trace as MLflow assessments grouped under one
Evaluation Run, plus a lightweight MLflow evaluation-dataset record; the task then completes with
`evalPassed`/`evalRationale` output variables — `evalPassed` is driven solely by `decision_quality` (the deterministic
scorers are recorded for visibility/audit only, not yet wired into the gate).

**BPMN wiring:** `bpmn/loan-assesment-eval.bpmn` (a separate process definition, `loanAssessmentEvalProcess`, from the
original `loan-assesment.bpmn`) invokes the loan-assessment agent as a **Call Activity**
(`CallActivity_LoanAssessmentAgent` → `loanAssessmentProcess`, defined in `loan-assesment.bpmn`), then runs
`ServiceTask_EvaluateAgentOutput` on this worker's topic (`agent-output-eval`), followed by
`ExclusiveGateway_EvalPassed`
routing on `evalPassed`: on pass → generate-report → approve/reject decision (with a human review task); on fail → a
`UserTask_ReviewFailedEval` human step. Because the agent runs in the Call Activity's *child* instance, the worker
resolves that child from the parent instance it's handed before reading its trace (see `eval-service-worker/README.md`).

Use `fluxnova-runner/config/loan-assesment-eval.yml` (not `loan-assesment.yml`) to run this BPMN — it lists
`loan-assesment.bpmn` under
`additional_bpmn_paths` so both process definitions deploy together, and sets `wait_for_activity:
CallActivity_LoanAssessmentAgent` so `fluxnova-run` returns once the agent finishes instead of hanging on the downstream
human tasks.

**Experiment alignment:** the OTel collector routes **every** trace (from the parent eval process and the called agent
child process alike) to the single MLflow experiment named by `MLFLOW_EXPERIMENT_ID` — a static collector header, not
per-process-key. The worker reads agent traces from `EVAL_SERVICE_EXPERIMENT_NAME`, so that name **must** resolve to the
same experiment `MLFLOW_EXPERIMENT_ID` points at (currently `fluxnova-loanAssessmentEvalProcess`, experiment id `3`).
Both
are kept in `local-dev/.env` (the single source of truth, also consumed by `compose.yaml`) so they stay in sync;
`eval-service-up.sh` passes `EVAL_SERVICE_EXPERIMENT_NAME` through to the container. You can also trigger a one-off
scoring run manually — see
`eval-service-worker/README.md` (or call `eval_service_worker.scoring.score_process_instance(...)` directly) with a
real `processInstanceId` from a completed run.

```bash
cd local-dev
./services/eval-service-up.sh          # build image if missing, start the eval-service-local pod
REBUILD=1 ./services/eval-service-up.sh  # force a rebuild after changing worker / fluxnova-mlflow-dataset code
./services/eval-service-down.sh        # stop and remove it
```

Or start it as part of the whole stack with `./pods-up.sh` (it's the last pod started, after fluxnova/mlflow, which
it depends on). It builds `eval-service-worker/Dockerfile` from the repo root (so it can install the local
`fluxnova-mlflow-dataset` path dependency too) **only when the image is missing** — repeated up-runs skip the
pip-install
cost, so pass `REBUILD=1` to force a rebuild after changing `eval-service-worker/` or `fluxnova-mlflow-dataset/`. It
passes `EVAL_SERVICE_FLUXNOVA_URL`/`EVAL_SERVICE_TRACKING_URI`/`EVAL_SERVICE_EXPERIMENT_NAME`
env vars (sourced from `local-dev/.env`) pointed at `mlflow-local` by pod name on the shared `fluxnova-dev` network,
and at `fluxnova-local` via `host.containers.internal` (that pod runs on `--network host` — see
[`OTEL-EXPORT-INVESTIGATION.md`](../OTEL-EXPORT-INVESTIGATION.md) — so it isn't resolvable by pod name). Both must
already be running. Because Podman bakes env vars at `podman run`, run `./services/eval-service-down.sh` then
`./services/eval-service-up.sh` to pick up any `.env` change (an existing pod is only *started*, not recreated).

The worker has **no config file of its own** — every setting (`fluxnova_url`, `experiment_name`, `process_key`,
`topic`, `judge_model`, `lock_duration_ms`, `tracking_uri`) is a hardcoded default in
`eval-service-worker/src/eval_service_worker/config.py`, overridable via either a CLI flag (e.g. `--tracking-uri`)
or an `EVAL_SERVICE_<NAME>` environment variable (e.g. `EVAL_SERVICE_TRACKING_URI`) — see that file or
`eval-service-worker/README.md` for the full list. This is deliberate: it keeps the worker independently deployable
without depending on another service's workflow YAML.

## GenAI observability dashboard: Prometheus + Grafana

`services/observability-up.sh` runs **Prometheus + Grafana** in a single `observability-local` Podman pod so you can
view Fluxnova's `gen_ai.*` metrics live on a dashboard. It plugs into the existing OTLP pipeline without touching the
traces-to-MLflow flow:

```
Fluxnova ──OTLP──> OTel Collector ─┬─ traces  ──> MLflow          (unchanged)
 (fluxnova-local,  (fluxnova-local, └─ metrics ──> Prometheus exporter :8889
  --network host)   --network host)                   ▲ scrape (via localhost)
                        Prometheus :9090 ───────────────┘   (observability-local, --network host)
                                        ▲ query
                                    Grafana :3000            (observability-local)
```

The OTel Collector now has a **metrics pipeline** (`otel-collector-config.yaml`) exposing a Prometheus scrape endpoint
on `:8889`, bound directly on the host since `fluxnova-local` runs on `--network host` (see
[`OTEL-EXPORT-INVESTIGATION.md`](../OTEL-EXPORT-INVESTIGATION.md)). `observability-local` runs on `--network host`
too — Prometheus scraping a `--network host` pod's port from a *different* namespace hit a second, separate problem
on Podman Desktop/machine (Windows): `host.containers.internal` routes out to the actual Windows host, not back into
the podman-machine VM where the port actually lives, so it times out. Only a fellow `--network host` container can
reach it, via plain `localhost` — confirmed empirically. Prometheus (`prometheus.yml`) scrapes `localhost:8889`;
Grafana auto-provisions the Prometheus datasource and the **Fluxnova GenAI Metrics** dashboard (`grafana/`), with
panels for token usage/throughput, chat/agent/tool latency percentiles, inference & tool-call counts per agent run,
operation rate and tool error rate.

```bash
cd local-dev
./services/observability-up.sh     # start the observability-local pod (Prometheus + Grafana)
./services/observability-down.sh   # stop and remove it
```

- **Grafana** → http://localhost:3000 (dashboard: *Fluxnova → Fluxnova GenAI Metrics*). Anonymous viewing is enabled;
  log in as `admin`/`admin` to edit. Set `GRAFANA_PORT`/`GRAFANA_IMAGE` in `.env` to change.
- **Prometheus** → http://localhost:9090 (check `…/targets` — `localhost:8889` should be **UP**). Set
  `PROMETHEUS_PORT`/`PROMETHEUS_IMAGE` in `.env` to change.

Start `fluxnova-up.sh` **before** this pod (and run an agentic subprocess) so there are metrics to scrape — until then
Prometheus reports the target down and the panels are empty. Storage is in-container/ephemeral, so
`observability-down.sh` needs no `--delete-data`. Like the other scripts it uses the same `localhost`→Podman-machine-IP
readiness fallback (see "Troubleshooting" above) and opens Grafana in your browser (`OBSERVABILITY_OPEN_BROWSER=false`
to skip).

## Files

| File                                                              | Purpose                                                                                                                                                                                                               |
|-------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `pods-up.sh` / `pods-down.sh`                                     | Start/stop postgres, mlflow, fluxnova, eval-service, and observability together (in dependency order), or any subset — idempotent                                                                                     |
| `compose.yaml`                                                    | Single-file `podman compose` alternative to the pod scripts (same `.env`/configs); `eval-service-worker` and `observability` behind the `eval`/`grafana` profiles — see "Alternative: a single `podman compose` file" |
| `services/postgres-up.sh` / `services/postgres-down.sh`           | Start/stop the `postgres-local` pod (shared PostgreSQL database)                                                                                                                                                      |
| `postgres/init.sh`                                                | Creates the `mlflow`/`fluxnova` databases and roles on first startup                                                                                                                                                  |
| `services/fluxnova-up.sh` / `services/fluxnova-down.sh`           | Start/stop the `fluxnova-local` pod (Fluxnova + OTel Collector)                                                                                                                                                       |
| `services/mlflow-up.sh` / `services/mlflow-down.sh`               | Start/stop the `mlflow-local` pod                                                                                                                                                                                     |
| `services/eval-service-up.sh` / `services/eval-service-down.sh`   | Build/start/stop the `eval-service-local` pod (see above)                                                                                                                                                             |
| `services/observability-up.sh` / `services/observability-down.sh` | Start/stop the `observability-local` pod (Prometheus + Grafana GenAI dashboard)                                                                                                                                       |
| `default.yml`                                                     | Fluxnova config mounted by `services/fluxnova-up.sh` (OTel plugin → `localhost:4317`, `--network host` pod; datasource → PostgreSQL via `localhost:5432`)                                                             |
| `otel-collector-config.yaml`                                      | OTel Collector pipelines: `otlp` receiver → `otlp_http` exporter to MLflow (traces) + `prometheus` exporter on `:8889` (metrics)                                                                                      |
| `prometheus.yml`                                                  | Prometheus scrape config (mounted by `services/observability-up.sh`) — scrapes `localhost:8889` (`--network host`)                                                                                                    |
| `grafana/`                                                        | Grafana provisioning (Prometheus datasource + dashboard provider) and the `gen-ai.json` dashboard                                                                                                                     |
| `.env`                                                            | Environment values (image names/ports/paths) — adjust as needed                                                                                                                                                       |

