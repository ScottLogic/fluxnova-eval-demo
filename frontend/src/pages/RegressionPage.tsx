import {useEffect} from 'react'
import {useRegressionStore} from '../store/regressionStore'
import TestList from '../components/TestList'
import Goldens from '../components/Goldens'

// Default MLflow port from local-dev/.env's MLFLOW_PORT.
const MLFLOW_URL = 'http://localhost:5000'

function RegressionPage() {
    const tests = useRegressionStore((state) => state.tests)
    const testsError = useRegressionStore((state) => state.testsError)
    const goldens = useRegressionStore((state) => state.goldens)
    const goldensError = useRegressionStore((state) => state.goldensError)
    const runResult = useRegressionStore((state) => state.runResult)
    const runError = useRegressionStore((state) => state.runError)
    const starting = useRegressionStore((state) => state.starting)
    const loadTests = useRegressionStore((state) => state.loadTests)
    const loadGoldens = useRegressionStore((state) => state.loadGoldens)
    const startRun = useRegressionStore((state) => state.startRun)

    useEffect(() => {
        loadTests()
        loadGoldens()
    }, [loadTests, loadGoldens])

    const running = starting || runResult?.status === 'running'

    const TextContent = () =>
        (
            <>
                <h3>Overview</h3>
                <p>
                    The end-to-end regression suite. This is the project's gating against behavioural regressions for
                    the agentic process.
                    It provides a baseline of functionality so that if anything changes then you can assess if the
                    result is better or worse.
                    We can also add failing production scenarios to the test suite allowing us to fix and validate real
                    use cases then keep them as part of our baseline in future.
                </p>
                <h3>What the tests do</h3>
                <p>For every golden scenario, a function drives the live agent end-to-end and uses MLFLow to evaluate
                    the agent's actual output.</p>
                <p>
                    The test generate one "real" run per golden which is replayed across every gate.
                    The output of the agent run is cached, the first call for a scenario actually drives the live agent,
                    and every later call replays that
                    same cached result rather than re-running the agent. This is a deliberate departure from calling the
                    agent fresh each time.
                    The agent is a live, non-deterministic call, and without caching, each non deterministic test would
                    be judging a different actual output for the same golden.
                    Caching guarantees every gate judges the same real output and reduces the overall cost of running
                    the tests.
                </p>
                <h3>How the output is collected</h3>
                <p>
                    The agent's actual final answer and tool call history is read from the run's
                    `_agentConversationHistory` and `_agentLoopIndex` process variables read back from an api call to
                    fluxnova.
                </p>
                <p className="panel-copy">
                    View available regression tests, trigger a run, and see results.
                </p>
            </>
        )

    return (
        <>
            <section className="panel regression-panel">
            <div className="panel-head">
                <p className="eyebrow">Regression</p>
                <h1>Regression tests</h1>
                <TextContent/>
            </div>

            <div className="actions">
                <button type="button" className="btn primary" onClick={startRun} disabled={running}>
                    {running ? 'Running…' : 'Run regression suite'}
                </button>
                <a className="btn ghost" href={MLFLOW_URL} target="_blank" rel="noreferrer">
                    Open MLflow dashboard
                </a>
            </div>

            {testsError && <p className="hint danger">{testsError}</p>}
            {!tests && !testsError && <p className="hint">Loading tests…</p>}

            <TestList tests={tests} runResult={runResult}/>

            {runError && <p className="hint danger">{runError}</p>}

            {runResult?.status === 'error' && (
                <div>
                    <p className="hint danger">Run crashed before producing results.</p>
                    <pre className="test-run-output">{runResult.output}</pre>
                </div>
            )}
        </section>
            <Goldens goldens={goldens} errors={goldensError} />
        </>
    )
}

export default RegressionPage
