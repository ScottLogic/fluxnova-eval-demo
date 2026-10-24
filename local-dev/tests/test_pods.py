"""Exercise the real Bash scripts with a recording Podman, without starting a VM."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Retain only the OS/runtime environment needed to launch Bash and the recording
# Python executable. Developer .env exports and fake-Podman controls must come
# exclusively from this fixture's .env or the test's explicit `extra` argument.
_RUNTIME_ENV_KEYS = {
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
    "TEMP", "TMP", "TMPDIR", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH",
}


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
        "if args[:1] == ['info'] and os.environ.get('STOPPED_MACHINE'): sys.exit(125)\n"
        "if args[:2] == ['pod', 'exists']: sys.exit(0 if os.environ.get('EXISTING_POD') else 1)\n"
        "if args[:2] == ['container', 'exists']: sys.exit(1 if os.environ.get('INCOMPLETE_POD') else 0)\n"
        "if args[:2] == ['container', 'inspect']:\n"
        " fmt = args[args.index('--format') + 1]\n"
        " if '.Config.Env' in fmt: print('EVAL_SERVICE_EXPERIMENT_NAME=' + os.environ.get('BAKED_EXPERIMENT', 'fluxnova-loanAssessmentEvalProcess'))\n"
        " elif '.State.Status' in fmt:\n"
        "  with open(os.environ['PODMAN_TEST_LOG']) as f: previous = [json.loads(line) for line in f]\n"
        "  probed = any(c[:1] == ['exec'] and 'test' in c for c in previous)\n"
        "  print('exited 1' if os.environ.get('EXITED_CONTAINER') or (os.environ.get('EXIT_AFTER_EXEC') and probed) else 'running 0')\n"
        "if args[:2] == ['image', 'exists']: sys.exit(0 if os.environ.get('CACHED_IMAGE') else 1)\n"
        "if args[:2] == ['image', 'inspect']: print(os.environ.get('IMAGE_PLATFORM', 'linux/amd64'))\n"
        "if args[:2] == ['pod', 'inspect']: print(os.environ.get('EXISTING_MLFLOW_PORT', '15000'))\n"
        "if args[:2] == ['pod', 'start'] and os.environ.get('START_ERROR'):\n"
        " print(os.environ['START_ERROR'], file=sys.stderr); sys.exit(125)\n"
        "if args[:1] == ['run'] and os.environ.get('RUN_ERROR'):\n"
        " print(os.environ['RUN_ERROR'], file=sys.stderr); sys.exit(125)\n"
        "if args[:1] == ['exec'] and 'test' in args and os.environ.get('HEADER_NOT_READY'):\n"
        " print('can only create exec sessions on running containers: container state improper', file=sys.stderr); sys.exit(125)\n"
        "if args[:1] == ['logs']: print(os.environ.get('LOG_MESSAGE', 'startup log'), file=sys.stderr)\n"
        "if args[:1] == ['pull']:\n"
        " with open(os.environ['PODMAN_TEST_LOG']) as f: count = sum(json.loads(line)[0] == 'pull' for line in f)\n"
        " if count <= int(os.environ.get('PULL_FAILURES', '0')):\n"
        "  print('failed to decode message from stream: unexpected EOF', file=sys.stderr); sys.exit(125)\n"
    )
    podman.chmod(0o755)
    curl = binaries / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n")
    curl.chmod(0o755)

    def run(name, mode="bridge", extra=None, mlflow_port="15000"):
        log.write_text("")
        (local / ".env").write_text(
            f"DEV_NETWORK_MODE={mode}\nFLUXNOVA_PORT=18080\n"
            + (f"MLFLOW_PORT={mlflow_port}\n" if mlflow_port else "")
            + "POSTGRES_PORT=15432\nPROMETHEUS_PORT=19090\nGRAFANA_PORT=13000\n"
            "LLM_JUDGE_PROVIDER=openai\nOPENAI_API_KEY=test-key\n"
        )
        env = {key: value for key, value in os.environ.items() if key.upper() in _RUNTIME_ENV_KEYS}
        env.update(
            PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}",
            PODMAN_TEST_LOG=str(log),
            FLUXNOVA_OPEN_BROWSER="false",
            MLFLOW_OPEN_BROWSER="false",
            OBSERVABILITY_OPEN_BROWSER="false",
            IMAGE_PULL_RETRY_DELAY="0",
        )
        env.update(extra or {})
        result = subprocess.run(
            ["bash", str(local / f"services/{name}-up.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
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


def test_mlflow_default_is_5001_on_host_and_5000_in_container(run_script):
    result, commands = run_script("mlflow", mlflow_port=None)
    assert result.returncode == 0, result.stderr
    assert "5001:5000" in next(c for c in commands if c[:2] == ["pod", "create"])
    assert "http://localhost:5001" in result.stdout


@pytest.mark.parametrize(
    "service",
    [
        "postgres",
        "mlflow",
        "fluxnova",
        "observability",
        "eval-service",
        "eval-listener",
    ],
)
def test_failed_pull_creates_no_pod_or_container(run_script, service):
    result, commands = run_script(service, extra={"PULL_FAILURES": "99"})
    assert result.returncode != 0
    assert len([c for c in commands if c[0] == "pull"]) == 3
    assert not any(c[:2] == ["pod", "create"] or c[0] == "run" for c in commands)
    assert "unexpected EOF" in result.stderr
    assert "local-dev/README.md#image-pull-fails-with-unexpected-eof" in result.stderr


def test_interrupted_pull_retries_before_creating_pod(run_script):
    result, commands = run_script("mlflow", extra={"PULL_FAILURES": "1"})
    assert result.returncode == 0, result.stderr
    pulls = [i for i, c in enumerate(commands) if c[0] == "pull"]
    create = next(i for i, c in enumerate(commands) if c[:2] == ["pod", "create"])
    assert len(pulls) == 2 and max(pulls) < create
    assert "--pull=never" in next(c for c in commands if c[0] == "run")


def test_cached_image_avoids_pull(run_script):
    result, commands = run_script("mlflow", extra={"CACHED_IMAGE": "1"})
    assert result.returncode == 0, result.stderr
    assert not any(c[0] == "pull" for c in commands)


def test_engine_pull_requests_configured_platform(run_script):
    result, commands = run_script("fluxnova")
    assert result.returncode == 0, result.stderr
    pull = next(
        c for c in commands if c[0] == "pull" and "fluxnova-edd-platform" in c[-1]
    )
    assert pull[pull.index("--platform") + 1] == "linux/amd64"


def test_new_pod_is_cleaned_up_on_port_conflict(run_script):
    result, commands = run_script(
        "mlflow", extra={"RUN_ERROR": "listen tcp :15000: bind: address already in use"}
    )
    assert result.returncode != 0
    assert "MLFLOW_PORT" in result.stderr and "15000" in result.stderr
    assert ["pod", "rm", "--force", "mlflow-local"] in commands
    assert not any(c[0] == "volume" and "rm" in c for c in commands)
    # A subsequent invocation can recreate the pod after the conflict is corrected.
    result, _ = run_script("mlflow")
    assert result.returncode == 0, result.stderr


def test_existing_pod_port_conflict_is_diagnosed_without_deleting_it(run_script):
    result, commands = run_script(
        "mlflow",
        extra={
            "EXISTING_POD": "1",
            "START_ERROR": "listen tcp :15000: bind: address already in use",
        },
    )
    assert result.returncode != 0
    assert "MLFLOW_PORT" in result.stderr
    assert not any(c[:2] == ["pod", "rm"] for c in commands)


def test_existing_old_port_requires_recreation_before_start(run_script):
    result, commands = run_script(
        "mlflow",
        mlflow_port=None,
        extra={"EXISTING_POD": "1", "EXISTING_MLFLOW_PORT": "5000"},
    )
    assert result.returncode != 0
    assert "5000" in result.stderr and "MLFLOW_PORT=5001" in result.stderr
    assert "Recreate" in result.stderr
    assert not any(c[:2] in (["pod", "start"], ["pod", "rm"]) for c in commands)


def test_incomplete_existing_pod_gets_recovery_command(run_script):
    result, commands = run_script(
        "mlflow", extra={"EXISTING_POD": "1", "INCOMPLETE_POD": "1"}
    )
    assert result.returncode != 0
    assert "podman pod rm --force 'mlflow-local'" in result.stderr
    assert not any(c[:2] == ["pod", "rm"] for c in commands)


def test_healthy_existing_pod_does_not_pull_or_recreate(run_script):
    result, commands = run_script("mlflow", extra={"EXISTING_POD": "1"})
    assert result.returncode == 0, result.stderr
    assert not any(c[0] in ("pull", "run") or c[:2] == ["pod", "rm"] for c in commands)


def test_changed_experiment_requires_recreation_before_restarting(run_script):
    result, commands = run_script("mlflow", extra={"EXISTING_POD": "1", "EVAL_SERVICE_EXPERIMENT_NAME": "trace-v2"})
    assert result.returncode != 0
    assert "trace-v2" in result.stderr and "Restarting does not apply" in result.stderr
    assert "podman pod rm --force 'mlflow-local'" in result.stderr
    assert not any(c[:2] in (["pod", "start"], ["pod", "rm"]) for c in commands)


def test_exited_container_fails_http_readiness_with_startup_logs(run_script):
    result, commands = run_script("mlflow", extra={"EXITED_CONTAINER": "1", "LOG_MESSAGE": "Experiment uses container-local artifact storage; choose a fresh name"})
    assert result.returncode != 0
    assert "exit=1" in result.stderr and "choose a fresh name" in result.stderr
    assert not any(c[0] == "exec" for c in commands)


def test_exit_between_http_and_bootstrap_file_is_reported_once(run_script):
    result, commands = run_script("mlflow", extra={"HEADER_NOT_READY": "1", "EXIT_AFTER_EXEC": "1", "LOG_MESSAGE": "bootstrap failed: legacy artifact path"})
    assert result.returncode != 0
    assert "legacy artifact path" in result.stderr and "exit=1" in result.stderr
    assert "container state improper" not in result.stderr
    assert len([c for c in commands if c[0] == "exec"]) == 1


@pytest.mark.parametrize("service, extra", [
    ("mlflow", {"EXISTING_POD": "1"}),
    ("eval-listener", {}),
])
def test_fixture_ignores_exported_developer_settings(run_script, monkeypatch, service, extra):
    for name, value in {
        "EVAL_SERVICE_EXPERIMENT_NAME": "fluxnova-loanAssessmentEvalProcess-v2",
        "EVAL_LISTENER_TRACKING_URI": "http://developer.invalid:9999",
        "MLFLOW_POD_NAME": "developer-mlflow",
        "MLFLOW_RUNTIME_VOLUME": "developer-runtime",
        "OLLAMA_CONTAINER_URL": "http://developer.invalid:11434",
        "POD_NAME": "developer-pod",
        "IMAGE_PULL_ATTEMPTS": "0",
        "START_ERROR": "inherited fake failure must not escape into another test",
    }.items():
        monkeypatch.setenv(name, value)
    result, commands = run_script(service, extra=extra)
    assert result.returncode == 0, result.stderr
    if service == "mlflow":
        assert ["pod", "start", "mlflow-local"] in commands
    else:
        run = next(command for command in commands if command[0] == "run")
        assert "EVAL_LISTENER_TRACKING_URI=http://mlflow-local:5000" in run
        assert "OLLAMA_API_BASE=http://host.containers.internal:11434" in run
