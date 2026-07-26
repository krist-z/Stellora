---
name: initialize-project-workflow
description: Initialize, adopt, inspect, validate, repair, or upgrade a self-contained project work-flow control plane without moving existing project directories. Use for new projects and existing projects that need managed rules, state, routing, locks, evidence, and a bundled runtime.
---

# Initialize Project Workflow

This skill installs a project-local `work-flow/` control plane. The project copy
is self-contained and must not depend on a distribution checkout, `CODEX_HOME`,
provider credentials, or a user login. Existing source, tests, docs, scripts,
build, and configuration directories stay where they are.

## Required flow

1. Read the project's root `AGENTS.md`, `project_rules.md`, README, and any
   existing workflow files. Treat existing rules as authoritative input.
2. Run a dry-run and inspect its JSON plan, conflicts, target hashes, source
   versions, and generated project facts.
3. For a project with custom root rules, obtain explicit confirmation for rule
   migration. The initializer preserves an exact backup and imports the text
   into the managed file; it does not ask a model to rewrite rule semantics.
4. Apply only with the returned plan hash. A changed target, source template,
   runtime, scan result, or conflict set invalidates the hash.
5. Run strict validation and record evidence before continuing with product
   work.

`init` and `upgrade` default to dry-run when neither `--dry-run` nor `--apply` is
provided. Never infer apply from omission.

## Commands

From the distribution checkout:

```powershell
python skills/initialize-project-workflow/scripts/workflow_cli.py init --root <ProjectRoot> --mode new --dry-run --json
python skills/initialize-project-workflow/scripts/workflow_cli.py init --root <ProjectRoot> --mode adopt --apply --plan-hash <sha256> --confirm-rule-migration --json
python skills/initialize-project-workflow/scripts/workflow_cli.py validate --root <ProjectRoot> --strict --json
python skills/initialize-project-workflow/scripts/workflow_cli.py upgrade --root <ProjectRoot> --dry-run --json
python skills/initialize-project-workflow/scripts/workflow_cli.py upgrade --root <ProjectRoot> --apply --plan-hash <sha256> --json
```

After initialization, use the bundled `work-flow/scripts/Invoke-ProjectWorkflow.ps1`,
`invoke-project-workflow.sh`, or `workflow.py` entry point. The same runtime
supports `inspect`, `validate`, `route`, `task`, `next-action`, `transition`,
`lock`, `worker`, and `archive`.

The maintained source lives in the distribution's
`skills/initialize-project-workflow` directory. Install the optional global copy
with the distribution installer only after offline validation, then compare the
source and installed file manifests. A project-local copy continues to support
offline `validate`, `inspect`, `route`, state, lock, and archive operations when
the global skill or Codex worker backend is unavailable; worker execution reports
exit code 3 instead of fabricating completion.

## Project layout

The initializer creates a root discovery pointer and `work-flow/AGENTS.md`,
`work-flow/project_rules.md`, `config.json`, `config.local.json`, `state.md`,
`.runtime/`, `docs/`, and `scripts/`. Existing root `project_rules.md` content is
backed up, imported verbatim, and removed from the root only after explicit
migration confirmation so the internal rules remain the single authority.

Requirements use an immutable UUID `task_id` plus a separate four-digit
`display_seq`; renaming a display directory never changes identity. `state.md`
contains a unique JSON sentinel block. Runtime writes use atomic replacement,
expected-revision compare-and-swap, a parent-owned operation lock, and a bounded
50-event window. Completed tasks are indexed only after result and archive
documents are written under `docs/requirements/` and `docs/archive/`.

## Routing and workers

Use 5.6 family content tiers: plan, plan review, and risk -> `gpt-5.6-sol`;
source changes, tests, and code review -> `gpt-5.6-terra`; formal text, result
documents, and light exploration -> `gpt-5.6-luna`. Unclassified complex
exploration uses Terra only after a recorded route decision. The requested effort is
recorded separately from the effective effort. Downgrade within the same model
only after an explicit unsupported-effort error or a verified local capability
table. Authentication, account, provider, model-not-found, quota, rate-limit,
network, permission, sandbox, schema, and test errors are blocking/failing
outcomes, never effort evidence.

Prefer native subagents when the exact model and effort are supported. Otherwise
use the controlled `codex exec --ephemeral --json` leaf worker with native
delegation disabled. Non-Git roots receive `--skip-git-repo-check` only after an
explicit `trust grant-non-git` record bound to the current workspace ID; Git
roots do not. Every worker receives a
`WORKFLOW_WORKER_CONTEXT`, operation ID, allowed paths, structured output schema,
and a pre/post workspace fingerprint. Leaf workers do not recurse, edit state,
locks, transactions, or aggregate results. A claimed result is rejected unless
identity, model/effort, changed paths, revision, and validation evidence are
consistent. Completed validation items must be structured passing command results,
or an explicit not-applicable record for a read-only role. Files, directories,
empty directories, Git metadata, symlinks and reparse points participate in the
typed fingerprint. Blocked, failed, invalid and timeout results restore all detected
worker changes; an incomplete restoration returns exit code 6.

## Upgrade and recovery

Runtime/template upgrades are never silent. Use dry-run, review a versioned plan
and backup, then apply with the plan hash. Only workflow-owned files are changed;
project facts, local config, and customized managed rules are preserved. Safe repair
is allowlisted; missing state/project facts and active locks require manual recovery.
Schema `0 -> 1` is registered with exact config/state migration backups; unknown or
future schemas are refused. Transaction failure
returns a rollback-aware exit code; exit code 6 requires manual recovery from the
recorded backup/manifest boundary.

If an operation lock is stale, do not delete it by hand. Use `lock recover` with
the exact operation ID, task ID, role, operator owner, and reason after the
heartbeat age gate, or record why `--force-stale` is necessary. The runtime
records the old operation, operator, heartbeat age, and time in
`.runtime/transactions/lock-recovery.jsonl`.

See the bundled references for layout, state schema, routing, migration,
upgrades, and Concord concept mapping.
