"""Minimal read-only Fluxnova REST client used by the eval workers and
``load_agent_run``: process variables, Call Activity child lookup, deployed
BPMN XML and run numbering. It never deploys or starts processes (that's
``fluxnova_runner``'s job).
"""

from __future__ import annotations

from typing import Any

import requests


class ApiError(Exception):
    """Raised when the Fluxnova REST API returns an unexpected response."""


class FluxnovaClient:
    """Thin, read-only wrapper around the Fluxnova Engine REST API."""

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        if username is not None or password is not None:
            self._session.auth = (username or "", password or "")

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

    def get_child_instance_id(self, parent_instance_id: str) -> str | None:
        """Return the process-instance id of the (single) child instance started
        by a Call Activity in ``parent_instance_id``, or ``None`` if there is none.

        Uses the *historic* process-instance API so it works after the child has
        already ended — which it always has by the time a downstream step (e.g.
        the eval service task) runs. A Call Activity spawns exactly one child
        instance, so the first match is returned; if the parent happens to have
        several (multiple call activities), the most recently started one wins.
        """
        response = self._session.get(
            f"{self._base}/history/process-instance",
            params={"superProcessInstanceId": parent_instance_id},
        )
        self._raise_for_status(response, "get child process instance")
        instances = response.json()
        if not instances:
            return None
        instances.sort(key=lambda item: item.get("startTime") or "", reverse=True)
        return instances[0]["id"]

    def get_process_definition_xml(self, instance_id: str) -> str:
        """Return the BPMN XML of the definition ``instance_id`` ran.

        Uses the historic process-instance API so it works after the instance
        ends, then reads the deployed definition's ``bpmn20Xml``.
        """
        response = self._session.get(f"{self._base}/history/process-instance/{instance_id}")
        self._raise_for_status(response, "get process instance")
        definition_id = response.json()["processDefinitionId"]
        response = self._session.get(f"{self._base}/process-definition/{definition_id}/xml")
        self._raise_for_status(response, "get process definition XML")
        return response.json()["bpmn20Xml"]

    def get_run_number(self, instance_id: str) -> int:
        """Return this instance's position among all runs of its process
        definition key, counting from 1 by start time.

        Read from the engine's history, so it survives worker restarts. It
        counts every version of the process, and resets only if that history
        is removed (e.g. by ``historyTimeToLive`` clean-up).
        """
        response = self._session.get(f"{self._base}/history/process-instance/{instance_id}")
        self._raise_for_status(response, "get process instance")
        instance = response.json()
        response = self._session.get(
            f"{self._base}/history/process-instance/count",
            params={
                "processDefinitionKey": instance["processDefinitionKey"],
                # Inclusive: counts every run started at or before this one.
                "startedBefore": instance["startTime"],
            },
        )
        self._raise_for_status(response, "count process instances")
        return int(response.json()["count"])

    @staticmethod
    def _raise_for_status(response: requests.Response, action: str) -> None:
        if not response.ok:
            raise ApiError(f"Failed to {action}: HTTP {response.status_code} — {response.text}")
