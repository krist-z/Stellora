from pathlib import Path, PurePosixPath

from .constants import (
    CONFLICT_SUBAGENT_RULES,
    IGNORE_ENTRIES,
    RUNTIME_VERSION,
    SCHEMA_VERSION,
    TEMPLATE_VERSION,
)
from .scanning import scan_project
from .schema import add_plan_hash, read_text_preserve, safe_join, sha256_bytes, sha256_file, workspace_identity
from .templates import (
    extract_imported_sections,
    imported_section,
    render_config,
    render_project,
    render_state,
    render_template,
    template_hashes,
)


def _read_existing_text(root, relative):
    path = root / relative
    if not path.exists() or not path.is_file():
        return None
    return read_text_preserve(path)


def _read_existing_bytes(root, relative):
    path = root / relative
    if not path.exists() or not path.is_file():
        return None
    return path.read_bytes()


def _is_managed(text):
    return bool(text and "workflow-managed:" in text)


def _conflicts_for(root):
    conflicts = []
    if (root / ".concord").exists() or (root / "docs/concord").exists():
        conflicts.append({"code": "parallel_control_plane", "path": ".concord or docs/concord", "message": "A Concord control plane exists; resolve it before installing work-flow."})
    for rel in ("AGENTS.md", "project_rules.md"):
        text = _read_existing_text(root, rel)
        lowered = text.lower() if text else ""
        if text and any(rule.lower() in lowered for rule in CONFLICT_SUBAGENT_RULES):
            conflicts.append(
                {
                    "code": "contradictory_legacy_subagent_rule",
                    "path": rel,
                    "message": "Legacy subagent rule requires user resolution before migration.",
                }
            )
    return conflicts


def _collect_existing_imports(root):
    root_agents = _read_existing_text(root, "AGENTS.md")
    workflow_agents = _read_existing_text(root, "work-flow/AGENTS.md")
    workflow_rules = _read_existing_text(root, "work-flow/project_rules.md")

    root_imports = {}
    project_imports = {}
    if _is_managed(root_agents):
        root_imports.update(extract_imported_sections(root_agents))
    elif root_agents:
        root_imports["AGENTS.md"] = root_agents

    if workflow_agents:
        imported = extract_imported_sections(workflow_agents)
        if imported:
            for name, content in imported.items():
                root_imports.setdefault(name, content)
        elif not _is_managed(workflow_agents):
            root_imports.setdefault("work-flow/AGENTS.md", workflow_agents)

    if _is_managed(workflow_rules):
        project_imports.update(extract_imported_sections(workflow_rules))

    root_project_rules = _read_existing_text(root, "project_rules.md")
    if root_project_rules:
        project_imports.setdefault("project_rules.md", root_project_rules)
    if workflow_rules and not _is_managed(workflow_rules):
        project_imports.setdefault("work-flow/project_rules.md", workflow_rules)

    return root_imports, project_imports


def _imports_to_text(imports):
    text = ""
    for name in sorted(imports):
        text += imported_section(name, imports[name])
    return text


def _merge_gitignore(existing):
    text = existing or ""
    lines = text.splitlines()
    output = text
    if output and not output.endswith(("\n", "\r")):
        output += "\n"
    present = set(lines)
    for entry in IGNORE_ENTRIES:
        if entry not in present:
            output += entry + "\n"
    return output


def _runtime_hashes(runtime_root, cli_path):
    root = Path(runtime_root)
    hashes = {}
    for path in sorted(root.rglob("*.py"), key=lambda item: item.relative_to(root).as_posix().lower()):
        hashes["workflow_core/" + path.relative_to(root).as_posix()] = sha256_file(path)
    hashes["workflow_cli.py"] = sha256_file(cli_path)
    return hashes


def _runtime_targets(runtime_root, cli_path, assets_root):
    root = Path(runtime_root)
    targets = {
        "work-flow/scripts/_runtime/workflow_cli.py": Path(cli_path).read_bytes(),
    }
    for path in sorted(root.rglob("*.py"), key=lambda item: item.relative_to(root).as_posix().lower()):
        rel = path.relative_to(root).as_posix()
        targets[f"work-flow/scripts/_runtime/workflow_core/{rel}"] = path.read_bytes()

    assets = Path(assets_root)
    for path in sorted(assets.rglob("*"), key=lambda item: item.relative_to(assets).as_posix().lower()):
        if path.is_file():
            rel = path.relative_to(assets).as_posix()
            if ".." in PurePosixPath(rel).parts:
                raise ValueError(f"asset path escapes root: {rel}")
            targets[f"work-flow/scripts/_runtime/assets/project-template/{rel}"] = path.read_bytes()
    return targets


def _backup_targets(root):
    backups = {}
    for rel, prefix in (("AGENTS.md", "root-AGENTS"), ("project_rules.md", "root-project_rules"), ("work-flow/AGENTS.md", "workflow-AGENTS"), ("work-flow/project_rules.md", "workflow-project_rules")):
        content = _read_existing_bytes(root, rel)
        text = _read_existing_text(root, rel)
        if content is None or _is_managed(text):
            continue
        digest = sha256_bytes(content)[:12]
        backup_rel = f"work-flow/.runtime/migration-backups/{prefix}-{digest}.md"
        backups[backup_rel] = content
    return backups


def _preserve_managed_customizations(root, desired):
    """Keep user-edited internal rule files byte-for-byte during re-runs.

    There is no reliable way to infer which lines a user added to a managed
    rules document.  If the existing managed file differs from the freshly
    rendered scaffold, treating it as user-owned is the safe choice: runtime
    and templates can still upgrade while the custom rules remain available
    for a separate, explicit Writer migration task.
    """
    preserved = []
    for rel in ("work-flow/AGENTS.md", "work-flow/project_rules.md"):
        current = _read_existing_bytes(root, rel)
        text = _read_existing_text(root, rel)
        if current is not None and _is_managed(text) and rel in desired and current != desired[rel]:
            desired[rel] = current
            preserved.append(rel)
    return preserved


def _public_actions(root, desired, backups, deletions=()):
    actions = []
    for rel in sorted(backups, key=str.lower):
        current = _read_existing_bytes(root, rel)
        kind = "up_to_date" if current == backups[rel] else "backup"
        actions.append(
            {
                "kind": kind,
                "path": rel,
                "sha256": sha256_bytes(backups[rel]),
            }
        )
    for rel in sorted(desired, key=str.lower):
        current = _read_existing_bytes(root, rel)
        digest = sha256_bytes(desired[rel])
        kind = "up_to_date" if current == desired[rel] else "write"
        actions.append({"kind": kind, "path": rel, "sha256": digest})
    for rel in sorted(deletions, key=str.lower):
        current = _read_existing_bytes(root, rel)
        if current is not None:
            actions.append({"kind": "delete", "path": rel, "sha256": sha256_bytes(current)})
    return actions


def _changes_for_apply(root, desired, backups, deletions=()):
    changes = []
    ordered = list(sorted(backups, key=str.lower)) + list(sorted(desired, key=str.lower))
    for rel in ordered:
        content = backups.get(rel, desired.get(rel))
        if content is None:
            continue
        if _read_existing_bytes(root, rel) == content:
            continue
        safe_join(root, rel)
        current = _read_existing_bytes(root, rel)
        changes.append((rel, content, sha256_bytes(current) if current is not None else None))
    for rel in sorted(deletions, key=str.lower):
        if _read_existing_bytes(root, rel) is not None:
            safe_join(root, rel)
            current = _read_existing_bytes(root, rel)
            changes.append((rel, None, sha256_bytes(current) if current is not None else None))
    return changes


def build_init_plan(root, mode, assets_root, runtime_root, cli_path):
    root = Path(root).resolve()
    if mode not in {"new", "adopt"}:
        raise ValueError("mode must be new or adopt")

    scan = scan_project(root)
    root_imports, project_imports = _collect_existing_imports(root)
    replacements = {
        # Root AGENTS.md remains a pointer. Imported rules belong only in the
        # internal authoritative workflow file.
        "IMPORTED_ROOT_AGENTS": "",
        "IMPORTED_WORKFLOW_AGENTS": _imports_to_text(root_imports),
        "IMPORTED_PROJECT_RULES": _imports_to_text(project_imports),
    }

    existing_state = _read_existing_bytes(root, "work-flow/state.md")
    initialized_config = _read_existing_bytes(root, "work-flow/config.json")
    state_content = (
        existing_state
        if initialized_config is not None and existing_state is not None
        else render_state(mode, workspace_identity(root, scan["is_git"], scan.get("git_root"))).encode("utf-8")
    )
    desired = {
        "AGENTS.md": render_template(assets_root, "root_AGENTS.md.tpl", replacements).encode("utf-8"),
        ".gitignore": _merge_gitignore(_read_existing_text(root, ".gitignore")).encode("utf-8"),
        "work-flow/AGENTS.md": render_template(
            assets_root, "work-flow/AGENTS.md.tpl", replacements
        ).encode("utf-8"),
        "work-flow/project_rules.md": render_template(
            assets_root, "work-flow/project_rules.md.tpl", replacements
        ).encode("utf-8"),
        "work-flow/docs/PROJECT.md": render_project(scan, mode).encode("utf-8"),
        "work-flow/state.md": state_content,
    }
    desired["work-flow/config.local.json"] = _read_existing_bytes(root, "work-flow/config.local.json") or b"{}\n"

    for rel, content in _runtime_targets(runtime_root, cli_path, assets_root).items():
        desired[rel] = content

    preserved_customizations = _preserve_managed_customizations(root, desired)

    for rel in (
        "work-flow/docs/README.md.tpl",
        "work-flow/docs/decisions.md.tpl",
        "work-flow/docs/evidence/.gitkeep",
        "work-flow/docs/requirements/.gitkeep",
        "work-flow/docs/decisions/.gitkeep",
        "work-flow/docs/handoffs/.gitkeep",
        "work-flow/docs/archive/.gitkeep",
        "work-flow/.runtime/worker-results/.gitkeep",
        "work-flow/.runtime/migration-backups/.gitkeep",
        "work-flow/.runtime/transactions/.gitkeep",
        "work-flow/.runtime/operation-lock.json",
        "work-flow/scripts/workflow.ps1",
        "work-flow/scripts/workflow.sh",
        "work-flow/scripts/Invoke-ProjectWorkflow.ps1",
        "work-flow/scripts/invoke-project-workflow.sh",
        "work-flow/scripts/workflow.py",
        "work-flow/scripts/Test-ProjectWorkflow.ps1",
        "work-flow/scripts/test-project-workflow.sh",
    ):
        target_rel = rel[:-4] if rel.endswith(".tpl") else rel
        source = Path(assets_root) / rel
        if source.is_file():
            desired[target_rel] = source.read_bytes()

    existing_lock = _read_existing_bytes(root, "work-flow/.runtime/operation-lock.json")
    if existing_lock is not None:
        desired["work-flow/.runtime/operation-lock.json"] = existing_lock

    managed_files = sorted(desired.keys() | {"work-flow/config.json"})
    desired["work-flow/config.json"] = render_config(mode, managed_files).encode("utf-8")

    backups = _backup_targets(root)
    deletions = {"project_rules.md"} if (root / "project_rules.md").is_file() else set()
    actions = _public_actions(root, desired, backups, deletions)
    public_plan = {
        "schema_version": SCHEMA_VERSION,
        "operation": "init",
        "mode": mode,
        "normalized_root": str(root),
        "runtime_version": RUNTIME_VERSION,
        "template_version": TEMPLATE_VERSION,
        "source_hashes": {
            "templates": template_hashes(assets_root),
            "runtime": _runtime_hashes(runtime_root, cli_path),
            "target_inputs": scan["source_inputs"],
        },
        "scan": scan,
        "actions": actions,
        "conflicts": _conflicts_for(root),
        "preserved_customizations": preserved_customizations,
        "rule_migration_required": bool(backups or deletions),
        "target_hashes": {
            rel: (sha256_file(root / rel) if (root / rel).is_file() else None)
            for rel in sorted(set(desired) | set(backups) | deletions)
        },
    }
    return {
        "public": add_plan_hash(public_plan),
        "desired": desired,
        "backups": backups,
        "changes": _changes_for_apply(root, desired, backups, deletions),
    }
