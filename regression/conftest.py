"""pytest configuration for the regression suite.

The ``@mlflow.test`` plugin (enabled via ``-p mlflow.pytest.plugin`` in
``addopts``) opens the test's MLflow run *before* the test body runs, using
whatever tracking store and experiment are configured at that moment. If those
were only selected inside the test body, the run would already be open in the
ambient local ``./mlruns`` store and get orphaned once the body switched to the
shared Postgres store — breaking ``evaluate()``'s dataset logging with
``Run not found``.

Selecting the store + experiment here, in ``pytest_configure`` (which runs
before any test call), ensures the plugin opens the run directly against the
shared MLflow tracking *server* (HTTP, ``default_server_tracking_uri()``) under
the dedicated regression experiment. Going through the server rather than
connecting to Postgres directly means the server owns the DB schema, so the
client never runs MLflow's strict SqlAlchemyStore schema-version check — which
otherwise makes the suite skip with "Detected out-of-date database schema"
whenever the server image and the client ``mlflow`` version drift apart (their
Alembic heads differ). ``setdefault`` leaves any externally-provided override
(e.g. a CI-provided ``MLFLOW_TRACKING_URI``) intact, and only sets env — it does
not touch the store — so an unreachable server still skips cleanly inside the
test rather than erroring during collection.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# litellm (a fluxnova-mlflow-dataset dependency) calls `load_dotenv()` on import, but with no
# path that only finds a ".env" in/above the current working directory — not this repo's actual
# single source of truth, `local-dev/.env` (the file podman-compose reads OPENAI_API_KEY etc.
# from). Load it explicitly here, before anything reads OPENAI_API_KEY, so the OpenAI-backed
# judge scorers (see fluxnova_mlflow_dataset.scorers) work from a plain `pytest regression` too.
# `override=False` (load_dotenv's default) leaves a real shell-exported value alone.
load_dotenv(Path(__file__).resolve().parent.parent / "local-dev" / ".env")

from fluxnova_mlflow_dataset import default_server_tracking_uri, experiment_name_for  # noqa: E402
from fluxnova_mlflow_dataset.scorers import LLM_JUDGE_PROVIDER  # noqa: E402

# Third-party loggers that emit chatty INFO/DEBUG output on their own named
# loggers. With live logging enabled (log_cli in pyproject.toml) these would
# drown out the suite's own progress lines, so cap them to WARNING while leaving
# the root/our loggers free to report INFO progress.
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "litellm",
    "LiteLLM",
    "mlflow",
    "openai",
)


class _DropMlflowTypeHintNoise(logging.Filter):
    """Drop MLflow's cosmetic "inferred as AnyType" type-hint warnings.

    When ``mlflow.genai.evaluate`` first imports ``mlflow.pyfunc``, MLflow
    infers a schema from its *own* ``ResponsesAgentRequest`` pydantic model
    (``mlflow/types/responses.py``), whose fields use multi-type Unions. That
    inference logs several ``Union type hint ... is inferred as AnyType`` /
    ``Any type hint is inferred as AnyType`` warnings on the
    ``mlflow.types.type_hints`` logger. They come entirely from MLflow internals
    (nothing in this repo), are purely informational, and would otherwise clutter
    every ``evaluate()`` run — so we filter just those messages.

    The filter is attached to the originating ``mlflow.types.type_hints`` logger
    rather than the root: a logger's filters only apply to records emitted *at*
    that logger, not to records propagated up from descendants.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "inferred as AnyType" not in record.getMessage()


class _DropCamundaNoise(logging.Filter):
    """Drop camunda's per-poll worker chatter.

    The camunda external-task client logs its "Fetching and Locking..." spam via
    ``logging.info`` (the *root* logger, not a ``camunda.*`` logger), so a plain
    ``setLevel`` on a named logger can't silence it. Filtering on the record's
    originating module drops that noise while leaving the suite's own INFO
    progress lines (and any other library's) intact.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "camunda" not in (record.pathname or "").lower()


def pytest_configure(config: pytest.Config) -> None:
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger().addFilter(_DropCamundaNoise())
    logging.getLogger("mlflow.types.type_hints").addFilter(_DropMlflowTypeHintNoise())

    os.environ.setdefault("MLFLOW_TRACKING_URI", default_server_tracking_uri())
    os.environ.setdefault(
        "MLFLOW_EXPERIMENT_NAME",
        experiment_name_for("loanAssessmentProcess-regression"),
    )
    # Serialize scoring: mlflow.genai.evaluate fans out every row's judge call
    # concurrently (MLFLOW_GENAI_EVAL_MAX_WORKERS defaults to 10). Against the
    # local CPU-bound Ollama judge (a single gemma4:e2b instance) those parallel
    # requests never get scheduled and every judge thread blocks forever in
    # socket.readinto with no client timeout, hanging the whole run. Capping to
    # one worker means one judge call hits Ollama at a time — the sequential path
    # that completes reliably. The default OpenAI judge (see
    # `fluxnova_mlflow_dataset.scorers.LLM_JUDGE_PROVIDER`) has no such
    # single-instance bottleneck, so it's safe to fan out there; still
    # overridable via env either way.
    os.environ.setdefault(
        "MLFLOW_GENAI_EVAL_MAX_WORKERS", "1" if LLM_JUDGE_PROVIDER == "ollama" else "10"
    )
