# Runner changes required for the callable Loan Assessment Agent

## Background
`bpmn/loan-assesment-eval.bpmn` no longer contains the agent inline. The
`Loan Assessment Agent` ad-hoc subprocess was extracted, and the eval process now
invokes it via a **Call Activity**:

```xml
<callActivity id="CallActivity_LoanAssessmentAgent"
              name="Loan Assessment Agent"
              calledElement="loanAssessmentProcess">
  <extensionElements>
    <camunda:in variables="all" />
    <camunda:out variables="all" />
  </extensionElements>
</callActivity>
```

`loanAssessmentProcess` is defined in the **separate** file
`bpmn/loan-assesment.bpmn` (which already exists and is independently
deployable/queryable).

Mock workers are topic-based and engine-wide, so `mock_workers.py` needs **no**
changes.

## 1. Deploy both BPMN files (required)
The Call Activity resolves `loanAssessmentProcess` by ID, so that definition must
exist in the engine. Bundle both files in one deployment (safest — avoids
`latest`-binding version drift).

- **`config.py`**: add `additional_bpmn_paths: list[Path]` (default empty),
  populated from an optional `additional_bpmn_paths:` list in the YAML and
  resolved relative to the repo root like `bpmn_path`.
- **`client.deploy()`**: accept the extra paths and attach each as a separate
  `files` entry in the single multipart POST to `/deployment/create`.
- **`main.deploy()`**: pass `cfg.additional_bpmn_paths` through to
  `client.deploy(...)`.
- **`harness/config/loan-assesment-eval.yml`**: declare the dependency:
  ```yaml
  additional_bpmn_paths:
    - bpmn/loan-assesment.bpmn
  ```

## 2. `--wait-for-activity` must follow the child instance (required)
`client.wait_for_activity_completion()` filters `history/activity-instance` by
`processInstanceId=<top-level eval instance>`. The
`AdHocSubProcess_LoanAssessmentAgent` activity now runs inside the **called**
(child) process instance, so it will never match and the wait will time out.

Fix: resolve the child instance first, then poll it:
```
GET /history/process-instance?superProcessInstanceId=<instance_id>
# then query /history/activity-instance with the child's processInstanceId
```
Poll across children until the activity with `activity_id` is finished.

## 2b. Post-eval flow now contains user tasks (runtime note)
The eval process was extended after the gateway: on **pass** it flows into
`Generate Assessment Report` -> `Recommendation?` -> approve/reject; on **fail** it
first routes to the `Review Failed Evaluation` user task (loan-officers) before
rejoining the report step. The approve branch also ends in a
`Review and Approve Loan` user task.

Because mock workers only complete **external tasks** (by topic), these
**user tasks** will not auto-complete. An unattended `fluxnova-run` (without
`--wait-for-activity`) will therefore block at the first user task. Options:
- Use `--wait-for-activity` to stop at the subprocess/eval boundary, or
- Have the runner auto-claim+complete user tasks (there is already
  `client.claim_task` / `client.complete_task`), or
- Complete them manually in Tasklist.

New external-task topics used (already present in
`harness/config/loan-assesment-eval.yml` mock_workers):
`generate-assessment-report`, `rejection-notification`.

## 3. Downstream (not runner code — flag only)
`mlflow-eval --collect` keys off `subprocess_id: AdHocSubProcess_LoanAssessmentAgent`.
Since that subprocess is now in the child instance, whatever reads its
trace/history (`fluxnova_mlflow_dataset`) needs the same parent -> child
resolution before an end-to-end eval will work.
