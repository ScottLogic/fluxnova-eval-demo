"""eval-service-worker: BPMN external-task worker that scores a just-completed
agentic subprocess run using MLflow's ``decision_quality`` judge, reading trace
data only. See ``EVAL-SERVICE-WORKER-PLAN.md`` at the repo root for background.
"""

from eval_service_worker.config import EvalServiceConfig
from eval_service_worker.scoring import EvalOutcome, NoFinalOutputError, score_process_instance

__all__ = [
    "EvalServiceConfig",
    "EvalOutcome",
    "NoFinalOutputError",
    "score_process_instance",
]
