"""eval-trace-listener: the external-task worker for the non-blocking Eval
service task (topic ``agent-output-eval-async``).

See :mod:`eval_trace_listener.worker` for the task handler,
:mod:`eval_trace_listener.config` for the YAML-file configuration, and the
package README for the design.
"""

from eval_trace_listener.config import ListenerConfig
from eval_trace_listener.scoring import TraceEvalOutcome, score_trace
from eval_trace_listener.worker import AsyncEvalWorker

__all__ = ["AsyncEvalWorker", "ListenerConfig", "TraceEvalOutcome", "score_trace"]
