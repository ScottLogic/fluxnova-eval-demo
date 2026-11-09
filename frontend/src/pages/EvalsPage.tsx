import {useEffect, useState} from 'react'
import {fetchEvalDefinitions, type EvalDefinitions} from '../api'
import ScorerTable from '../components/ScorerTable'

function EvalsPage() {
    const [definitions, setDefinitions] = useState<EvalDefinitions | null>(null)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        fetchEvalDefinitions()
            .then((result) => {
                setDefinitions(result)
                setError(null)
            })
            .catch((err: unknown) => {
                setError(err instanceof Error ? err.message : 'Failed to load eval definitions')
            })
    }, [])

    return (
        <section className="panel">
            <div className="panel-head">
                <p className="eyebrow">Evals</p>
                <h1>Evals</h1>
                <p>
                    An evaluation or “eval” is a test for an AI system. The test typically consists of giving an AI an
                    input and then apply some scoring logic to its output to measure how good the response is for some
                    measure of good.
                </p>
                <p className="eyebrow">Scorers</p>
                <h1>Scorers</h1>
                <p className="panel-copy">
                    A scorer is a function which inspects a completed agent run and reports pass/fail (or a graded
                    score) against one specific check.</p>
                <p>
                    <strong className="scorer-legend-deterministic">Deterministic</strong> scorers are plain code checks
                    over the run's tool calls and process variables — fast, free, and exactly repeatable.</p>
                <p> <strong className="scorer-legend-non-deterministic">LLM judge</strong> scorers instead ask a model to grade
                    the agent's output (e.g. against fixed guidelines, or a golden reference answer) — slower and not
                    perfectly repeatable, but able to judge things a code check can't.
                </p>
                <p>
                    In production runs, both eval workers build each scorer's inputs from the agent's Fluxnova process
                    variables (its context variables, conversation history and loop count), not from trace content,
                    and attach their results to the run's MLflow trace.
                </p>
                <p className="eyebrow">Guardrail thresholds</p>
                <h1>When the guardrail passes</h1>
                <p>
                    The eval service worker (the <strong>Eval service worker</strong> column) runs as a blocking
                    guardrail on the <em>Evaluate Agent Output</em> task. Each run gets a score: the fraction of
                    applicable scorers that passed. Scorers that don't apply to the run (for example the
                    self-employed checks for an employed applicant) are left out.
                </p>
                <p>
                    The pass rule is set on the BPMN task itself, as two inputs you can edit in the Modeler without
                    changing or restarting the worker:
                </p>
                <ul>
                    <li><code>evalMinScore</code>: the minimum score, from 0 to 1. <code>1.0</code> (the default)
                        means every applicable scorer must pass.</li>
                    <li><code>evalRequiredScorers</code>: comma-separated scorer names that must pass whatever the
                        score, for example <code>decision_quality</code>. Only scorers ticked in the{' '}
                        <strong>Eval service worker</strong> column below can be used.</li>
                </ul>
                <p>
                    The worker writes back <code>evalPassed</code>, <code>evalScore</code>,{' '}
                    <code>evalFailedScorers</code> and <code>evalRationale</code>. A failed run goes to human review.
                    Invalid thresholds (a score outside 0–1, or an unknown scorer name) stop the task with an
                    incident before any judge is called. The Workflow run tab shows the BPMN defaults and lets you
                    override them for a single run; each run records the thresholds it used as process variables.
                </p>
            </div>

            {error && <p className="hint danger">{error}</p>}
            {!definitions && !error && <p className="hint">Loading eval definitions…</p>}

            {definitions && <ScorerTable scorers={definitions.scorers}/>}
        </section>
    )
}

export default EvalsPage
