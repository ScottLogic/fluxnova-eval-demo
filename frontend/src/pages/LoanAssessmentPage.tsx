import {useState} from 'react'
import BpmnViewer from '../components/BpmnViewer'

const DIAGRAMS = [
    {
        id: 'loan-approval-ai',
        label: 'Loan Assessment Process',
        xmlUrl: '/bpmn/LoanApprovalProcess_AI.bpmn',
        description: (
            <>
                <p>
                    A multi-agent loan approval workflow that automates document intake, fraud detection, credit risk
                    assessment, decisioning, pricing, human review, agreement generation, e-signature, and disbursement.
                    <p>
                    </p>
                    Automates and optimizes evaluating, approving, pricing, documenting, and disbursing loans. A loan
                    approval orchestrator coordinates specialist agents for document intelligence, fraud detection,
                    compliance review, credit risk assessment, dynamic pricing, and document generation, with
                    deterministic policy gates and human review checkpoints.
                </p>
                <p>
                    This is the BPMN for the overall loans assessment process. It contains the AI Credit Risk Agent as a Call Activity
                    which calls out to a separate bpmn (loan Assessment)
                </p>
            </>
        ),
    },
    {
        id: 'loan-assessment',
        label: 'Credit Risk Agent',
        xmlUrl: '/bpmn/loan-assesment.bpmn',
        description: (
            <>
                <p>
                    This process contains only the agentic ad-hoc subprocess so it can be isolated for eval testing.
                </p>
            </>
        ),
    },
] as const

function LoanAssessmentPage() {
    const [activeId, setActiveId] = useState<(typeof DIAGRAMS)[number]['id']>(DIAGRAMS[0].id)
    const active = DIAGRAMS.find((diagram) => diagram.id === activeId) ?? DIAGRAMS[0]

    return (
        <section className="panel">
            <div className="panel-head">
                <p className="eyebrow">Loan assessment</p>
                <h1>Loan assessment workflows</h1>
                <p className="panel-copy">
                    The two BPMN processes behind this demo's loan use case: the full loan approval process run from
                    the Workflow run tab, and the AI agent subprocess exercised by the regression suite.
                </p>
            </div>

            <div className="actions">
                {DIAGRAMS.map((diagram) => (
                    <button
                        key={diagram.id}
                        type="button"
                        className={`btn ${diagram.id === activeId ? 'primary' : 'ghost'}`}
                        onClick={() => setActiveId(diagram.id)}
                    >
                        {diagram.label}
                    </button>
                ))}
            </div>

            {active.description}

            <BpmnViewer xmlUrl={active.xmlUrl}/>
        </section>
    )
}

export default LoanAssessmentPage
