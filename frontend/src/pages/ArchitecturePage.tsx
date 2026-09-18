import {ReactFlow, Background, Controls, MarkerType, type Edge, type Node} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

const nodeDefaults = {
    style: {
        background: '#1a2130',
        color: 'var(--paper)',
        border: '1px solid var(--paper-dim)',
        borderRadius: 8,
        padding: '0.5rem 0.75rem',
        fontSize: '0.85rem',
        width: 200,
    }
}

const nodes: Node[] = [
    {
        id: 'bpmn',
        position: {x: 0, y: 180},
        data: {label: 'bpmn/\nProcess definitions', description: 'BPMN process definitions deployed into Fluxnova.'},
        ...nodeDefaults,
    },
    {
        id: 'datasets',
        position: {x: 0, y: 320},
        data: {
            label: 'datasets/\nGolden scenarios',
            description: 'Golden loan-assessment scenarios (goldens.json) used by the regression suite.'
        },
        ...nodeDefaults,
    },
    {
        id: 'fluxnova',
        position: {x: 300, y: 180},
        data: {
            label: 'Fluxnova engine\n(BPMN + agent runtime)',
            description: 'Runs deployed BPMN processes, including the AI agent subprocess, and exports OTel traces for every run.',
        },
        ...nodeDefaults,
        style: {...nodeDefaults.style, borderColor: 'var(--copper)'},
    },
    {
        id: 'postgres',
        position: {x: 300, y: 40},
        data: {
            label: 'Postgres\n(Fluxnova + MLflow store)',
            description: 'Shared datasource: Fluxnova\'s process/runtime data and MLflow\'s tracking store.'
        },
        ...nodeDefaults,
    },
    {
        id: 'otel',
        position: {x: 300, y: 320},
        data: {
            label: 'OTel Collector\n(OTLP traces)',
            description: 'Receives OTLP traces from Fluxnova and forwards them to MLflow\'s trace store.'
        },
        ...nodeDefaults,
    },

    {
        id: 'mlflow',
        position: {x: 600, y: 180},
        data: {
            label: 'MLflow\n(tracking + traces)',
            description: 'Tracking server for experiment runs, regression results, and agent traces.'
        },
        ...nodeDefaults,
    },

    {
        id: 'runner',
        position: {x: 300, y: 460},
        data: {
            label: 'fluxnova-runner\n(deploy/drive a BPMN run)',
            description: 'Client library that deploys a BPMN and drives a process instance to completion.'
        },
        ...nodeDefaults,
    },
    {
        id: 'regression',
        position: {x: 0, y: 460},
        data: {
            label: 'regression/\nMLflow regression suite',
            description: 'Drives the live agent through fluxnova-runner for every golden and scores the result with MLflow.'
        },
        ...nodeDefaults,
    },
    {
        id: 'mlflow-dataset',
        position: {x: 600, y: 460},
        data: {
            label: 'fluxnova-mlflow-dataset\n(shared scorers/judges)',
            description: 'Shared library of deterministic/LLM-judge scorers used by the regression suite and both eval services.'
        },
        ...nodeDefaults,
    },

    {
        id: 'listener',
        position: {x: 900, y: 100},
        data: {
            label: 'eval-trace-listener\n(tails traces, scores)',
            description: 'Tails the MLflow trace store and scores newly-completed traces with the deterministic scorers.'
        },
        ...nodeDefaults,
    },
    {
        id: 'worker',
        position: {x: 900, y: 280},
        data: {
            label: 'eval-service-worker\n(external-task scoring)',
            description: 'Subscribes to a Fluxnova external-task topic and scores runs against MLflow in real time.'
        },
        ...nodeDefaults,
    },
]

const edgeDefaults = {
    type: 'smoothstep',
    markerEnd: {type: MarkerType.ArrowClosed},
    style: {stroke: 'var(--paper-dim)'},
}

const edges: Edge[] = [
    {id: 'e-bpmn-fluxnova', source: 'bpmn', target: 'fluxnova', label: 'deployed into', ...edgeDefaults},
    {id: 'e-runner-fluxnova', source: 'runner', target: 'fluxnova', label: 'starts process instance', ...edgeDefaults},
    {
        id: 'e-regression-runner',
        source: 'regression',
        target: 'runner',
        label: 'drives run per golden', ...edgeDefaults
    },
    {id: 'e-datasets-regression', source: 'datasets', target: 'regression', label: 'goldens.json', ...edgeDefaults},
    {
        id: 'e-regression-scorers',
        source: 'regression',
        target: 'mlflow-dataset',
        label: 'uses scorers', ...edgeDefaults
    },
    {id: 'e-postgres-fluxnova', source: 'postgres', target: 'fluxnova', label: 'datasource', ...edgeDefaults},
    {id: 'e-postgres-mlflow', source: 'postgres', target: 'mlflow', label: 'tracking store', ...edgeDefaults},
    {id: 'e-fluxnova-otel', source: 'fluxnova', target: 'otel', label: 'OTLP export', ...edgeDefaults},
    {id: 'e-otel-mlflow', source: 'otel', target: 'mlflow', label: 'forwards traces', ...edgeDefaults},
    {id: 'e-regression-mlflow', source: 'regression', target: 'mlflow', label: 'evaluate()', ...edgeDefaults},
    {id: 'e-listener-mlflow', source: 'listener', target: 'mlflow', label: 'tails traces', ...edgeDefaults},
    {id: 'e-listener-scorers', source: 'listener', target: 'mlflow-dataset', label: 'uses scorers', ...edgeDefaults},
    {id: 'e-worker-fluxnova', source: 'worker', target: 'fluxnova', label: 'external-task topic', ...edgeDefaults},
    {id: 'e-worker-mlflow', source: 'worker', target: 'mlflow', label: 'writes scores', ...edgeDefaults},
    {id: 'e-worker-scorers', source: 'worker', target: 'mlflow-dataset', label: 'uses scorers', ...edgeDefaults},
]

function ArchitecturePage() {
    return (
        <section className="panel-full-width">
            <div className="panel-head">
                <p className="eyebrow">Architecture</p>
                <h1>Project architecture</h1>
                <p>
                    The project is built around a central Fluxnova instance which includes the agentic-subprocesses
                    plugin
                    and has been augmented to export OTel gen_ai telemetry.
                </p>
            </div>

            <div className="architecture-diagram">
                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    fitView
                    nodesDraggable={false}
                    nodesConnectable={false}
                    elementsSelectable={false}
                >
                    <Background/>
                    <Controls showInteractive={false}/>
                </ReactFlow>
            </div>
        </section>
    )
}

export default ArchitecturePage
