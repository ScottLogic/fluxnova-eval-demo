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

    @staticmethod
    def _raise_for_status(response: requests.Response, action: str) -> None:
        if not response.ok:
            raise ApiError(f"Failed to {action}: HTTP {response.status_code} — {response.text}")
