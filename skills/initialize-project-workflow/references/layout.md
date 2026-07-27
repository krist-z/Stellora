# Project layout

The root `AGENTS.md` is an automatic-discovery pointer. The authoritative
workflow files live under `work-flow/`; existing project directories are not
moved or renamed. `work-flow/scripts/_runtime/` is the committed, versioned
runtime used by the project itself. `config.json` is shared; the ignored
`config.local.json` is machine-local. Existing root `project_rules.md` is backed
up and imported before removal so it cannot remain a second authority.

`work-flow/scripts/_runtime/runtime-manifest.json` contains stable SHA-256 hashes
for the bundled CLI, Python modules, wrappers, and template assets. The matching
manifest hash and rendered managed-rule baseline hashes live in `config.json`.
Generated `__pycache__`, worker results, locks, backups, and transactions are not
part of the manifest or committed distribution.
