# Running on WSL with rootless Podman

This uses Podman **inside a WSL distro**, rather than the Windows Git Bash client.
For macOS see [RUNNING-MACOS.md](RUNNING-MACOS.md); shared configuration and debugging
are described in [local-dev/README.md](local-dev/README.md).

## Prerequisites

- Rootless Podman in your distro (`podman info`); no Podman machine is required
  when running Podman directly in Linux/WSL.
- Python 3.11+.
- An OpenAI API key for the default agent and judges. Ollama is optional.

## Setup and run

From the repository root in WSL:

```bash
./setup.sh
source .venv/bin/activate
cp local-dev/.env.example local-dev/.env  # first time only
```

Edit the key in `.env`, then:

```bash
./local-dev/pods-up.sh
set -a
source local-dev/.env
set +a
fluxnova-run fluxnova-runner/config/loan-assesment.yml --with-mock-workers
fluxnova-run fluxnova-runner/config/loan-assesment-eval.yml --with-mock-workers
```

Linux/WSL defaults to bridge networking with published host ports. MLflow creates
the trace experiment automatically; no fixed ID or gateway setup is needed for
the default direct judges. If reproducing the older OTLP isolation issue, select
`DEV_NETWORK_MODE=host` in `.env` and recreate the pods. Windows Git Bash already
defaults to that fallback; these are different Podman environments.

Endpoints: Fluxnova `localhost:8080` (`demo`/`demo`), MLflow `localhost:5001`, Grafana
`localhost:3000`, Prometheus `localhost:9090`, PostgreSQL `localhost:5432`. Respect
any `.env` port overrides. Follow steps 7–11 of the Mac guide for workflow, trace,
assessment, regression and persistence checks; use your Linux browser as appropriate.

## Compose alternative

Install a provider such as `podman-compose`, then from `local-dev/`:

```bash
podman compose --profile eval --profile grafana up -d --build
podman compose ps
podman compose logs -f fluxnova-local
podman compose --profile eval --profile grafana down
```

Choose Compose or pod scripts for a session; they share names and data volumes.

## Ollama and teardown

For local models, run Ollama in the distro or configure a reachable Windows host
URL. Set the agent/provider pair and judge settings as explained in the shared
guide. Do not assume WSL/Windows loopback addresses are interchangeable.

```bash
./local-dev/pods-down.sh                # preserves databases and artifacts
# ./local-dev/pods-down.sh --delete-data # intentional clean reset
```
