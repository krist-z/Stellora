# Project Rules

Follow the user's current request, then the root `AGENTS.md` pointer, then this
file. Existing project rules imported below remain verbatim and retain their
meaning; resolve conflicts explicitly before implementation.

## Managed workflow boundaries

- Keep workflow assets under `work-flow/`; existing project directories remain in place.
- `work-flow/state.md` is the machine state source. Its JSON sentinel block is authoritative; do not edit it directly.
- Keep `work-flow/config.local.json`, `.runtime/`, worker output, backups, and transactions out of version control.
- External writes, production changes, permissions, payment, deletion, migration, and release require explicit confirmation, rollback, monitoring, and post-action validation.

<!-- workflow-managed:project-rules:v1 -->
{{IMPORTED_PROJECT_RULES}}
