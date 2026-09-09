"""eval-trace-listener: a standalone service that tails an MLflow experiment's
trace store and scores newly-completed agent runs with the shared deterministic
(trace-only) scorers.

See :mod:`eval_trace_listener.listener` for the poll loop, :mod:`eval_trace_listener.config`
for the YAML-file configuration, and the package README for the design rationale
(why it polls MLflow rather than running its own OTLP receiver).
"""

from eval_trace_listener.config import ListenerConfig
from eval_trace_listener.listener import TraceListener
from eval_trace_listener.scoring import TraceEvalOutcome, score_trace

__all__ = ["ListenerConfig", "TraceListener", "TraceEvalOutcome", "score_trace"]
