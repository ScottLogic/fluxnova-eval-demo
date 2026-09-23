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

import ast
import json
import os
import re
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

def _docstrings_by_qualified_name(source_path: Path) -> dict[str, str]:
    """Maps ``"test_foo"``/``"SomeClass.test_foo"`` to that test's docstring.

    Reads docstrings directly from the test file's own AST rather than from
    pytest's ``-v`` console output — that output's indentation depth (used to
    tell a docstring's continuation lines apart from the next test) depends on
    how deeply pytest happens to nest this collection (module vs. class vs.
    directory), so parsing it is brittle to nesting or pytest/plugin version
    changes. The AST gives the same docstrings without depending on any of
    that.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    docstrings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    docstrings[f"{node.name}.{child.name}"] = ast.get_docstring(child) or ""
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            docstrings.setdefault(node.name, ast.get_docstring(node) or "")
    return docstrings


_DETERMINISTIC_CHECK_RE = re.compile(r"^test_agent_passes_deterministic_check\[(.+)\]$")


def _clean_docstring(doc: str | None) -> str:
    if not doc:
        return ""
    return " ".join(line.strip() for line in doc.strip().splitlines()).strip()


def _deterministic_scorer_docstring(scorer_name: str) -> str:
    """Looks up one deterministic scorer's own docstring by name.

    `test_agent_passes_deterministic_check` is parametrized once per scorer (see
    `regression/test_mlflow_regression.py`) so each reports pass/fail as its own
    line item, but they all share that one test function's docstring — this
    returns the *scorer's* own docstring instead, so each parametrized entry
    gets a description specific to what it actually checks (mirrors
    `ui_api.eval_definitions._describe`'s same fallback for the eval services).
    """
    from fluxnova_mlflow_dataset.scorers import ALL_DETERMINISTIC_SCORERS

    for scorer in ALL_DETERMINISTIC_SCORERS:
        if scorer.name == scorer_name:
            description = getattr(scorer, "description", None)
            if description:
                return description
            original_func = getattr(scorer, "_original_func", None)
            return _clean_docstring(getattr(original_func, "__doc__", None) if original_func else None)
    return ""


def list_tests() -> list[dict[str, str]]:
    """Returns one ``{name, description}`` entry per test in the regression suite.

    ``name`` is the pytest node id (from `pytest --collect-only -q`, the same
    structured/stable form the UI already used for run node ids elsewhere);
    ``description`` is that test's own docstring, read directly from the file's
    AST (see `_docstrings_by_qualified_name`) — except for the parametrized
    `test_agent_passes_deterministic_check[<scorer>]` entries, which use that
    scorer's own docstring instead (see `_deterministic_scorer_docstring`).
    """
    result = subprocess.run(
        [_python(), "-m", "pytest", "--collect-only", "-q", REGRESSION_TEST_FILE.name],
        cwd=REGRESSION_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    prefix = f"{REGRESSION_TEST_FILE.name}::"
    node_ids = [line.strip() for line in result.stdout.splitlines() if line.startswith(prefix)]

    docstrings = _docstrings_by_qualified_name(REGRESSION_TEST_FILE)
    tests = []
    for node_id in node_ids:
        qualified_name = node_id[len(prefix) :].replace("::", ".")
        deterministic_match = _DETERMINISTIC_CHECK_RE.match(qualified_name)
        if deterministic_match:
            description = _deterministic_scorer_docstring(deterministic_match.group(1))
        else:
            description = docstrings.get(qualified_name, "")
        tests.append({"name": node_id, "description": description})
    return tests

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


_INLINE_RESULT_RE = re.compile(r"^(?P<nodeid>\S+\.py::\S+)\s+(?P<outcome>PASSED|FAILED|ERROR|SKIPPED)\b")
_NODEID_ONLY_RE = re.compile(r"^(?P<nodeid>\S+\.py::\S+)\s*$")
_OUTCOME_ONLY_RE = re.compile(r"^(?P<outcome>PASSED|FAILED|ERROR|SKIPPED)\b")

# Matches the structured progress markers `evaluation_rows` logs (see
# regression/test_mlflow_regression.py) for the upfront pass that drives each
# golden through the live agent once, before any pytest test line appears.
_GOLDEN_START_RE = re.compile(r"Golden run starting (?P<index>\d+)/(?P<total>\d+): (?P<name>.+)$")
_GOLDEN_DONE_RE = re.compile(r"Golden run finished (?P<index>\d+)/(?P<total>\d+): (?P<name>.+)$")


def _parse_golden_progress(output_text: str) -> list[dict[str, Any]]:
    """Best-effort per-golden progress for the live-agent pass, parsed from the
    same in-progress console output `_parse_partial_results` reads.

    Returns one ``{name, status}`` entry per golden that's started, in the order
    it started, with ``status`` "running" until its matching finish line shows up.
    """
    progress: dict[str, str] = {}
    order: list[str] = []
    for raw_line in output_text.splitlines():
        line = raw_line.rstrip()
        start_match = _GOLDEN_START_RE.search(line)
        if start_match:
            name = start_match.group("name")
            if name not in progress:
                order.append(name)
            progress[name] = "running"
            continue
        done_match = _GOLDEN_DONE_RE.search(line)
        if done_match:
            progress[done_match.group("name")] = "done"

    return [{"name": name, "status": progress[name]} for name in order]


def _parse_partial_results(output_text: str, prefix: str) -> list[dict[str, Any]]:
    """Best-effort per-test outcomes parsed from pytest's live ``-v`` console
    output, so a run *in progress* can show what's happened so far instead of
    the UI going quiet until the whole suite finishes (the JSON report file
    only exists once the process has exited — see `get_run`).

    Handles both shapes pytest's console output takes: a plain
    ``"nodeid OUTCOME [ N%]"`` line when nothing else printed during the test,
    and — when ``log_cli`` output interleaves, as this suite's live per-golden
    logging does (see ``regression/pytest.ini``) — the nodeid alone on its own
    line, followed by the log lines, followed by a bare ``"OUTCOME [ N%]"``
    line once the test ends. Whichever nodeid started but has no outcome line
    yet is reported as ``"running"`` — the test currently executing.
    """
    outcomes: dict[str, str] = {}
    order: list[str] = []
    pending: str | None = None

    for raw_line in output_text.splitlines():
        line = raw_line.rstrip()
        inline_match = _INLINE_RESULT_RE.match(line)
        if inline_match and line.startswith(prefix):
            node_id = inline_match.group("nodeid")
            if node_id not in outcomes:
                order.append(node_id)
            outcomes[node_id] = inline_match.group("outcome").lower()
            pending = None
            continue

        nodeid_match = _NODEID_ONLY_RE.match(line)
        if nodeid_match and line.startswith(prefix):
            node_id = nodeid_match.group("nodeid")
            if node_id not in outcomes:
                order.append(node_id)
            outcomes.setdefault(node_id, "running")
            pending = node_id
            continue

        outcome_match = _OUTCOME_ONLY_RE.match(line)
        if outcome_match and pending:
            outcomes[pending] = outcome_match.group("outcome").lower()
            pending = None

    return [
        {"nodeId": node_id, "outcome": outcomes[node_id], "durationSeconds": None}
        for node_id in order
    ]


def get_run(run_id: str) -> dict[str, Any] | None:
    """Returns the current status/result of a run, or None if run_id is unknown."""
    with _runs_lock:
        run = _runs.get(run_id)
    if run is None:
        return None

    exit_code = run.process.poll()
    if exit_code is None:
        output = run.output_path.read_text(encoding="utf-8", errors="replace") if run.output_path.exists() else ""
        prefix = f"{REGRESSION_TEST_FILE.name}::"
        return {
            "runId": run_id,
            "status": "running",
            "tests": _parse_partial_results(output, prefix),
            "goldens": _parse_golden_progress(output),
        }

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
