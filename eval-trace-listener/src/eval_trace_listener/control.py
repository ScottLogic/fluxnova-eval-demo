"""Runtime control surface for the listener's sample rate.

`TraceListener` normally reads its settings once at startup (see `config.py`) —
but the whole point of a *sample rate* is to be able to dial it up/down while
the listener keeps running (e.g. from ui-api's evals.py router, driven by the
frontend's "Auto-eval (listener)" toggle), without restarting the process and
losing its in-memory dedup state. `SampleRateControl` is the thread-safe value
both the poll loop and this tiny HTTP server share; `start_control_server`
runs the server on a daemon thread so it never blocks `run_forever`.

Deliberately built on the standard library (`http.server`) rather than adding
a web framework dependency — the surface is two JSON routes on one value.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_PATH = "/config"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class SampleRateControl:
    """Thread-safe holder for the listener's current sample rate (0.0-1.0)."""

    def __init__(self, initial: float = 1.0) -> None:
        self._lock = threading.Lock()
        self._value = _clamp(initial)

    def get(self) -> float:
        with self._lock:
            return self._value

    def set(self, value: float) -> float:
        """Clamps to [0.0, 1.0] and returns the value actually stored."""
        with self._lock:
            self._value = _clamp(value)
            return self._value


def _make_handler(control: SampleRateControl) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - required BaseHTTPRequestHandler name
            if self.path.rstrip("/") == _CONFIG_PATH:
                self._send_json(200, {"sample_rate": control.get()})
            else:
                self._send_json(404, {"detail": "not found"})

        def do_PUT(self) -> None:  # noqa: N802 - required BaseHTTPRequestHandler name
            if self.path.rstrip("/") != _CONFIG_PATH:
                self._send_json(404, {"detail": "not found"})
                return
            length = int(self.headers.get("Content-Length") or "0")
            raw_body = self.rfile.read(length) if length else b"{}"
            try:
                parsed = json.loads(raw_body or b"{}")
                rate = float(parsed["sample_rate"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                self._send_json(
                    400, {"detail": "expected a JSON body like {\"sample_rate\": 0.5}"}
                )
                return
            applied = control.set(rate)
            logger.info("sample_rate set to %.3f via control endpoint", applied)
            self._send_json(200, {"sample_rate": applied})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            logger.debug("control endpoint: " + format, *args)

    return Handler


def start_control_server(control: SampleRateControl, host: str, port: int) -> ThreadingHTTPServer:
    """Starts the sample-rate control HTTP server on a daemon thread.

    Returns the server (mainly so tests/callers can call `.shutdown()`) —
    `run_forever`'s own loop doesn't need to hold a reference to it.
    """
    server = ThreadingHTTPServer((host, port), _make_handler(control))
    thread = threading.Thread(target=server.serve_forever, name="eval-listener-control", daemon=True)
    thread.start()
    logger.info("Sample-rate control endpoint listening on http://%s:%d%s", host, port, _CONFIG_PATH)
    return server
