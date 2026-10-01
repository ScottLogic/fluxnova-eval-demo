interface FieldInfo {
  label: string
  description: string
}

// Labels/descriptions for the known process variables in
// fluxnova-runner/config/loan_approval_process_ai.yml's `variables`. aiRiskScore
// and approvalDecision aren't applicant-facing data — they're starting values
// for BPMN gateway conditions (Gateway_4 "Risk Approved?" / Gateway_5 "Manual
// Review Required?"), described as such rather than guessed at.
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
    description: "Starting value for the automated risk gate (\"Risk Approved?\"); normally left at its default.",
  },
  approvalDecision: {
    label: 'Approval Decision',
    description: 'Starting value for the manual-review gate; normally left at its default.',
  },
  skipEvalServiceWorker: {
    label: 'Skip Eval Service Worker',
    description: 'When enabled, bypasses the synchronous eval-service-worker scoring step for this run.',
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
