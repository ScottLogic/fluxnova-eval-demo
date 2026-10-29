"""Complete one local eval task with a controlled failure and verify human review.

Stop container and host eval workers first. This checks BPMN routing, not whether
the LLM judged a response correctly. Only the named parent's eval task is modified.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import requests

REVIEW_TASK = "UserTask_ReviewFailedEval"
VALIDATION_WORKER = "local-route-validation"
EVAL_WORKER = "eval-service-worker"


def require_stopped_worker(container: str = EVAL_WORKER) -> None:
    exists = subprocess.run(["podman", "container", "exists", container], capture_output=True, text=True, timeout=10, check=False)
    if exists.returncode == 1:
        return
    if exists.returncode:
        raise RuntimeError("Cannot check Podman worker state: " + exists.stderr)
    state = subprocess.run(["podman", "inspect", "--format", "{{.State.Status}}", container],
                           capture_output=True, text=True, timeout=10, check=False)
    if state.returncode or state.stdout.strip() not in {"exited", "stopped", "created", "configured"}:
        raise RuntimeError(f"Stop the eval worker before changing task ownership: podman stop {container}. Also stop any host copy.")


def check_review_route(session, base_url: str, parent_id: str, *,
                       ensure_worker_stopped=require_stopped_worker, timeout: float = 30) -> dict:
    base = base_url.rstrip("/")

    def call(method, path, **kwargs):
        response = session.request(method, base + path, timeout=15, **kwargs)
        if not response.ok:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text}")
        return response.json() if response.content else None

    def user_tasks():
        return call("GET", "/task", params={"processInstanceId": parent_id})

    tasks = user_tasks()
    if any(task["taskDefinitionKey"] == REVIEW_TASK for task in tasks):
        return {"status": "passed", "process_instance_id": parent_id, "user_task": REVIEW_TASK,
                "already_at_review": True}
    if tasks:
        raise RuntimeError("This process already reached another user task; start a fresh controlled eval instance.")
    ensure_worker_stopped()
    deadline = time.monotonic() + timeout
    while True:
        pending = call("GET", "/external-task", params={"processInstanceId": parent_id, "topicName": "agent-output-eval"})
        if pending:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f"No pending evaluation task for parent {parent_id}")
        time.sleep(0.5)
    if len(pending) != 1:
        raise RuntimeError(f"Expected one evaluation task for parent {parent_id}; found {len(pending)}")
    task = pending[0]
    if (task.get("processInstanceId") != parent_id or task.get("topicName") != "agent-output-eval"
            or task.get("activityId") != "ServiceTask_EvaluateAgentOutput"
            or task.get("processDefinitionKey") != "loanAssessmentEvalProcess"):
        raise RuntimeError("Refusing to change an unrelated process/task")
    owner = task.get("workerId")
    if owner not in {None, EVAL_WORKER, VALIDATION_WORKER}:
        raise RuntimeError(f"Task is owned by unrelated worker {owner!r}; its lock was left untouched")
    path = f"/external-task/{task['id']}"
    if owner:
        # A stopped worker's lease/pending long poll can outlive its process.
        # Reclaim only this verified task, never unlock all outstanding tasks.
        call("POST", path + "/unlock")
    call("POST", path + "/lock", json={"workerId": VALIDATION_WORKER, "lockDuration": 60000})
    call("POST", path + "/complete", json={"workerId": VALIDATION_WORKER, "variables": {
        "evalPassed": {"value": False, "type": "Boolean"},
        "evalRationale": {"value": "Controlled validation of human-review routing", "type": "String"},
    }})
    while True:
        if any(item["taskDefinitionKey"] == REVIEW_TASK for item in user_tasks()):
            return {"status": "passed", "process_instance_id": parent_id, "user_task": REVIEW_TASK,
                    "reclaimed_from": owner, "external_task_id": task["id"]}
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Parent {parent_id} did not reach {REVIEW_TASK}")
        time.sleep(0.5)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[1] / "local-dev/.env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("process_instance_id", help="Parent loanAssessmentEvalProcess instance ID")
    parser.add_argument("--fluxnova-url", default=os.environ.get("FLUXNOVA_URL", "http://localhost:8080/engine-rest"))
    args = parser.parse_args()
    with requests.Session() as session:
        username, password = os.environ.get("FLUXNOVA_USERNAME"), os.environ.get("FLUXNOVA_PASSWORD")
        if username or password:
            session.auth = (username or "", password or "")
        print(json.dumps(check_review_route(session, args.fluxnova_url, args.process_instance_id), indent=2))


if __name__ == "__main__":
    main()
