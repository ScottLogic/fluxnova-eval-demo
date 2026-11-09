"""eval-async-worker: the external-task worker for the non-blocking Eval
service task (topic ``agent-output-eval-async``).

See :mod:`eval_async_worker.worker` for the task handler,
:mod:`eval_async_worker.config` for the YAML-file configuration, and the
package README for the design.
"""

from eval_async_worker.config import AsyncWorkerConfig
from eval_async_worker.scoring import TraceEvalOutcome, score_trace
from eval_async_worker.worker import AsyncEvalWorker

__all__ = ["AsyncEvalWorker", "AsyncWorkerConfig", "TraceEvalOutcome", "score_trace"]
