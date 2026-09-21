"""Client for eval-trace-listener's sample-rate control endpoint.

See `eval_trace_listener/control.py` — a tiny always-on HTTP surface the
listener runs alongside its poll loop so `sample_rate` can be changed live,
without restarting it. `evals.py`'s auto-eval toggle forwards here.
"""

from __future__ import annotations

import os

import requests


class ListenerControlError(Exception):
    """Raised when the listener's control endpoint can't be reached or errors."""


def _base_url() -> str:
    # eval-trace-listener runs in its own pod/container (see
    # local-dev/services/eval-listener-up.sh / compose.yaml's
    # eval-trace-listener-local), with its control port published on the host —
    # reachable via plain localhost since ui-api itself runs on --network host
    # (see local-dev/services/frontend-up.sh).
    return os.environ.get("UI_API_EVAL_LISTENER_URL", "http://localhost:8092").rstrip("/")


def get_sample_rate() -> float:
    try:
        response = requests.get(f"{_base_url()}/config", timeout=5)
        response.raise_for_status()
    except requests.RequestException as error:
        raise ListenerControlError(str(error)) from error
    return float(response.json()["sample_rate"])


def set_sample_rate(rate: float) -> float:
    try:
        response = requests.put(f"{_base_url()}/config", json={"sample_rate": rate}, timeout=5)
        response.raise_for_status()
    except requests.RequestException as error:
        raise ListenerControlError(str(error)) from error
    return float(response.json()["sample_rate"])
