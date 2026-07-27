import json
import os
from pathlib import Path

from .constants import RUNTIME_VERSION, SCHEMA_VERSION, TEMPLATE_VERSION
from .plan_generation import (
    _changes_for_apply,
    _collect_existing_imports,
    _imports_to_text,
    _public_actions,
    _runtime_hashes,
    _runtime_targets,
    _backup_targets,
    _conflicts_for,
    _merge_gitignore,
    _preserve_managed_customizations,
)
from .locking import _validate_lock_document
from .migration import build_registered_migration
from .migration import parse_state_document, render_state_document
from .runtime_manifest import RUNTIME_MANIFEST_RELATIVE
from .schema import add_plan_hash, pretty_json, sha256_bytes
from .templates import render_config, render_template, template_hashes
from .transactions import FileChange, TransactionError, apply_file_changes
from .validation import validate_project


def _existing_project_mode(root):
    config = root / "work-flow/config.json"
    if not config.exists():
        return "adopt"
    try:
        return json.loads(config.read_text(encoding="utf-8")).get("mode", "adopt")
    except Exception:
        return "adopt"


def build_upgrade_plan(root, assets_root, runtime_root, cli_path):
    root = Path(root).resolve()
    config_path = root / "work-flow/config.json"
    if not config_path.is_file():
        raise ValueError("upgrade requires an initialized project workflow")
    try:
        config_bytes = config_path.read_bytes()
        existing_config = json.loads(config_bytes.decode("utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"project workflow config is invalid: {exc}") from exc
    state_path = root / "work-flow/state.md"
    project_path = root / "work-flow/docs/PROJECT.md"
    if not state_path.is_file():
        raise ValueError("manual recovery required: workflow state is missing")
    if not project_path.is_file():
        raise ValueError("manual recovery required: project facts are missing")
    state_bytes = state_path.read_bytes()
    mode = _existing_project_mode(root)
    root_imports, project_imports = _collect_existing_imports(root)
    replacements = {
        "IMPORTED_ROOT_AGENTS": "",
        "IMPORTED_WORKFLOW_AGENTS": _imports_to_text(root_imports),
        "IMPORTED_PROJECT_RULES": _imports_to_text(project_imports),
    }
    desired = {
        "work-flow/AGENTS.md": render_template(assets_root, "work-flow/AGENTS.md.tpl", replacements).encode("utf-8"),
        "work-flow/project_rules.md": render_template(assets_root, "work-flow/project_rules.md.tpl", replacements).encode("utf-8"),
    }
    local_config = root / "work-flow/config.local.json"
    desired["work-flow/config.local.json"] = local_config.read_bytes() if local_config.is_file() else b"{}\n"
    gitignore = root / ".gitignore"
    desired[".gitignore"] = _merge_gitignore(
        gitignore.read_text(encoding="utf-8") if gitignore.is_file() else None
    ).encode("utf-8")
    root_agents = root / "AGENTS.md"
    if not root_agents.exists() or "workflow-managed:root-agents:" in root_agents.read_text(encoding="utf-8", errors="replace"):
        desired["AGENTS.md"] = render_template(assets_root, "root_AGENTS.md.tpl", replacements).encode("utf-8")
    for rel in (
        "work-flow/docs/README.md.tpl",
        "work-flow/docs/decisions.md.tpl",
        "work-flow/scripts/workflow.ps1",
        "work-flow/scripts/workflow.sh",
        "work-flow/scripts/workflow.py",
        "work-flow/scripts/Test-ProjectWorkflow.ps1",
        "work-flow/scripts/test-project-workflow.sh",
        "work-flow/scripts/Invoke-ProjectWorkflow.ps1",
        "work-flow/scripts/invoke-project-workflow.sh",
        "work-flow/docs/requirements/.gitkeep",
        "work-flow/docs/decisions/.gitkeep",
        "work-flow/docs/handoffs/.gitkeep",
        "work-flow/docs/archive/.gitkeep",
        "work-flow/docs/evidence/.gitkeep",
        "work-flow/.runtime/worker-results/.gitkeep",
        "work-flow/.runtime/migration-backups/.gitkeep",
        "work-flow/.runtime/transactions/.gitkeep",
    ):
        target_rel = rel[:-4] if rel.endswith(".tpl") else rel
        desired[target_rel] = (Path(assets_root) / rel).read_bytes()
    for rel, content in _runtime_targets(runtime_root, cli_path, assets_root).items():
        desired[rel] = content

    lock_rel = "work-flow/.runtime/operation-lock.json"
    lock_path = root / lock_rel
    if lock_path.is_file():
        try:
            lock_document = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"manual recovery required: operation lock is invalid: {exc}") from exc
        lock_error = _validate_lock_document(root, lock_document)
        if lock_error:
            raise ValueError(f"manual recovery required: operation lock is invalid: {lock_error}")
        if lock_document.get("locks"):
            raise ValueError("upgrade requires no active workflow operation locks")
        desired[lock_rel] = lock_path.read_bytes()
    else:
        desired[lock_rel] = (Path(assets_root) / lock_rel).read_bytes()
    template_baselines = {
        rel: sha256_bytes(desired[rel])
        for rel in ("work-flow/AGENTS.md", "work-flow/project_rules.md")
    }
    preserved_customizations, merged_customizations, merge_conflicts = _preserve_managed_customizations(
        root, desired, existing_config, replacements
    )
    managed_files = sorted(set(desired.keys()) | set(existing_config.get("managed_files", [])) | {"work-flow/config.json", "work-flow/docs/PROJECT.md", "work-flow/state.md", ".gitignore"})
    runtime_manifest_sha256 = sha256_bytes(desired[RUNTIME_MANIFEST_RELATIVE])
    current_defaults = json.loads(render_config(
        mode, managed_files, template_baselines, runtime_manifest_sha256
    ))
    migration = build_registered_migration(
        root,
        existing_config,
        config_bytes,
        state_bytes,
        managed_files,
        current_defaults,
    )
    if migration:
        desired.update(migration["desired"])
        desired["work-flow/config.json"] = pretty_json(migration["config"]).encode("utf-8")
    else:
        state = parse_state_document(state_bytes.decode("utf-8-sig"))
        if state.get("runtime_version") != RUNTIME_VERSION or state.get("template_version") != TEMPLATE_VERSION:
            state = dict(state)
            state["runtime_version"] = RUNTIME_VERSION
            state["template_version"] = TEMPLATE_VERSION
            state["revision"] = int(state.get("revision", 0)) + 1
            desired["work-flow/state.md"] = render_state_document(state).encode("utf-8")
        desired["work-flow/config.json"] = render_config(
            mode, managed_files, template_baselines, runtime_manifest_sha256
        ).encode("utf-8")

    backups = _backup_targets(root)
    deletions = {"project_rules.md"} if (root / "project_rules.md").is_file() else set()
    actions = _public_actions(root, desired, backups, deletions)
    public_plan = {
        "schema_version": SCHEMA_VERSION,
        "operation": "upgrade",
        "normalized_root": str(root),
        "runtime_version": RUNTIME_VERSION,
        "template_version": TEMPLATE_VERSION,
        "migration_chain": [migration["migration_id"]] if migration else [],
        "migration": ({key: value for key, value in migration.items() if key not in {"desired", "config"}} if migration else None),
        "source_hashes": {
            "templates": template_hashes(assets_root),
            "runtime": _runtime_hashes(runtime_root, cli_path),
            "target_inputs": {
                rel: sha256_bytes((root / rel).read_bytes())
                for rel in ("AGENTS.md", "work-flow/project_rules.md", "work-flow/config.json", "work-flow/state.md")
                if (root / rel).exists()
            },
        },
        "actions": actions,
        "conflicts": _conflicts_for(root) + merge_conflicts,
        "preserved_customizations": preserved_customizations,
        "merged_customizations": merged_customizations,
        "target_hashes": {rel: (sha256_bytes((root / rel).read_bytes()) if (root / rel).is_file() else None) for rel in sorted(set(desired) | set(backups) | deletions)},
    }
    return {
        "public": add_plan_hash(public_plan),
        "desired": desired,
        "changes": _changes_for_apply(root, desired, backups, deletions),
    }


def upgrade_dry_run(root, assets_root, runtime_root, cli_path):
    return build_upgrade_plan(root, assets_root, runtime_root, cli_path)["public"]


def upgrade_apply(root, plan_hash, assets_root, runtime_root, cli_path, fail_after=None, confirm_rule_migration=False):
    plan = build_upgrade_plan(root, assets_root, runtime_root, cli_path)
    public = plan["public"]
    if public["plan_hash"] != plan_hash:
        return 2, {
            "error": "plan_hash_mismatch",
            "expected_plan_hash": public["plan_hash"],
            "provided_plan_hash": plan_hash,
            "plan": public,
        }
    if public.get("conflicts"):
        return 2, {"error": "unresolved_conflicts", "conflicts": public["conflicts"], "plan": public}
    legacy_targets = [item for item in public.get("actions", []) if item.get("path") in {"AGENTS.md", "project_rules.md"} and item.get("kind") in {"write", "delete"}]
    if legacy_targets and not confirm_rule_migration:
        return 2, {"error": "rule_migration_confirmation_required", "paths": [item["path"] for item in public.get("actions", []) if item.get("kind") == "backup"], "plan": public}
    if fail_after is None:
        injected = os.environ.get("WORKFLOW_CORE_FAIL_AFTER_ACTION")
        fail_after = int(injected) if injected else None
    changes = [FileChange(relative_path=rel, content=content, expected_sha256=expected) for rel, content, expected in plan["changes"]]
    try:
        result = apply_file_changes(root, changes, fail_after=fail_after, post_validate=lambda: validate_project(root, strict=True))
    except TransactionError as exc:
        payload = {"error": "transaction_failed", "message": str(exc), "plan": public}
        payload.update(getattr(exc, "details", {}))
        return getattr(exc, "exit_code", 5), payload
    return 0, {
        "status": "applied", "changed": result["changed"],
        "transaction_id": result.get("transaction_id"),
        "transaction_record": result.get("transaction_record"),
        "plan_hash": public["plan_hash"], "plan": public,
    }
