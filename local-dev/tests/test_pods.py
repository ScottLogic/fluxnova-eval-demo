"""Exercise the real Bash scripts with a recording Podman, without starting a VM."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def run_script(tmp_path):
    local = tmp_path / "checkout with spaces/local-dev"
    shutil.copytree(Path(__file__).parents[1] / "services", local / "services")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "podman.jsonl"
    podman = binaries / "podman"
    podman.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['PODMAN_TEST_LOG'], 'a') as f: f.write(json.dumps(args) + '\\n')\n"
        "if args[:2] in [['pod', 'exists'], ['image', 'exists'], ['volume', 'exists']]: sys.exit(1)\n"
        "if args[:1] == ['info'] and os.environ.get('STOPPED_MACHINE'): sys.exit(125)\n"
    )
    podman.chmod(0o755)
    curl = binaries / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n")
    curl.chmod(0o755)

    def run(name, mode="bridge", extra=None):
        (local / ".env").write_text(
            f"DEV_NETWORK_MODE={mode}\nFLUXNOVA_PORT=18080\nMLFLOW_PORT=15000\n"
            "POSTGRES_PORT=15432\nPROMETHEUS_PORT=19090\nGRAFANA_PORT=13000\n"
            "LLM_JUDGE_PROVIDER=openai\nOPENAI_API_KEY=test-key\n"
        )
        env = dict(
            os.environ,
            PATH=f"{binaries}:{os.environ['PATH']}",
            PODMAN_TEST_LOG=str(log),
            FLUXNOVA_OPEN_BROWSER="false",
            MLFLOW_OPEN_BROWSER="false",
            OBSERVABILITY_OPEN_BROWSER="false",
        )
        env.update(extra or {})
        result = subprocess.run(
            ["bash", str(local / f"services/{name}-up.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        return result, commands

    return run


def test_bridge_engine_publishes_ports_and_uses_internal_db(run_script):
    result, commands = run_script("fluxnova")
    assert result.returncode == 0, result.stderr
    create = next(c for c in commands if c[:2] == ["pod", "create"])
    assert "18080:8080" in create
    engine = next(c for c in commands if c[:1] == ["run"] and "fluxnova" in c)
    assert engine[engine.index("--platform") + 1] == "linux/amd64"
    assert "FLUXNOVA_POSTGRES_HOST=postgres-local" in engine
    assert "FLUXNOVA_POSTGRES_PORT=5432" in engine


def test_host_fallback_uses_vm_local_db_port_without_publishing(run_script):
    result, commands = run_script("fluxnova", "host")
    assert result.returncode == 0, result.stderr
    create = next(c for c in commands if c[:2] == ["pod", "create"])
    assert "host" in create and "-p" not in create
    engine = next(c for c in commands if c[:1] == ["run"] and "fluxnova" in c)
    assert "SERVER_PORT=18080" in engine
    assert "FLUXNOVA_POSTGRES_HOST=localhost" in engine
    assert "FLUXNOVA_POSTGRES_PORT=15432" in engine


def test_listener_receives_judge_credentials_and_container_ollama_url(run_script):
    result, commands = run_script("eval-listener")
    assert result.returncode == 0, result.stderr
    run = next(c for c in commands if c[:1] == ["run"])
    assert "OPENAI_API_KEY=test-key" in run
    assert "LLM_JUDGE_PROVIDER=openai" in run
    assert "OLLAMA_API_BASE=http://host.containers.internal:11434" in run


def test_worker_host_fallback_can_reach_engine_and_mlflow(run_script):
    result, commands = run_script("eval-service", "host")
    assert result.returncode == 0, result.stderr
    run = next(c for c in commands if c[:1] == ["run"])
    assert "EVAL_SERVICE_FLUXNOVA_URL=http://localhost:18080/engine-rest" in run
    assert "EVAL_SERVICE_TRACKING_URI=http://localhost:15000" in run
    assert "EVAL_SERVICE_JUDGE_MODEL=openai:/gpt-4o-mini" in run


def test_mlflow_mounts_shared_bootstrap_and_runtime(run_script):
    result, commands = run_script("mlflow")
    assert result.returncode == 0, result.stderr
    run = next(c for c in commands if c[:1] == ["run"])
    assert "mlflow-local-runtime:/mlflow-runtime" in run
    assert "/local-dev-mlflow/start.sh" in run
    assert "15000:5000" in next(c for c in commands if c[:2] == ["pod", "create"])


def test_postgres_uses_named_storage_and_published_port(run_script):
    result, commands = run_script("postgres")
    assert result.returncode == 0, result.stderr
    assert "15432:5432" in next(c for c in commands if c[:2] == ["pod", "create"])
    run = next(c for c in commands if c[:1] == ["run"])
    assert "postgres-local-data:/var/lib/postgresql/data" in run
    probe = next(c for c in commands if "pg_isready" in c)
    assert probe[probe.index("-h") + 1] == "127.0.0.1"


def test_observability_publishes_host_ports_but_keeps_internal_datasource(run_script):
    result, commands = run_script("observability")
    assert result.returncode == 0, result.stderr
    create = next(c for c in commands if c[:2] == ["pod", "create"])
    assert "19090:9090" in create and "13000:3000" in create
    grafana = next(c for c in commands if c[:1] == ["run"] and "grafana" in c)
    assert "PROMETHEUS_URL=http://localhost:9090" in grafana


def test_stopped_machine_fails_before_creating_resources(run_script):
    result, commands = run_script("fluxnova", extra={"STOPPED_MACHINE": "1"})
    assert result.returncode != 0
    assert "podman machine start" in result.stderr
    assert not any(c[:2] == ["pod", "create"] for c in commands)
