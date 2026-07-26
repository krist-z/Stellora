# Runtime upgrades

Compare project, installed, and distribution runtime/template versions with a
dry-run plan. Apply only with its hash. Upgrade workflow-owned files and schema
backups, preserve project facts and custom rules, run strict validation, and
retain transaction records under `work-flow/.runtime/transactions/`. Managed
rule customizations and `config.local.json` are preserved byte-for-byte; they
require a separate explicit migration task instead of template overwrite.

`init` and `upgrade` default to dry-run. Safe repair is limited to workflow-owned
runtime/wrappers, required ignore entries, an absent empty operation-lock document,
and required `.gitkeep` files. Missing or corrupt state/project facts, active locks,
and unregistered schemas require manual recovery. The registered schema `0 -> 1`
migration stores exact config/state before-images under
`work-flow/.runtime/migration-backups/`, binds them into the plan hash, migrates in
one transaction, and runs strict validation. Future schemas fail closed.
