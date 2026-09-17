"""Drives a Fluxnova workflow run via the `fluxnova-runner` client/config.

Unlike `regression_runner.py`, this calls `fluxnova_runner.client.Client` directly
in-process rather than shelling out — deploying a BPMN and starting a process
instance are just a couple of fast HTTP calls to Fluxnova, not a slow live-agent
test suite, so there's no need to isolate them in a subprocess.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from fluxnova_runner.client import ApiError, Client
from fluxnova_runner.config import RunnerConfig
from fluxnova_runner.mock_workers import start_workers


def _default_config_path() -> Path:
    # ui-api/src/ui_api/workflow_runner.py -> repo root is three levels up. This
    # only holds for an editable/source install of ui-api itself (see
    # regression_runner.py's _default_regression_dir for the same caveat) — the
    # ui-api Docker image copies fluxnova-runner/ in directly and sets
    # UI_API_WORKFLOW_CONFIG explicitly.
    return (
        Path(__file__).resolve().parents[3]
        / "fluxnova-runner"
        / "config"
        / "loan-assesment.yml"
    )


CONFIG_PATH = Path(os.environ.get("UI_API_WORKFLOW_CONFIG", str(_default_config_path())))

_mock_workers_started = False
_mock_workers_lock = threading.Lock()


def _load_config() -> RunnerConfig:
    return RunnerConfig.from_file(CONFIG_PATH)


def _client(cfg: RunnerConfig) -> Client:
    return Client(
        base_url=cfg.fluxnova_url,
        username=os.environ.get("FLUXNOVA_USERNAME"),
        password=os.environ.get("FLUXNOVA_PASSWORD"),
    )


def _ensure_mock_workers(cfg: RunnerConfig) -> None:
    """Starts the config's mock external-task workers once per ui-api process.

    Mock worker threads subscribe forever and answer whichever matching external
    task shows up, so they only need starting once — not per run (starting a fresh
    set for every run would just have several threads race for the same task).
    """
    global _mock_workers_started
    if _mock_workers_started:
        return
    with _mock_workers_lock:
        if _mock_workers_started:
            return
        start_workers(
            cfg,
            username=os.environ.get("FLUXNOVA_USERNAME"),
            password=os.environ.get("FLUXNOVA_PASSWORD"),
        )
        _mock_workers_started = True


def start_run(variable_overrides: dict[str, Any] | None = None) -> str:
    """Deploys the configured BPMN, starts mock workers, starts a process instance.

    `variable_overrides` are merged over the config file's default `variables` —
    keys not given keep their config default (the "random input" a caller can
    selectively edit).
    """
    cfg = _load_config()
    client = _client(cfg)

    try:
        client.unlock_stale_external_tasks()
    except ApiError:
        pass  # best-effort cleanup, same as fluxnova-run's CLI

    if cfg.deployment_name:
        try:
            client.delete_deployments_by_name(cfg.deployment_name)
        except ApiError:
            pass  # best-effort clean redeploy, same as fluxnova-run's CLI
    client.deploy(
        cfg.bpmn_path,
        deployment_name=cfg.deployment_name,
        additional_paths=cfg.additional_bpmn_paths,
    )

    _ensure_mock_workers(cfg)

    variables = {**cfg.variables, **(variable_overrides or {})}
    return client.start_process(cfg.process_key, variables)


def get_run(instance_id: str) -> dict[str, Any]:
    """Returns the current status (and, once ended, final variables) of a run."""
    cfg = _load_config()
    client = _client(cfg)

    if client.get_instance(instance_id) is not None:
        return {"instanceId": instance_id, "status": "active"}

    history = client.get_history(instance_id)
    state = history.get("state", "UNKNOWN")
    status = "completed" if state == "COMPLETED" else "terminated" if state == "EXTERNALLY_TERMINATED" else "error"
    return {
        "instanceId": instance_id,
        "status": status,
        "state": state,
        "variables": client.get_variables(instance_id),
    }
