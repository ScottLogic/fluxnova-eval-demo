"""Drives the `regression/` pytest suite out-of-process.

Deliberately shells out to `pytest` as a subprocess (via `python -m pytest`) rather
than importing/calling into the suite in-process — the suite depends on
`fluxnova-runner`/`fluxnova-mlflow-dataset` and drives a live agent run per golden,
so isolating it in its own process keeps a slow/hanging run from ever affecting
ui-api itself, and lets several runs be tracked independently by run id.

Requires the `pytest-json-report` plugin (see `regression/requirements.txt`) so a
run's per-test pass/fail/timing can be read back from a structured file instead of
scraping console output.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

def _default_regression_dir() -> Path:
    # ui-api/src/ui_api/regression_runner.py -> repo root is three levels up. This
    # only holds for an editable/source install (see ../../setup.sh) — once pip
    # installs ui-api as a normal (non-editable) package, this file's copy under
    # site-packages/ui_api/ no longer sits inside the repo checkout at all, so that
    # relative walk resolves to nonsense (e.g. /usr/local/lib/regression in the
    # ui-api container). The Docker image instead copies regression/ in directly and
    # sets UI_API_REGRESSION_DIR explicitly (see ui-api/Dockerfile) to sidestep this.
    return Path(__file__).resolve().parents[3] / "regression"


def _default_goldens_path() -> Path:
    # Mirrors _default_regression_dir()'s reasoning: this only resolves correctly
    # for an editable/source install, where repo root/datasets/ sits next to
    # repo root/regression/. The Docker image copies datasets/ in directly and
    # sets UI_API_GOLDENS_PATH explicitly (see ui-api/Dockerfile) to sidestep this.
    return REGRESSION_DIR.parent / "datasets" / "loan-assessment" / "goldens.json"


REGRESSION_DIR = Path(os.environ.get("UI_API_REGRESSION_DIR", str(_default_regression_dir())))
REGRESSION_TEST_FILE = REGRESSION_DIR / "test_mlflow_regression.py"
GOLDENS_PATH = Path(os.environ.get("UI_API_GOLDENS_PATH", str(_default_goldens_path())))

RunStatus = Literal["running", "passed", "failed", "error"]


def _python() -> str:
    # The regression suite needs fluxnova-runner/fluxnova-mlflow-dataset installed —
    # point this at the repo's shared .venv (see ../../setup.sh) if ui-api itself
    # isn't running from that same environment.
    return os.environ.get("UI_API_REGRESSION_PYTHON", sys.executable)


def list_tests() -> list[str]:
    """Returns pytest node ids for the regression suite, via `pytest --collect-only`."""
    result = subprocess.run(
        [_python(), "-m", "pytest", "--collect-only", "-q", REGRESSION_TEST_FILE.name],
        cwd=REGRESSION_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    prefix = f"{REGRESSION_TEST_FILE.name}::"
    return [line.strip() for line in result.stdout.splitlines() if line.startswith(prefix)]

def list_goldens() -> list[dict[str, Any]]:
    """Returns the raw contents of the loan-assessment golden dataset."""
    return json.loads(GOLDENS_PATH.read_text(encoding="utf-8"))


@dataclass
class _Run:
    process: subprocess.Popen
    report_path: Path
    output_path: Path
    started_at: float


_runs: dict[str, _Run] = {}
_runs_lock = threading.Lock()


def start_run() -> str:
    """Starts a regression run in the background and returns its run id."""
    run_id = uuid.uuid4().hex
    tmp_dir = Path(tempfile.gettempdir()) / "ui-api-regression"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    report_path = tmp_dir / f"{run_id}.json"
    output_path = tmp_dir / f"{run_id}.log"

    output_file = output_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            _python(),
            "-m",
            "pytest",
            "-v",
            REGRESSION_TEST_FILE.name,
            "--json-report",
            f"--json-report-file={report_path}",
        ],
        cwd=REGRESSION_DIR,
        stdout=output_file,
        stderr=subprocess.STDOUT,
    )
    with _runs_lock:
        _runs[run_id] = _Run(process, report_path, output_path, time.time())
    return run_id


def get_run(run_id: str) -> dict[str, Any] | None:
    """Returns the current status/result of a run, or None if run_id is unknown."""
    with _runs_lock:
        run = _runs.get(run_id)
    if run is None:
        return None

    exit_code = run.process.poll()
    if exit_code is None:
        return {"runId": run_id, "status": "running"}

    if run.report_path.exists():
        report = json.loads(run.report_path.read_text(encoding="utf-8"))
        tests = [
            {
                "nodeId": test["nodeid"],
                "outcome": test["outcome"],
                "durationSeconds": test.get("call", {}).get("duration"),
            }
            for test in report.get("tests", [])
        ]
        status: RunStatus = "passed" if exit_code == 0 else "failed"
        return {
            "runId": run_id,
            "status": status,
            "exitCode": exit_code,
            "summary": report.get("summary", {}),
            "tests": tests,
        }

    # Process exited before writing a report — a collection error or crash rather
    # than a normal test failure. Surface the captured console output instead.
    output = run.output_path.read_text(encoding="utf-8", errors="replace") if run.output_path.exists() else ""
    return {
        "runId": run_id,
        "status": "error",
        "exitCode": exit_code,
        "output": output[-4000:],
    }
