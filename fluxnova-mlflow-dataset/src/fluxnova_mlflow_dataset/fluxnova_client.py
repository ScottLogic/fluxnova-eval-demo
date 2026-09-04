"""Minimal read-only Fluxnova REST API client used by the ``collect`` step.

Collection never deploys or starts processes (that's ``fluxnova_runner``'s
job) — it only needs to read back a completed instance's final variables,
which MLflow's trace store doesn't carry (only span/tool-call data does).
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

    @staticmethod
    def _raise_for_status(response: requests.Response, action: str) -> None:
        if not response.ok:
            raise ApiError(f"Failed to {action}: HTTP {response.status_code} — {response.text}")
