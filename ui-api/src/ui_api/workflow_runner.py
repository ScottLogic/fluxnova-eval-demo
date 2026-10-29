"""Drives a Fluxnova workflow run via the `fluxnova-runner` client/config.

Unlike `regression_runner.py`, this calls `fluxnova_runner.client.Client` directly
in-process rather than shelling out — deploying a BPMN and starting a process
instance are just a couple of fast HTTP calls to Fluxnova, not a slow live-agent
test suite, so there's no need to isolate them in a subprocess.
"""

from __future__ import annotations

import os
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from fluxnova_mlflow_dataset.bpmn import BpmnLookup, BpmnLookupError
from fluxnova_runner.client import ApiError, Client
from fluxnova_runner.config import RunnerConfig
from fluxnova_runner.mock_workers import start_workers


def _default_config_path() -> Path:
    # ui-api/src/ui_api/workflow_runner.py -> repo root is three levels up. This
    # only holds for an editable/source install of ui-api itself (see
    # regression_runner.py's _default_regression_dir for the same caveat) — the
    # ui-api Docker image copies fluxnova-runner/ in directly and sets
    # UI_API_WORKFLOW_CONFIG explicitly.
    #
    # loan_approval_process_ai.yml/LoanApprovalProcess_AI.bpmn is the current
    # workflow — the older loan-assesment(-eval).yml/.bpmn files are deprecated.
    return (
        Path(__file__).resolve().parents[3]
        / "fluxnova-runner"
        / "config"
        / "loan_approval_process_ai.yml"
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


def _agent_bpmn_lookup(cfg: RunnerConfig) -> BpmnLookup:
    """Find the BPMN file that actually declares the ad-hoc subprocess's ``agent:config``.

    ``cfg.bpmn_path`` is often the *outer* process — the agent-bearing subprocess
    can instead live in one of ``additional_bpmn_paths``, reached via a Call
    Activity (e.g. ``loan_approval_process_ai.yml``'s ``bpmn_path`` is
    ``LoanApprovalProcess_AI.bpmn``, but the ad-hoc subprocess itself is declared
    in ``additional_bpmn_paths``' ``loan-assesment.bpmn``). Tries every candidate
    file in order and returns the first one that actually has the subprocess.
    """
    # BpmnLookup's constructor only parses the file — it doesn't validate that
    # the subprocess actually lives there (that's checked lazily, by whichever
    # of system_prompt()/provider()/model() gets called first), so trying each
    # candidate must explicitly check has_subprocess() before returning it,
    # rather than just catching a constructor error that never comes.
    for path in (cfg.bpmn_path, *cfg.additional_bpmn_paths):
        lookup = BpmnLookup(path, cfg.subprocess_id)
        if lookup.has_subprocess():
            return lookup
    raise BpmnLookupError(
        f"No adHocSubProcess with id {cfg.subprocess_id!r} in {cfg.bpmn_path} or its additional_bpmn_paths"
    )


def _agent_config(cfg: RunnerConfig) -> dict[str, str] | None:
    """Returns the agent's ``{provider, model, systemPrompt}`` as authored on the
    BPMN, or ``None`` if the config has no agent subprocess or it can't be found.

    This reflects what's *authored* in the BPMN — it may not be the actual
    runtime model if the engine's own model-provider config overrides it.
    """
    if not cfg.subprocess_id:
        return None
    try:
        lookup = _agent_bpmn_lookup(cfg)
        return {
            "provider": lookup.provider(),
            "model": lookup.model(),
            "systemPrompt": lookup.system_prompt(),
        }
    except BpmnLookupError:
        return None


def get_config() -> dict[str, Any]:
    """Returns the default process variables a run starts with, for a form to
    pre-populate and selectively override (the "random input" a caller can
    edit), plus the agent's model/provider/prompt as authored on the BPMN."""
    cfg = _load_config()
    return {
        "processKey": cfg.process_key,
        "variables": cfg.variables,
        "agentConfig": _agent_config(cfg),
    }


def start_run(variable_overrides: dict[str, Any] | None = None) -> str:
    """Deploys the configured BPMN, starts mock workers, starts a process instance.

    `variable_overrides` are merged over the config file's default `variables` —
    keys not given keep their config default (the "random input" a caller can
    selectively edit, including `skipEvalServiceWorker` — see
    `bpmn/LoanApprovalProcess_AI.bpmn`'s `Gateway_SkipEvalServiceWorker`).
    """
    cfg = _load_config()
    client = _client(cfg)

    with suppress(ApiError):  # best-effort stale-lock cleanup
        client.unlock_stale_external_tasks()

    # The deployment API reuses unchanged resources and versions changed BPMN.
    # Cascading deletion here would erase earlier runs, history and human tasks
    # every time the UI starts another workflow. Cleanup must be explicit.
    client.deploy(
        cfg.bpmn_path,
        deployment_name=cfg.deployment_name,
        additional_paths=cfg.additional_bpmn_paths,
    )

    _ensure_mock_workers(cfg)

    variables = {**cfg.variables, **(variable_overrides or {})}
    return client.start_process(cfg.process_key, variables)


# Activity types worth showing as their own "stage" row — everything else
# (gateways, sequence flows) is just BPMN routing logic, not a step a user
# watching a run would consider a distinct stage. Matched case-insensitively by
# substring since Camunda's own casing varies (`serviceTask`, `noneEndEvent`,
# `startEvent`, `adHocSubProcess`, ...); `callActivity` doesn't contain any of
# these substrings so it's checked for explicitly.
_STAGE_ACTIVITY_TYPE_MARKERS = ("task", "subprocess", "startevent", "endevent")


def _is_stage_activity(activity_type: str | None) -> bool:
    if not activity_type:
        return False
    lowered = activity_type.lower()
    return lowered == "callactivity" or any(marker in lowered for marker in _STAGE_ACTIVITY_TYPE_MARKERS)


def _stages_for(client: Client, instance_id: str) -> list[dict[str, Any]]:
    """Build the ordered, filtered stage list for one process instance.

    Recurses into a Call Activity's own called process instance (via that
    activity's `calledProcessInstanceId`, present once it's started) so its
    inner steps nest under that row — e.g. the agent's individual tool calls,
    which actually run inside a *separate* process instance
    (`loanAssessmentProcess`) spawned by the outer process's
    `AgentTask_CreditRisk` Call Activity, not the outer instance itself
    (confirmed against a real run: `/history/activity-instance` on the outer
    instance only ever shows the Call Activity as one row; the tool-call-level
    detail lives on the called instance's own history).
    """
    stages = []
    for activity in client.get_activity_instances(instance_id):
        if not _is_stage_activity(activity.get("activityType")):
            continue
        stage: dict[str, Any] = {
            "activityId": activity["activityId"],
            "name": activity.get("activityName") or activity["activityId"],
            "startTime": activity.get("startTime"),
            "endTime": activity.get("endTime"),
        }
        called_instance_id = activity.get("calledProcessInstanceId")
        if called_instance_id:
            stage["children"] = _stages_for(client, called_instance_id)
        stages.append(stage)
    stages.sort(key=lambda stage: stage["startTime"] or "")
    return stages


def get_run(instance_id: str) -> dict[str, Any]:
    """Returns the current status, variables, and stage progress of a run.

    Variables are included even while `status` is "active" — e.g. once the
    ad-hoc agent subprocess finishes but the outer process is still waiting on
    the (possibly skipped) eval step or a later human review task — using the
    historic variable-instance query, which reflects current values regardless
    of whether the instance has ended. `stages` is included in every status —
    even once the run has finished, so the stage list stays visible as a
    record of what happened rather than disappearing.
    """
    cfg = _load_config()
    client = _client(cfg)

    if client.get_instance(instance_id) is not None:
        return {
            "instanceId": instance_id,
            "status": "active",
            "variables": client.get_variables(instance_id),
            "stages": _stages_for(client, instance_id),
        }

    history = client.get_history(instance_id)
    state = history.get("state", "UNKNOWN")
    status = "completed" if state == "COMPLETED" else "terminated" if state == "EXTERNALLY_TERMINATED" else "error"
    return {
        "instanceId": instance_id,
        "status": status,
        "state": state,
        "variables": client.get_variables(instance_id),
        "stages": _stages_for(client, instance_id),
    }
