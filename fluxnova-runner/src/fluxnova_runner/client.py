"""Fluxnova REST API client for the automated-run service.

Provides only what the runner needs:
- Deploying a BPMN file
- Starting a process instance
- Claiming/completing user tasks (used indirectly via mock workers)
- Polling until the instance completes

(Read-back of agent-history/report data is ``mlflow-eval --collect``'s job —
see ``fluxnova_mlflow_dataset.fluxnova_client.FluxnovaClient``.)
"""

import time
from pathlib import Path
from typing import Any

import requests


class ApiError(Exception):
    """Raised when the Fluxnova REST API returns an unexpected response."""


class Client:
    """Thin wrapper around the Fluxnova Engine REST API."""

    def __init__(
            self,
            base_url: str,
            root: Path | None = None,
            username: str | None = None,
            password: str | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._root = root or Path.cwd()
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        if username is not None or password is not None:
            self._session.auth = (username or "", password or "")

    def deploy(self, bpmn_path: Path, deployment_name: str) -> dict[str, Any]:
        """Deploy a BPMN file and return the deployment resource.

        Args:
            bpmn_path: Path to the .bpmn file, relative to the client root directory.
            deployment_name: Human-readable name shown in Fluxnova Cockpit.

        Returns:
            The deployment response dict from Fluxnova.
        """
        name = deployment_name
        resolved = self._root / bpmn_path
        with resolved.open("rb") as fh:
            response = self._session.post(
                f"{self._base}/deployment/create",
                data={"deployment-name": name, "enable-duplicate-filtering": "true"},
                files={"upload": (resolved.name, fh, "application/octet-stream")},
                headers={"Content-Type": None},  # type: ignore[arg-type]
            )
        self._raise_for_status(response, "deploy BPMN")
        return response.json()

    def start_process(
            self,
            process_key: str,
            variables: dict[str, Any] | None = None,
    ) -> str:
        """Start a new process instance and return its instance ID.

        Args:
            process_key: The process definition key (``id`` attribute on
                         ``<process>`` in the BPMN).
            variables: Initial process variables as a plain Python dict.
                       Values are automatically wrapped in Camunda variable format.

        Returns:
            The new process instance ID.
        """
        body: dict[str, Any] = {}
        if variables:
            body["variables"] = _to_camunda_vars(variables)

        response = self._session.post(
            f"{self._base}/process-definition/key/{process_key}/start",
            json=body,
        )
        self._raise_for_status(response, "start process")
        return response.json()["id"]

    def claim_task(self, task_id: str, user_id: str) -> dict[str, Any]:
        """Claim a task and return its instance ID."""
        response = self._session.post(
            url=f"{self._base}/task/{task_id}/claim",
            data={"userId": user_id},
            headers={"Content-Type": "application/json"}
        )
        self._raise_for_status(response, "claim a task")
        return response.json()

    def complete_task(self, task_id: str, variables) -> dict[str, Any]:
        """Complete a task and return its instance ID."""
        response = self._session.post(
            url=f"{self._base}/task/{task_id}/complete",
            data={"variables": variables,
                  "withVariablesInReturn": True
                  },
            headers={"Content-Type": "application/json"}
        )
        self._raise_for_status(response, "complete a task")
        return response.json()

    def get_instance(self, instance_id: str) -> dict[str, Any] | None:
        """Return the process instance dict, or *None* if it has ended."""
        response = self._session.get(f"{self._base}/process-instance/{instance_id}")
        if response.status_code == 404:
            return None
        self._raise_for_status(response, "get process instance")
        return response.json()

    def get_history(self, instance_id: str) -> dict[str, Any]:
        """Return the historic process instance (always available, even after completion)."""
        response = self._session.get(f"{self._base}/history/process-instance/{instance_id}")
        self._raise_for_status(response, "get historic process instance")
        return response.json()

    def get_variables(self, instance_id: str) -> dict[str, Any]:
        """Return the current (or final) variables for an instance.

        Queries the historic variable API so this works after the instance ends.
        Returns a plain Python dict of ``{name: value}``.
        """
        response = self._session.get(
            f"{self._base}/history/variable-instance",
            params={"processInstanceId": instance_id},
        )
        self._raise_for_status(response, "get variables")
        return {item["name"]: item["value"] for item in response.json()}

    # ------------------------------------------------------------------
    # Polling helper
    # ------------------------------------------------------------------

    def wait_for_completion(
            self,
            instance_id: str,
            poll_interval: float = 2.0,
            timeout: float = 300.0,
    ) -> dict[str, Any]:
        """Block until the process instance finishes, then return its final variables.

        Args:
            instance_id: The process instance ID to monitor.
            poll_interval: Seconds between status checks.
            timeout: Maximum seconds to wait before raising ``TimeoutError``.

        Returns:
            A plain Python dict of final process variables.

        Raises:
            TimeoutError: If the instance has not completed within *timeout* seconds.
            ApiError: If the instance ended with an error/incident state.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            instance = self.get_instance(instance_id)
            if instance is None:
                # Instance no longer active — check historic record
                history = self.get_history(instance_id)
                state = history.get("state", "UNKNOWN")
                if state not in {"COMPLETED", "EXTERNALLY_TERMINATED"}:
                    raise ApiError(f"Process instance {instance_id} ended in state '{state}'")
                return self.get_variables(instance_id)
            time.sleep(poll_interval)

        raise TimeoutError(f"Process instance {instance_id} did not complete within {timeout}s")

    def wait_for_activity_completion(
            self,
            instance_id: str,
            activity_id: str,
            poll_interval: float = 2.0,
            timeout: float = 300.0,
    ) -> dict[str, Any]:
        """Block until one activity (e.g. an ad-hoc subprocess) within the process
        instance finishes, then return its historic activity-instance record.

        Unlike :meth:`wait_for_completion`, this returns as soon as the named
        activity itself ends — regardless of whether the overall process
        instance is still running (e.g. still has a downstream eval service
        task/gateway left to execute).

        Args:
            instance_id: The process instance ID to monitor.
            activity_id: The BPMN element ID to wait on (the ``id`` attribute
                         on the element in the BPMN, e.g.
                         ``AdHocSubProcess_LoanAssessmentAgent``).
            poll_interval: Seconds between status checks.
            timeout: Maximum seconds to wait before raising ``TimeoutError``.

        Returns:
            The historic activity-instance dict for the finished activity
            (includes ``activityInstanceId``, ``startTime``, ``endTime``, etc.).

        Raises:
            TimeoutError: If the activity has not finished within *timeout* seconds.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self._session.get(
                f"{self._base}/history/activity-instance",
                params={
                    "processInstanceId": instance_id,
                    "activityId": activity_id,
                    "finished": "true",
                },
            )
            self._raise_for_status(response, "get historic activity instance")
            instances = response.json()
            if instances:
                return instances[0]
            time.sleep(poll_interval)

        raise TimeoutError(
            f"Activity '{activity_id}' on process instance {instance_id} did not "
            f"finish within {timeout}s"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _raise_for_status(response: requests.Response, action: str) -> None:
        if not response.ok:
            raise ApiError(f"Failed to {action}: HTTP {response.status_code} — {response.text}")


def _to_camunda_vars(variables: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Convert a plain dict to Camunda variable format.

    Each value is wrapped as ``{"value": ..., "type": ...}``.
    Supported Python types: str, int, float, bool.
    Everything else is serialised as a String.
    """
    _type_map = {
        str: "String",
        int: "Integer",
        float: "Double",
        bool: "Boolean",
    }
    result = {}
    for name, value in variables.items():
        camunda_type = _type_map.get(type(value), "String")
        result[name] = {"value": value, "type": camunda_type}
    return result
