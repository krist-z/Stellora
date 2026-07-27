# Runtime upgrades

Compare project, installed, and distribution runtime/template versions with a
dry-run plan. Apply only with its hash. Upgrade workflow-owned files and schema
backups, preserve project facts and custom rules, run strict validation, and
retain transaction records under `work-flow/.runtime/transactions/`. Managed
rule customizations and `config.local.json` are preserved byte-for-byte. Managed
rules use a three-way decision: current file, recorded rendered baseline, and new
template. Legacy projects reconstruct the old baseline from the template assets in
their project-local runtime. Non-overlapping current/template edits are merged into
the planned target. Overlapping hunks produce `template_merge_conflict`; a missing or
unreconstructable baseline produces `template_baseline_unavailable`. Either conflict
blocks apply until an explicit migration resolves it.

Runtime 1.1 and later writes `runtime-manifest.json` under the project runtime.
Strict validation compares the manifest version, exact file set, every SHA-256,
the runtime and template versions, and the manifest hash recorded in `config.json`.
Missing, unexpected, or changed runtime files fail validation. An explicit upgrade
plan repairs drift and replaces the manifest in the same rollback-aware transaction;
a runtime/template state mutation advances the state revision.

`init` and `upgrade` default to dry-run. Safe repair is limited to workflow-owned
runtime/wrappers, required ignore entries, an absent empty operation-lock document,
and required `.gitkeep` files. Missing or corrupt state/project facts, active locks,
and unregistered schemas require manual recovery. The registered schema `0 -> 1`
migration stores exact config/state before-images under
`work-flow/.runtime/migration-backups/`, binds them into the plan hash, migrates in
one transaction, and runs strict validation. Future schemas fail closed.
