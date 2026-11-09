interface FieldInfo {
  label: string
  description: string
}

// Labels/descriptions for the known process variables in
// fluxnova-runner/config/loan_approval_process_ai.yml's `variables`.
// approvalDecision isn't applicant data: it's the starting value for Gateway_5
// "Manual Review Required?" (MANUAL_REVIEW routes to Loan Officer Review).
// aiRiskScore is legacy and no longer used by the BPMN.
const FIELD_INFO: Record<string, FieldInfo> = {
  applicationId: {
    label: 'Application ID',
    description: 'Unique identifier for this loan application.',
  },
  customerId: {
    label: 'Customer ID',
    description: 'Unique identifier for the applicant/customer.',
  },
  applicantName: {
    label: 'Applicant Name',
    description: 'Full name of the loan applicant.',
  },
  requestedAmount: {
    label: 'Requested Amount',
    description: 'Loan amount being requested, in GBP.',
  },
  applicantType: {
    label: 'Applicant Type',
    description: 'Employment status of the applicant: EMPLOYED or SELF_EMPLOYED.',
  },
  hasCollateral: {
    label: 'Has Collateral',
    description: 'Whether the applicant has offered collateral against the loan.',
  },
  collateralDescription: {
    label: 'Collateral Description',
    description: 'Free-text description of the offered collateral, if any.',
  },
  loanPurpose: {
    label: 'Loan Purpose',
    description: 'What the applicant intends to use the loan for.',
  },
  aiRiskScore: {
    label: 'AI Risk Score',
    description: "Legacy variable, no longer used. \"Risk Approved?\" follows the reviewer's decision, or the agent's if there was no review.",
  },
  approvalDecision: {
    label: 'Approval Decision',
    description: 'Set to MANUAL_REVIEW to route to Human: Loan Officer Review (that task has no form in this demo); leave blank to skip it.',
  },
  skipEvalServiceWorker: {
    label: 'Skip Eval Service Worker',
    description: 'When enabled, skips the blocking guardrail (and so any human review) for this run; the agent\'s decision goes straight to "Risk Approved?".',
  },
}

/** "someFieldName" -> "Some Field Name" — fallback for any variable not in FIELD_INFO. */
function humanizeFieldName(name: string): string {
  const spaced = name.replace(/([a-z0-9])([A-Z])/g, '$1 $2')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function fieldInfo(name: string): FieldInfo {
  return FIELD_INFO[name] ?? { label: humanizeFieldName(name), description: '' }
}
