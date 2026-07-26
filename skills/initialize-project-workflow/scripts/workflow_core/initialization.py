import json
import os
from pathlib import Path

from .locking import _read as read_lock_document, _validate_lock_document, lock_path
from .plan_generation import build_init_plan
from .state import read_state
from .transactions import FileChange, TransactionError, apply_file_changes
from .validation import validate_project


def _validate_existing_control_plane(root):
    root = Path(root).resolve()
    if not (root / "work-flow/config.json").is_file():
        return
    try:
        read_state(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"manual recovery required: workflow state is missing or invalid: {exc}") from exc
    path = lock_path(root)
    if not path.is_file():
        raise ValueError("manual recovery required: operation lock is missing")
    try:
        document = read_lock_document(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"manual recovery required: operation lock is invalid: {exc}") from exc
    lock_error = _validate_lock_document(root, document)
    if lock_error:
        raise ValueError(f"manual recovery required: operation lock is invalid: {lock_error}")
    if document.get("locks"):
        raise ValueError("manual recovery required: active workflow operation locks must be released or recovered")


def init_dry_run(root, mode, assets_root, runtime_root, cli_path):
    _validate_existing_control_plane(root)
    return build_init_plan(Path(root).resolve(), mode, assets_root, runtime_root, cli_path)["public"]


def init_apply(root, mode, plan_hash, assets_root, runtime_root, cli_path, fail_after=None, confirm_rule_migration=False):
    _validate_existing_control_plane(root)
    plan = build_init_plan(Path(root).resolve(), mode, assets_root, runtime_root, cli_path)
    public = plan["public"]
    if public["plan_hash"] != plan_hash:
        return 2, {
            "error": "plan_hash_mismatch",
            "expected_plan_hash": public["plan_hash"],
            "provided_plan_hash": plan_hash,
            "plan": public,
        }
    if public["conflicts"]:
        return 2, {"error": "unresolved_conflicts", "conflicts": public["conflicts"], "plan": public}
    if public.get("rule_migration_required") and not confirm_rule_migration:
        return 2, {
            "error": "rule_migration_confirmation_required",
            "paths": [item.get("path") for item in public.get("actions", []) if item.get("kind") == "backup"],
            "message": "Re-run apply with --confirm-rule-migration after reviewing the verbatim import and backup.",
            "plan": public,
        }

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
