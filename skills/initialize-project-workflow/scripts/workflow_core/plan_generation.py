import json
import difflib
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
from .runtime_manifest import RUNTIME_MANIFEST_RELATIVE, render_runtime_manifest
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
    targets[RUNTIME_MANIFEST_RELATIVE] = render_runtime_manifest(targets)
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


def _legacy_template_baseline(root, relative, replacements):
    template_relative = {
        "work-flow/AGENTS.md": "work-flow/AGENTS.md.tpl",
        "work-flow/project_rules.md": "work-flow/project_rules.md.tpl",
    }.get(relative)
    if not template_relative:
        return None
    old_assets = root / "work-flow/scripts/_runtime/assets/project-template"
    template_path = old_assets / template_relative
    if not template_path.is_file():
        return None
    return render_template(old_assets, template_relative, replacements).encode("utf-8")


def _line_changes(base_lines, branch_lines):
    matcher = difflib.SequenceMatcher(a=base_lines, b=branch_lines, autojunk=False)
    return [
        (start, end, branch_lines[branch_start:branch_end])
        for tag, start, end, branch_start, branch_end in matcher.get_opcodes()
        if tag != "equal"
    ]


def _changes_overlap(left, right):
    left_start, left_end, _ = left
    right_start, right_end, _ = right
    if left_start == left_end and right_start == right_end:
        return left_start == right_start
    if left_start == left_end:
        return right_start <= left_start < right_end
    if right_start == right_end:
        return left_start <= right_start < left_end
    return max(left_start, right_start) < min(left_end, right_end)


def _three_way_merge(base, current, new):
    base_lines = base.decode("utf-8").splitlines(keepends=True)
    current_lines = current.decode("utf-8").splitlines(keepends=True)
    new_lines = new.decode("utf-8").splitlines(keepends=True)
    current_changes = _line_changes(base_lines, current_lines)
    new_changes = _line_changes(base_lines, new_lines)
    merged = []
    conflicts = []
    cursor = 0
    current_index = 0
    new_index = 0
    while current_index < len(current_changes) or new_index < len(new_changes):
        current_change = current_changes[current_index] if current_index < len(current_changes) else None
        new_change = new_changes[new_index] if new_index < len(new_changes) else None
        if current_change is not None and new_change is not None and _changes_overlap(current_change, new_change):
            if current_change == new_change:
                change = current_change
                current_index += 1
                new_index += 1
            else:
                conflicts.append({
                    "base_start_line": min(current_change[0], new_change[0]) + 1,
                    "base_end_line": max(current_change[1], new_change[1]),
                    "current_sha256": sha256_bytes("".join(current_change[2]).encode("utf-8")),
                    "new_sha256": sha256_bytes("".join(new_change[2]).encode("utf-8")),
                })
                break
        elif new_change is None or (
            current_change is not None
            and (current_change[0], current_change[1]) < (new_change[0], new_change[1])
        ):
            change = current_change
            current_index += 1
        else:
            change = new_change
            new_index += 1
        start, end, replacement = change
        if start < cursor:
            conflicts.append({
                "base_start_line": start + 1,
                "base_end_line": end,
                "current_sha256": sha256_bytes(current),
                "new_sha256": sha256_bytes(new),
            })
            break
        merged.extend(base_lines[cursor:start])
        merged.extend(replacement)
        cursor = end
    if conflicts:
        return None, conflicts
    merged.extend(base_lines[cursor:])
    return "".join(merged).encode("utf-8"), []


def _preserve_managed_customizations(root, desired, existing_config=None, replacements=None):
    """Three-way merge managed rules and preserve only unresolved/custom results."""
    preserved = []
    merged_paths = []
    conflicts = []
    baselines = (existing_config or {}).get("template_baselines", {})
    baselines = baselines if isinstance(baselines, dict) else {}
    replacements = replacements or {}
    for rel in ("work-flow/AGENTS.md", "work-flow/project_rules.md"):
        current = _read_existing_bytes(root, rel)
        text = _read_existing_text(root, rel)
        if current is None or not _is_managed(text) or rel not in desired or current == desired[rel]:
            continue
        recorded = baselines.get(rel)
        if isinstance(recorded, str) and sha256_bytes(current) == recorded:
            continue
        legacy = _legacy_template_baseline(root, rel, replacements)
        if recorded is None and legacy is not None and current == legacy:
            continue
        if legacy is None or (isinstance(recorded, str) and sha256_bytes(legacy) != recorded):
            desired[rel] = current
            conflicts.append({
                "code": "template_baseline_unavailable",
                "path": rel,
                "message": "The recorded template baseline cannot be reconstructed; resolve the managed rule upgrade explicitly.",
            })
            continue
        merged, merge_conflicts = _three_way_merge(legacy, current, desired[rel])
        if merge_conflicts:
            desired[rel] = current
            conflicts.append({
                "code": "template_merge_conflict",
                "path": rel,
                "message": "Current custom rules and the new template change overlapping lines.",
                "hunks": merge_conflicts,
            })
            continue
        desired[rel] = merged
        if merged == current:
            preserved.append(rel)
        else:
            merged_paths.append(rel)
    return preserved, merged_paths, conflicts


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
    try:
        existing_config = json.loads(initialized_config.decode("utf-8-sig")) if initialized_config else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        existing_config = {}
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

    template_baselines = {
        rel: sha256_bytes(desired[rel])
        for rel in ("work-flow/AGENTS.md", "work-flow/project_rules.md")
    }
    preserved_customizations, merged_customizations, merge_conflicts = _preserve_managed_customizations(
        root, desired, existing_config, replacements
    )

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
    desired["work-flow/config.json"] = render_config(
        mode,
        managed_files,
        template_baselines,
        sha256_bytes(desired[RUNTIME_MANIFEST_RELATIVE]),
    ).encode("utf-8")

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
        "conflicts": _conflicts_for(root) + merge_conflicts,
        "preserved_customizations": preserved_customizations,
        "merged_customizations": merged_customizations,
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
