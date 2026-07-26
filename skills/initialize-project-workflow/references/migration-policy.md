# Migration policy

Initialization defaults to dry-run. Existing rules are backed up and imported
verbatim. Replacing a custom root rule requires `--confirm-rule-migration`; a
conflict blocks apply. No model may silently rewrite the semantics of legacy
rules during initialization. After confirmation, the root `AGENTS.md` becomes
the discovery pointer and a migrated root `project_rules.md` is removed only
after its backup and verbatim internal import are staged in the same rollback
transaction.
