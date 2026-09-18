import FinosProjectsPanel from "../components/FinosProjectsPanel.tsx";

function LandingPage() {
    const TextContent = () =>
        (
            <>
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
                    <li>Demonstration of real time production level guard-rail evaluation using FLuxnova.
                        This is demonstrated through the use of an Eval Service Task built into the Fluxnova process
                    </li>
                </ul>

                <h2>Overview</h2>
                <p>This project comprises of two main flows. These flows can be run via the console however,
                    this UI provides as user friendly layer for running and viewing these flows.
                </p>
                <ol>
                    <li>Production use case demo.</li>
                    <ul>
                        <li>Deploy and initiate a bpmn.</li>
                        <li>Observe the agentic ai tracing and metrics</li>
                        <li>Automatically run evals against configured traces as they appear.</li>
                        <li>Handle real time guard-rail use-cases with a Service Task and handler.
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
            </>
        )

    return (
        <div className="app-shell">
            <div className="mesh" aria-hidden="true"/>
            <section className="panel regression-panel">
                <div className="panel-head">
                    <h1>Fluxnova Eval Driven Development Demo</h1>
                    <TextContent/>
                </div>
            </section>
            <FinosProjectsPanel/>
        </div>
    )
}

export default LandingPage