---
name: project-workflow
description: Generic project workflow for Codex-style development, debugging, documentation, acceptance, and repo maintenance. Use when a repository needs PM/Explorer/Builder/Tester/Reporter coordination, doc-driven continuation, full closeout, or workflow synchronization.
---

# Project Workflow

## Purpose

Use this skill to run repository work through a reusable operating model: read the current project instructions, choose the right role, make the smallest useful change, verify the real behavior, and update durable evidence when conclusions change.

## Required First Reads

Start from the repository root. Read only what exists and is relevant:

1. `AGENTS.md`
2. `project_rules.md` or the repository's equivalent rules file
3. Product, architecture, docs index, runbook, or acceptance-result documents that govern the task
4. Relevant source files, tests, scripts, and generated artifacts needed for the current question

When the user says to continue, continue from the current project docs, result artifacts, and newest request instead of asking them to restate context.

## Prompt Templates

Global workflow trigger prompts live in `CODEX_HOME/prompt-templates/workflow-prompts.json`.
They are shortcuts for starting common flows such as PM/Explorer-only checks, full execution, read-only investigation, runtime debugging, documentation sync, review, and full closure.
When the user wants an input picker, the optional local helper is `CODEX_HOME/scripts/Start-CodexPromptMenuBackground.ps1`; it opens the same prompt list from the custom `#` trigger while Codex is focused, and can be stopped with `CODEX_HOME/scripts/Stop-CodexPromptMenu.ps1`.
`/` and `@` are reserved for Codex built-in input behavior. Use `CODEX_HOME/scripts/Install-CodexPromptMenuAutostart.ps1` only when the user wants logon autostart.

Use them as prompt starters only; the active repository's `AGENTS.md` and rule files still define the concrete commands, paths, evidence documents, and safety rules.

## Role Routing

Use the logical roles below. A single Codex instance can perform all roles for small tasks.

- PM: scope, acceptance criteria, impact boundary, and task slicing.
- Explorer: read-only code, doc, script, and artifact investigation.
- Builder: focused implementation in declared files/modules.
- Tester: targeted build, test, runtime acceptance, and artifact inspection.
- Reporter: durable conclusion updates and final evidence summary.

Spawn subagents only when the user explicitly asks for delegation, parallel agents, or multi-agent execution.

## Task Level Routing

Classify the task before choosing how much process to apply:

- L1 Quick: wording, comments, low-risk docs, tiny style/config notes. Read the directly relevant file, change the minimum surface, and run a narrow static/readability check when useful.
- L2 Standard: normal bug fixes, local features, tests, scripts, or refactors. Read the relevant project rules/docs, implement a bounded patch, run targeted verification, and sync necessary docs.
- L3 Full Closure: cross-module behavior, runtime UI/API/persistence/protocol paths, or explicit full-closure/sync requests. Complete PM/Explorer/Builder/Tester/Reporter, update evidence, and run workflow sync checks.
- L4 Release/Risk: production release, migrations, destructive operations, security, permissions, data deletion, payments, or irreversible changes. Do L3 plus rollback, monitoring, post-release validation, and explicit human confirmation.

If a user's wording suggests a lower level but the actual impact is higher, use the higher level and explain the escalation. If the task is truly L1, do not burden it with L3 documentation unless the repository rules require it.

## Standard Flow

1. Confirm the active target from the newest user request and repository instructions.
2. Inspect worktree status before editing; preserve unrelated changes.
3. Use fast discovery tools such as `rg` and `rg --files` where available.
4. Classify the task: code, tests, scripts, docs, workflow, runtime acceptance, release, security, data, or infrastructure.
5. Patch the smallest coherent slice that satisfies the request.
6. Run the narrowest verification that proves the changed behavior; expand to runtime acceptance when needed.
7. Update durable docs/result files when new evidence changes the current conclusion.
8. Keep workflow entrypoints synchronized if scripts, docs, results, or local instructions change.
9. When the user asks for full closure or zero-risk workflow, translate the request into verifiable gates: synchronized docs, latest evidence, rollback/runbook coverage, and explicit residual risks.
10. Final response must name changed files, verification run, failures or unverified items, and remaining risk.

## Definition Of Done

- L1: the narrow change is complete; static/readability checks pass or are explained as not applicable.
- L2: targeted tests/checks pass; docs are synced if behavior, scripts, APIs, or workflows changed.
- L3: real-path verification or trusted acceptance passes; evidence and workflow sync are updated; residual risk is explicit.
- L4: L3 is complete; rollback, monitoring, release/post-release validation, and human confirmation are recorded.

## Documentation Rules

- Keep long-lived conclusions in repository docs, result files, runbooks, or the project `AGENTS.md`, not only in chat.
- Result documents should represent the latest proven state; do not mix stale and fresh evidence into ambiguity.
- Project-specific workflow belongs in the repository `AGENTS.md` unless the user explicitly asks for a repo-local `.codex` override.
- Global skills should stay generic and reusable across repositories.
- Keep secrets, private tokens, database passwords, local certs, generated logs, and machine-only paths out of durable files.
- Use handoff blocks for multi-session continuation: goal, current state, important files, decisions, validation, risks, and next step.

## Verification Guidance

Build success alone is not enough when the request concerns UI interaction, playback, streaming, persistence, network protocols, data migration, deployment, or runtime status. Use the real runtime path or acceptance scripts that the repository already trusts.

For documentation/workflow-only changes, run the repository's documented sync/check script if one exists. If no such script exists, validate links, paths, syntax, and stale references manually.

For mature workflows, prefer split checks for workflow sync, secrets, git boundaries, document links, evidence quality, and health dashboard generation. These checks reduce drift but do not replace product-specific runtime acceptance.
