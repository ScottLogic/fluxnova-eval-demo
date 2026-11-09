import FinosProjectsPanel from '../components/FinosProjectsPanel'
import RepoQrCard from '../components/RepoQrCard'
import TabContents from '../components/TabContents'

function OverviewText() {
    return (
        <>
            <p className="sample-preview-label">Overview</p>
            <div>
                <p>This project comprises two main flows. They can be run from the console, but this UI provides
                    a user-friendly layer for running and viewing them.
                </p>
                <ol>
                    <li>Production use case demo.</li>
                    <ul>
                        <li>Deploy and initiate a bpmn.</li>
                        <li>Observe the agentic ai tracing and metrics</li>
                        <li>Automatically score every run with a non-blocking Eval Service Task that never holds up the
                            process.</li>
                        <li>Run a blocking guardrail Eval Service Task that sends failed (and, if configured, every
                            Nth) runs to a human reviewer in Fluxnova Tasklist.
                        </li>
                    </ul>
                    <li>Development Demo</li>
                    <ul>
                        <li>Run a complete regression suite using the "golden" set of validated example flows.</li>
                    </ul>
                </ol>
                <p>
                    Together these two use-case demonstrate both development using an EDD approach of a Fluxnova
                    processes and the live monitoring and evaluation of agentic workflows in Fluxnova.
                </p>
            </div>
        </>
    )
}

function Contents() {
    return (
        <>
            <div>
                <p className="sample-preview-label">Contents</p>
                <TabContents/>
            </div>
        </>
    )
}

function LandingText() {
    return (
        <>
            <p className="sample-preview-label">Goals</p>
            <p>
                The Fluxnova EDD Demo is a set of tooling designed to demonstrate the use and benefits of agentic
                evaluation with Fluxnova workflows.
                The goals of this project are:
            </p>
            <ul>
                <li>Demonstration of EDD in Development with Fluxnova. This is demonstrated via the regression
                    tests.
                </li>
                <li>Demonstration of real-time production level monitoring and Evaluation of agentic output.
                    This is Demonstrated through the use of <code><a
                        href="https://opentelemetry.io/blog/2026/genai-observability/">gen_ai*</a></code>
                    metrics and tracing coupled with <a href="https://mlflow.org/">MLFlow</a>.
                </li>
                <li>Demonstration of real time production level guard-rail evaluation using Fluxnova.
                    This is demonstrated through the use of a blocking Eval Service Task built into the Fluxnova
                    process, which sends failed (and, if configured, every Nth) runs to human review.
                </li>
            </ul>
        </>
    )
}

function LandingPage() {
    return (
        <>
            <section className="panel regression-panel">
                <div className="panel-head">
                    <h1>Fluxnova Eval Driven Development Demo</h1>
                    <LandingText/>
                </div>

                <Contents/>
                <OverviewText/>
            </section>

            <div className="goldens-panel landing-side">
                <RepoQrCard/>
                <FinosProjectsPanel/>
            </div>
        </>
    )
}

export default LandingPage
