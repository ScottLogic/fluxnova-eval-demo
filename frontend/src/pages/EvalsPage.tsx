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
            </div>

            {error && <p className="hint danger">{error}</p>}
            {!definitions && !error && <p className="hint">Loading eval definitions…</p>}

            {definitions && <ScorerTable scorers={definitions.scorers}/>}
        </section>
    )
}

export default EvalsPage
