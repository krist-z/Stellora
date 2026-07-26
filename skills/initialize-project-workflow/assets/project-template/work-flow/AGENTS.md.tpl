# Managed Project Workflow

This directory is the project's workflow control plane. It is authoritative for
agent execution, state, routing, validation, evidence, and handoffs.

Read in this order: the root pointer, `work-flow/AGENTS.md`,
`work-flow/project_rules.md`, `work-flow/config.json`, `work-flow/state.md`, the
active requirement document, its evidence records, and its result document.
The root `AGENTS.md` is only an automatic-discovery pointer.

<!-- workflow-managed:work-flow-agents:v1 -->
{{IMPORTED_WORKFLOW_AGENTS}}

## Execution contract

- Default delegation is allowed when it materially improves the task. Use at most three concurrent read-only workers and one write worker.
- Route plan/requirements and high-risk review to `gpt-5.6-sol`; code, tests, and code review to `gpt-5.6-terra`; text, documents, reports, and light exploration to `gpt-5.6-luna`. This is content-based model-tier routing, not failure-triggered model substitution.
- Same-model effort downgrade is allowed only for an explicit unsupported-effort response. Authentication, provider, account, quota, network, permission, and model-not-found errors block the task.
- The parent session is the only writer of `state.md`, operation locks, and aggregate result files. Workers return structured results and do not recursively delegate when a valid `WORKFLOW_WORKER_CONTEXT` is present.
- A worker context is valid only when its task ID, operation ID, and role all match the same record in `work-flow/.runtime/operation-lock.json`. Any mismatch blocks execution.
- Preserve unrelated files. Do not move, rename, or reorder existing source, test, documentation, build, script, or configuration directories.

## Validation contract

- Deterministic facts come from the scanner. Unknown facts are written as `未发现/未验证`; no placeholders or invented commands.
- Run `work-flow/scripts/Invoke-ProjectWorkflow.ps1 validate --root <project> --strict` (or the Bash/Python wrapper) after initialization, upgrade, and material workflow changes.
- Record task results and evidence under `work-flow/docs/requirements/`, `decisions/`, `evidence/`, `handoffs/`, or `archive/` as appropriate.
