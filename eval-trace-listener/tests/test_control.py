from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from eval_trace_listener.control import SampleRateControl, start_control_server


def test_sample_rate_control_clamps_to_0_1() -> None:
    control = SampleRateControl(initial=5.0)
    assert control.get() == 1.0
    assert control.set(-2.0) == 0.0
    assert control.get() == 0.0
    assert control.set(0.5) == 0.5


@pytest.fixture
def server():
    control = SampleRateControl(initial=1.0)
    httpd = start_control_server(control, "127.0.0.1", 0)  # port 0 -> OS picks a free one
    try:
        yield control, httpd.server_address[1]
    finally:
        httpd.shutdown()


def _get(port: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/config") as response:
        return json.loads(response.read())


def _put(port: int, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/config",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_get_config_returns_current_rate(server) -> None:
    _control, port = server
    assert _get(port) == {"sample_rate": 1.0}


def test_put_config_updates_rate_and_is_reflected_in_get(server) -> None:
    control, port = server
    status, body = _put(port, {"sample_rate": 0.25})
    assert status == 200
    assert body == {"sample_rate": 0.25}
    assert control.get() == 0.25
    assert _get(port) == {"sample_rate": 0.25}


def test_put_config_clamps_out_of_range_values(server) -> None:
    _control, port = server
    status, body = _put(port, {"sample_rate": 3.0})
    assert status == 200
    assert body == {"sample_rate": 1.0}


def test_put_config_rejects_malformed_body(server) -> None:
    _control, port = server
    status, body = _put(port, {"not_sample_rate": 1})
    assert status == 400
    assert "detail" in body


def test_unknown_path_returns_404(server) -> None:
    _control, port = server
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/nope")
    assert exc_info.value.code == 404
