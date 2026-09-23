import {
    ReactFlow,
    Background,
    Controls,
    MarkerType,
    type Edge,
    type Node,
    useNodesState,
    useEdgesState,
} from '@xyflow/react'
import CustomNode from '../components/CustomNode'
import '@xyflow/react/dist/style.css'
import {useEffect} from "react";

const nodeDefaults = {
    style: {
        background: '#1a2130',
        color: 'var(--paper)',
        border: '1px solid var(--paper-dim)',
        borderRadius: 8,
        padding: '0.5rem 0.75rem',
        fontSize: '0.85rem',
        width: 200,
    },
    type: "selectorNode"
}

const NODES: Node[] = [
    {
        id: 'fluxnova',
        position: {x: 0, y: 0},
        data: {
            label: 'Fluxnova engine',
            description: 'Runs deployed BPMN processes, including the AI agentic subprocess, and exports OTel traces for every run.',
        },
        ...nodeDefaults,
        height: 150,
        style: {...nodeDefaults.style, borderColor: 'var(--copper)', borderWidth: "thin", alignContent: "center"},
    },
    {
        id: 'postgres',
        position: {x: 400, y: -100},
        data: {
            label: 'Postgres',
            description: 'Shared datasource: Fluxnova\'s process/runtime data and MLflow\'s tracking store.'
        },
        ...nodeDefaults,
    },
    {
        id: 'otel',
        position: {x: 150, y: 250},
        data: {
            label: 'OTel Collector',
            description: 'Receives OTLP traces from Fluxnova and forwards them to MLflow\'s trace store.'
        },
        ...nodeDefaults,
    },

    {
        id: 'mlflow',
        position: {x: 700, y: 300},
        data: {
            label: 'MLflow',
            description: 'The MLFlow UI, used to visualise tracing from Fluxnova, Eval runs from the listener and Regression test runs.'
        },
        ...nodeDefaults,
    },

    {
        id: 'runner',
        position: {x: -350, y: 200},
        data: {
            label: 'Fluxnova Runner',
            description: 'Custom service that deploys a BPMN to Fluxnova, initiates it and waits for a specified completion point. Handles mocking out service task as well.'
        },
        ...nodeDefaults,
    },
    {
        id: 'regression',
        position: {x: -350, y: 500},
        data: {
            label: 'regression suite',
            description: 'Uses MLFlow to run the regression tests against the golden data sets. Drives the live agent through the Runner for every golden and scores the result.'
        },
        ...nodeDefaults,
    },
    {
        id: 'grafana',
        position: {x: 400, y: 100},
        data: {
            label: 'Grafana (Metrics)',
            description: 'Grafana and Prometheus instances for viewing the metrics out of the OTel Collector'
        },
        ...nodeDefaults,
    },
    {
        id: 'listener',
        position: {x: 850, y: 0},
        data: {
            label: 'eval-trace-listener',
            description: 'Listens to the MLflow trace store and runs evals against newly completed traces. Is configurable with a sample rate to run against every nth trace.'
        },
        ...nodeDefaults,
    },
    {
        id: 'worker',
        position: {x: -100, y: 400},
        data: {
            label: 'eval-service-worker',
            description: 'Subscribes to a Fluxnova external-task topic and scores runs against MLflow in real time (See Loan Assessment BPMN).'
        },
        ...nodeDefaults,
    },
]

const edgeDefaults = {
    type: 'smoothstep',
    markerEnd: {type: MarkerType.Arrow},
    style: {stroke: 'var(--paper-dim)'},
}

const EDGES: Edge[] = [
    {
        id: 'e-runner-fluxnova',
        source: 'runner',
        sourceHandle: 'right',
        target: 'fluxnova',
        targetHandle: 'left',
        label: 'Initiate process instance', ...edgeDefaults
    },
    {
        id: 'e-regression-runner',
        source: 'regression',
        sourceHandle: 'top',
        target: 'runner',
        targetHandle: 'bottom',
        label: 'Uses', ...edgeDefaults
    },
    {
        id: 'e-postgres-fluxnova',
        source: 'fluxnova',
        sourceHandle: 'top',
        target: 'postgres',
        targetHandle: 'left',
        label: 'datasource', ...edgeDefaults
    },
    {
        id: 'e-postgres-mlflow',
        source: 'postgres',
        sourceHandle: 'right',
        target: 'mlflow',
        targetHandle: 'ttop',
        label: 'tracking store', ...edgeDefaults
    },
    {
        id: 'e-fluxnova-otel',
        source: 'otel',
        sourceHandle: 'top',
        target: 'fluxnova',
        targetHandle: 'bottom',
        label: 'OTLP export', ...edgeDefaults
    },
    {
        id: 'e-otel-mlflow',
        source: 'otel',
        sourceHandle: 'right',
        target: 'mlflow',
        targetHandle: 'left',
        label: 'forwards traces', ...edgeDefaults
    },
    {
        id: 'e-otel-grafana',
        source: 'otel',
        sourceHandle: 'right',
        target: 'grafana',
        targetHandle: 'left',
        label: 'forwards traces', ...edgeDefaults
    },
    {
        id: 'e-regression-mlflow',
        source: 'regression',
        sourceHandle: 'right',
        target: 'mlflow',
        targetHandle: 'bottom',
        label: 'evaluates', ...edgeDefaults
    },
    {
        id: 'e-listener-mlflow',
        source: 'mlflow',
        sourceHandle: 'right',
        target: 'listener',
        targetHandle: 'bottom',
        label: 'tails traces', ...edgeDefaults
    },
    {
        id: 'e-worker-fluxnova',
        source: 'worker',
        sourceHandle: 'top',
        target: 'fluxnova',
        targetHandle: 'bottom',
        label: 'Handles task', ...edgeDefaults
    },
    {
        id: 'e-worker-mlflow',
        source: 'worker',
        sourceHandle: 'right',
        target: 'mlflow',
        targetHandle: 'left',
        label: 'writes scores', ...edgeDefaults
    },
]

const nodeTypes = {
    selectorNode: CustomNode,
};

function ArchitecturePage() {
    const [nodes, setNodes, onNodesChange] = useNodesState(NODES);
    const [edges, setEdges, onEdgesChange] = useEdgesState(EDGES);

    useEffect(() => {
        setNodes(NODES)
        setEdges(EDGES)
    }, []);

    return (
        <section className="panel-full-width">
            <div className="panel-head">
                <p className="eyebrow">Architecture</p>
                <h1>Project architecture</h1>
                <p>
                    The project is built around a central Fluxnova instance which includes the agentic-subprocesses
                    plugin and has been augmented to export OTel gen_ai telemetry.
                </p>
                <p>Select a node for a more detailed description:</p>
            </div>

            <div className="architecture-diagram">
                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    fitView
                    nodeTypes={nodeTypes}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    elementsSelectable={true}
                >
                    <Background/>
                    <Controls showInteractive={false}/>
                </ReactFlow>
            </div>
        </section>
    )
}

export default ArchitecturePage
