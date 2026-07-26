import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath

from .locking import _validate_lock_document, current_operation, get_operation
from .routing import classify_worker_error, next_effort, resolve_route
from .scanning import scan_project
from .schema import safe_join, workspace_identity
from .state import read_state


READ_ROLES = {"pm", "plan-reviewer", "explorer", "code-reviewer", "risk-reviewer"}
PROTECTED_PATHS = {
    "work-flow/state.md",
    "work-flow/.state-write.guard",
    "work-flow/.runtime/operation-lock.json",
    "work-flow/.runtime/.operation-lock.guard",
}
PROTECTED_PREFIXES = (
    ".git/",
    "work-flow/.runtime/worker-results/",
    "work-flow/.runtime/transactions/",
)
LOCK_RELATIVE_PATH = "work-flow/.runtime/operation-lock.json"


class WorkerRollbackError(RuntimeError):
    def __init__(self, paths):
        self.paths = sorted(paths)
        super().__init__("worker rollback incomplete: " + ", ".join(self.paths))


def _redact(value):
    text = str(value or "")
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:access|refresh|api)[_-]?token|api[_-]?key|secret)(\s*[:=]\s*)[^\s,;]+", r"\1\2[REDACTED]", text)
    return text


def _sanitize(value):
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    return value


def _is_protected(relative):
    path = Path(relative).as_posix()
    while path.startswith("./"):
        path = path[2:]
    path = path.lstrip("/")
    return path in PROTECTED_PATHS or any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in PROTECTED_PREFIXES
    )


def _path_record(path):
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return {
            "kind": "reparse",
            "target": os.readlink(path),
            "target_is_directory": True,
        }
    if path.is_symlink():
        return {
            "kind": "symlink",
            "target": os.readlink(path),
            "target_is_directory": path.is_dir(),
        }
    if path.is_dir():
        return {"kind": "directory"}
    if path.is_file():
        try:
            mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
        except OSError:
            mode = None
        return {"kind": "file", "content": path.read_bytes(), "mode": mode}
    return {"kind": "other"}


def _snapshot(root, ignore_result=None):
    root = Path(root).resolve()
    result = {}

    def visit(directory):
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
        except OSError:
            return
        for entry in entries:
            path = Path(entry.path)
            rel = path.relative_to(root).as_posix()
            if ignore_result and rel == ignore_result:
                continue
            record = _path_record(path)
            result[rel] = record
            if record.get("kind") == "directory":
                visit(path)

    visit(root)
    return result


def _parse_timestamp(value):
    if not isinstance(value, str) or not value:
        raise ValueError("missing timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _lock_heartbeat_only(root, before_value, after_value, operation_id):
    if not before_value or not after_value:
        return False
    if before_value.get("kind") != "file" or after_value.get("kind") != "file":
        return False
    try:
        before = json.loads(before_value["content"].decode("utf-8"))
        after = json.loads(after_value["content"].decode("utf-8"))
        if _validate_lock_document(root, before) or _validate_lock_document(root, after):
            return False
        before_revision = before.get("revision")
        after_revision = after.get("revision")
        if not isinstance(before_revision, int) or not isinstance(after_revision, int) or after_revision <= before_revision:
            return False
        before_locks = {item.get("operation_id"): item for item in before.get("locks", [])}
        after_locks = {item.get("operation_id"): item for item in after.get("locks", [])}
        if set(before_locks) != set(after_locks) or operation_id not in before_locks:
            return False
        for item_id in before_locks:
            if item_id != operation_id and before_locks[item_id] != after_locks[item_id]:
                return False
        before_current = dict(before_locks[operation_id])
        after_current = dict(after_locks[operation_id])
        before_heartbeat = before_current.pop("heartbeat_at", None)
        after_heartbeat = after_current.pop("heartbeat_at", None)
        if before_current != after_current:
            return False
        if _parse_timestamp(after_heartbeat) <= _parse_timestamp(before_heartbeat):
            return False
        before_copy = dict(before)
        after_copy = dict(after)
        before_copy.pop("revision", None)
        after_copy.pop("revision", None)
        before_copy["locks"] = sorted(before_locks)
        after_copy["locks"] = sorted(after_locks)
        return before_copy == after_copy
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _changed_paths(root, before, after, operation_id):
    changed = sorted(rel for rel in set(before) | set(after) if before.get(rel) != after.get(rel))
    if LOCK_RELATIVE_PATH in changed and _lock_heartbeat_only(
        root, before.get(LOCK_RELATIVE_PATH), after.get(LOCK_RELATIVE_PATH), operation_id
    ):
        changed.remove(LOCK_RELATIVE_PATH)
    return changed


def _claimable_paths(before, after, changed):
    result = []
    for rel in changed:
        before_kind = (before.get(rel) or {}).get("kind")
        after_kind = (after.get(rel) or {}).get("kind")
        if {before_kind, after_kind}.issubset({None, "directory"}):
            continue
        result.append(rel)
    return result


def _json_events(stdout):
    events, errors, warnings = [], [], []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(value)
        if isinstance(value, dict):
            if value.get("type") == "error":
                errors.append(value)
            item = value.get("item")
            if value.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "error":
                warnings.append(item)
            if value.get("type") in {"turn.failed", "thread.error"}:
                errors.append(value)
    return events, errors, warnings


def _allowed_changed(changed, allowed):
    if any(_is_protected(path) for path in changed):
        return False
    if not allowed:
        return True
    normalized = [Path(item).as_posix().rstrip("/") for item in allowed]
    return all(
        not _is_protected(path) and any(path == root or path.startswith(root + "/") for root in normalized)
        for path in changed
    )


def _allowed_path_conflicts_protected(relative):
    path = Path(relative).as_posix().strip("/")
    protected_roots = set(PROTECTED_PATHS) | {prefix.rstrip("/") for prefix in PROTECTED_PREFIXES}
    return any(
        path == protected or path.startswith(protected + "/") or protected.startswith(path + "/")
        for protected in protected_roots
    )


def _remove_path(path):
    is_junction = getattr(path, "is_junction", None)
    if path.is_symlink() or (callable(is_junction) and is_junction()) or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists() and path.is_dir():
        shutil.rmtree(path)


def _restore_record(path, record):
    kind = record.get("kind")
    if kind == "directory":
        path.mkdir(parents=True, exist_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind in {"symlink", "reparse"}:
        os.symlink(
            record["target"],
            path,
            target_is_directory=bool(record.get("target_is_directory")),
        )
        return
    if kind == "file":
        path.write_bytes(record["content"])
        if record.get("mode") is not None:
            try:
                os.chmod(path, record["mode"])
            except OSError:
                pass


def _restore_unauthorized(root, before, changed, allowed):
    unauthorized = [rel for rel in changed if _is_protected(rel) or not _allowed_changed([rel], allowed)]
    for rel in sorted(unauthorized, key=lambda item: len(Path(item).parts), reverse=True):
        path = Path(root) / rel
        _remove_path(path)
    for rel in sorted(
        (item for item in unauthorized if (before.get(item) or {}).get("kind") == "directory"),
        key=lambda item: len(Path(item).parts),
    ):
        _restore_record(Path(root) / rel, before[rel])
    for rel in sorted(
        (item for item in unauthorized if item in before and before[item].get("kind") != "directory"),
        key=lambda item: len(Path(item).parts),
    ):
        _restore_record(Path(root) / rel, before[rel])
    restored_snapshot = _snapshot(root)
    failed = [rel for rel in unauthorized if restored_snapshot.get(rel) != before.get(rel)]
    if failed:
        raise WorkerRollbackError(failed)
    return unauthorized


def _observed_model_from_events(events):
    """Extract only CLI event metadata, never the model's response body."""
    for event in events:
        if not isinstance(event, dict):
            continue
        for key in ("model", "model_name"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        thread = event.get("thread")
        if isinstance(thread, dict):
            for key in ("model", "model_name"):
                value = thread.get(key)
                if isinstance(value, str) and value:
                    return value
    return None


def _non_git_workspace_is_trusted(root):
    local_path = Path(root) / "work-flow" / "config.local.json"
    try:
        local = json.loads(local_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    trust = local.get("non_git_trust") if isinstance(local, dict) else None
    return bool(
        isinstance(trust, dict)
        and trust.get("trusted") is True
        and trust.get("workspace_id") == workspace_identity(root)
    )


def trust_command(args):
    root = Path(args.root).resolve()
    local_path = root / "work-flow" / "config.local.json"
    try:
        local = json.loads(local_path.read_text(encoding="utf-8")) if local_path.is_file() else {}
    except (OSError, json.JSONDecodeError) as exc:
        return 2, {"error": "local_config_invalid", "message": str(exc)}
    if not isinstance(local, dict):
        return 2, {"error": "local_config_invalid"}
    workspace_id = workspace_identity(root)
    if args.action == "status":
        return 0, {
            "workspace_id": workspace_id,
            "is_git": scan_project(root)["is_git"],
            "non_git_trusted": _non_git_workspace_is_trusted(root),
        }
    if args.action == "grant-non-git":
        if scan_project(root)["is_git"]:
            return 2, {"error": "non_git_trust_not_applicable"}
        local["non_git_trust"] = {
            "trusted": True,
            "workspace_id": workspace_id,
            "granted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
    elif args.action == "revoke-non-git":
        local.pop("non_git_trust", None)
    else:
        return 2, {"error": "unsupported_trust_action"}
    local_path.parent.mkdir(parents=True, exist_ok=True)
    temp = local_path.with_name(f".{local_path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temp.write_text(json.dumps(local, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, local_path)
    return 0, {
        "status": "granted" if args.action == "grant-non-git" else "revoked",
        "workspace_id": workspace_id,
        "non_git_trusted": _non_git_workspace_is_trusted(root),
    }


def build_worker_command(root, route, prompt_file, output_schema, result_file):
    command = [
        "codex", "exec", "--ephemeral", "--json", "--model", route["requested_model"],
        "--config", f'model_reasoning_effort="{route["effective_effort"]}"',
        "--disable", "multi_agent", "--config", "agents.enabled=false",
        "--sandbox", "read-only" if route["role"] in READ_ROLES else "workspace-write",
        "--cd", str(root), "--output-last-message", str(result_file),
    ]
    if output_schema:
        command.extend(["--output-schema", str(output_schema)])
    if not scan_project(root)["is_git"]:
        if not _non_git_workspace_is_trusted(root):
            raise ValueError("non-Git worker requires workspace-bound trust in work-flow/config.local.json")
        command.append("--skip-git-repo-check")
    command.append("-")
    return command


def _result_schema(task_id, operation_id, route):
    return {
        "schema_version": 1,
        "task_id": task_id,
        "operation_id": operation_id,
        "role": route["role"],
        "backend": "codex-exec",
        "requested_model": route["requested_model"],
        "configured_model": route["requested_model"],
        "cli_reported_model": None,
        "provider_observed_model": None,
        "provider_attestation": "unavailable",
        "requested_effort": route["requested_effort"],
        "configured_effort": route["effective_effort"],
        "provider_observed_effort": None,
        "reasoning_effort": route["effective_effort"],
        "status": "blocked",
        "summary": "",
        "changed_files": [],
        "validation": [],
        "findings": [],
        "new_backlog_items": [],
        "blockers": [],
    }


def _worker_output_schema():
    validation_item = {
        "type": "object",
        "anyOf": [
            {
                "required": ["command", "exit_code"],
                "properties": {
                    "command": {"type": "string", "minLength": 1},
                    "exit_code": {"const": 0},
                },
            },
            {
                "required": ["evidence", "status"],
                "properties": {
                    "evidence": {"type": "string", "minLength": 1},
                    "status": {"const": "not_applicable"},
                },
            },
        ],
    }
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["schema_version", "task_id", "operation_id", "role", "backend", "model", "reasoning_effort", "status", "summary", "changed_files", "validation", "findings", "new_backlog_items", "blockers"],
        "properties": {
            "schema_version": {"const": 1}, "task_id": {"type": "string"}, "operation_id": {"type": "string"},
            "role": {"type": "string"}, "backend": {"enum": ["native", "codex-exec"]}, "model": {"type": "string"},
            "reasoning_effort": {"type": "string"}, "status": {"enum": ["completed", "blocked", "failed"]},
            "summary": {"type": "string"}, "changed_files": {"type": "array", "items": {"type": "string"}},
            "validation": {"type": "array", "items": {"type": "object"}}, "findings": {"type": "array"}, "new_backlog_items": {"type": "array"}, "blockers": {"type": "array"},
        },
        "allOf": [{
            "if": {"properties": {"status": {"const": "completed"}}, "required": ["status"]},
            "then": {"properties": {"validation": {"type": "array", "minItems": 1, "items": validation_item}}},
        }],
    }


def _validate_completed_evidence(validation, role):
    if not isinstance(validation, list) or not validation:
        return False
    for item in validation:
        if not isinstance(item, dict) or not item:
            return False
        command = item.get("command")
        exit_code = item.get("exit_code")
        if isinstance(command, str) and command.strip() and isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code == 0:
            continue
        evidence = item.get("evidence")
        if role in READ_ROLES and isinstance(evidence, str) and evidence.strip() and item.get("status") == "not_applicable":
            continue
        return False
    return True


def worker_command(args):
    try:
        root = Path(args.root).resolve()
        timeout_seconds = int(getattr(args, "timeout_seconds", 300))
        if timeout_seconds < 1 or timeout_seconds > 1800:
            return 2, {"error": "invalid_timeout_seconds"}
        operation = get_operation(root, args.operation_id)
        if not operation:
            return 4, {"error": "operation_lock_required"}
        try:
            uuid.UUID(args.task_id)
        except (ValueError, AttributeError):
            return 2, {"error": "invalid_task_id"}
        route = resolve_route(args.role)
        if operation.get("task_id") != args.task_id or operation.get("role") != route["role"]:
            return 4, {"error": "operation_identity_mismatch"}
        start_revision = read_state(root).get("revision", 0)
        if start_revision != args.expected_revision:
            return 4, {"error": "revision_conflict", "current_revision": start_revision}
        runtime_dir = root / "work-flow" / ".runtime" / "worker-results"
        result_file = runtime_dir / f"{args.task_id}-{args.operation_id}.json"
        if args.prompt_file:
            prompt_path = Path(args.prompt_file)
            prompt_path = prompt_path.resolve() if prompt_path.is_absolute() else (root / prompt_path).resolve()
            try:
                prompt_path.relative_to(root)
            except ValueError:
                return 2, {"error": "prompt_file_escape"}
            prompt = prompt_path.read_text(encoding="utf-8")
        else:
            prompt = "Execute the assigned leaf workflow role and return a concise structured result."
        allowed = []
        for value in args.allowed_path or []:
            candidate = Path(value)
            if candidate.is_absolute():
                try:
                    value = candidate.resolve().relative_to(root).as_posix()
                except ValueError:
                    return 2, {"error": "allowed_path_escape", "path": value}
            if str(value).strip() in {"", "."} or ".." in PurePosixPath(str(value).replace("\\", "/")).parts:
                return 2, {"error": "allowed_path_escape", "path": value}
            normalized_allowed = Path(value).as_posix().rstrip("/")
            if _allowed_path_conflicts_protected(normalized_allowed):
                return 2, {"error": "allowed_path_protected", "path": value}
            try:
                safe_join(root, normalized_allowed)
            except ValueError:
                return 2, {"error": "allowed_path_escape", "path": value}
            allowed.append(normalized_allowed)
        if route["role"] not in READ_ROLES and not allowed:
            return 2, {"error": "allowed_path_required_for_write_worker"}
        if not scan_project(root)["is_git"] and not _non_git_workspace_is_trusted(root):
            return 3, {
                "error": "non_git_workspace_not_trusted",
                "message": "Record explicit workspace-bound trust in work-flow/config.local.json before using --skip-git-repo-check.",
                "workspace_id": workspace_identity(root),
            }
        context = (
            "WORKFLOW_WORKER_CONTEXT\n"
            "schema_version: 1\n"
            f"task_id: {args.task_id}\noperation_id: {args.operation_id}\nrole: {route['role']}\n"
            "allowed_paths:\n" + "\n".join(f"  - {item}" for item in allowed) +
            "\nEND_WORKFLOW_WORKER_CONTEXT\n"
            "You are a leaf worker. Do not spawn agents, invoke codex workers, or modify state.md, operation locks, or aggregate result files.\n"
        )
        prompt = context + prompt
        runtime_dir.mkdir(parents=True, exist_ok=True)
        result_file.unlink(missing_ok=True)
        result_rel = result_file.relative_to(root).as_posix()
        before = _snapshot(root, result_rel)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".schema.json", delete=False) as schema_handle:
            json.dump(_worker_output_schema(), schema_handle)
            schema_path = Path(schema_handle.name)
        attempts = []
        try:
            while True:
                command = build_worker_command(root, route, args.prompt_file, schema_path, result_file)
                completed = subprocess.run(command, input=prompt, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False, timeout=timeout_seconds)
                attempt_events, attempt_errors, _ = _json_events(completed.stdout)
                combined_error = completed.stderr + "\n" + json.dumps(attempt_errors, ensure_ascii=False)
                category = classify_worker_error(combined_error) if completed.returncode != 0 else None
                attempts.append({
                    "model": route["requested_model"], "reasoning_effort": route["effective_effort"],
                    "exit_code": completed.returncode, "error_category": category,
                })
                if completed.returncode == 0:
                    break
                after_attempt = _snapshot(root, result_rel)
                changed_during_attempt = _changed_paths(root, before, after_attempt, args.operation_id)
                fallback = next_effort(route, route["effective_effort"], combined_error)
                if category != "unsupported_effort" or not fallback or changed_during_attempt:
                    break
                route["effective_effort"] = fallback
                route["effort_fallback_reason"] = "explicit_unsupported_effort"
                result_file.unlink(missing_ok=True)
        except subprocess.TimeoutExpired as exc:
            after = _snapshot(root, result_rel)
            changed = _changed_paths(root, before, after, args.operation_id)
            restored = _restore_unauthorized(root, before, changed, ["__timeout_restore_all__"])
            changed_files = _claimable_paths(before, after, changed)
            return 3, {
                "schema_version": 1, "error": "worker_timeout", "status": "blocked",
                "backend": "codex-exec", "role": route["role"],
                "requested_model": route["requested_model"],
                "requested_effort": route["requested_effort"],
                "reasoning_effort": route["effective_effort"],
                "effort_fallback_reason": route["effort_fallback_reason"],
                "error_category": "blocked_external", "task_id": args.task_id,
                "operation_id": args.operation_id, "changed_files": changed_files,
                "workspace_changes": changed,
                "restored_files": restored,
                "stderr_tail": _redact(exc.stderr or "")[-4000:],
            }
        finally:
            schema_path.unlink(missing_ok=True)
        after = _snapshot(root, result_rel)
        changed = _changed_paths(root, before, after, args.operation_id)
        changed_files = _claimable_paths(before, after, changed)
        unauthorized = changed if route["role"] in READ_ROLES else _restore_unauthorized(root, before, changed, allowed)
        if route["role"] in READ_ROLES:
            _restore_unauthorized(root, before, changed, ["__read_only_never__"])
        events, errors, warnings = _json_events(completed.stdout)
        payload = _result_schema(args.task_id, args.operation_id, route)
        payload.update({
            "status": "blocked" if errors or completed.returncode != 0 or unauthorized else "completed",
            "exit_code": completed.returncode,
            "changed_files": changed_files,
            "workspace_changes": changed,
            "errors": _sanitize(errors),
            "warnings": _sanitize(warnings),
            "unauthorized_changes": unauthorized,
            "stderr_tail": _redact(completed.stderr)[-4000:],
            "result_file": str(result_file),
            "effective_effort": route["effective_effort"],
            "effort_fallback_reason": route["effort_fallback_reason"],
            "start_revision": start_revision,
            "attempts": attempts,
        })
        if result_file.exists():
            try:
                agent_result = json.loads(result_file.read_text(encoding="utf-8"))
                if isinstance(agent_result, dict):
                    required_result_keys = {"schema_version", "task_id", "operation_id", "role", "backend", "model", "reasoning_effort", "status", "summary", "changed_files", "validation", "findings", "new_backlog_items", "blockers"}
                    result_shape_invalid = False
                    if not required_result_keys.issubset(agent_result):
                        payload["status"] = "blocked"
                        payload.setdefault("blockers", []).append("result_schema_incomplete")
                        result_shape_invalid = True
                    if agent_result.get("schema_version") != 1 or agent_result.get("status") not in {"completed", "blocked", "failed"}:
                        payload["status"] = "blocked"
                        payload.setdefault("blockers", []).append("result_schema_invalid")
                        result_shape_invalid = True
                    if not isinstance(agent_result.get("summary"), str) or any(
                        not isinstance(agent_result.get(key), list)
                        for key in ("changed_files", "validation", "findings", "new_backlog_items", "blockers")
                    ) or any(
                        not isinstance(value, str)
                        for value in (agent_result.get("changed_files") if isinstance(agent_result.get("changed_files"), list) else [])
                    ):
                        payload["status"] = "blocked"
                        payload.setdefault("blockers", []).append("result_schema_invalid")
                        result_shape_invalid = True
                    if agent_result.get("task_id", args.task_id) != args.task_id or agent_result.get("operation_id", args.operation_id) != args.operation_id or agent_result.get("role", route["role"]) != route["role"]:
                        payload["status"] = "blocked"
                        payload.setdefault("blockers", []).append("result_identity_mismatch")
                    if agent_result.get("backend") != "codex-exec":
                        payload["status"] = "blocked"
                        payload.setdefault("blockers", []).append("result_backend_mismatch")
                    if agent_result.get("model") != route["requested_model"]:
                        payload["status"] = "blocked"
                        payload.setdefault("blockers", []).append("result_model_mismatch")
                    if agent_result.get("reasoning_effort") not in route["requested_efforts"] or agent_result.get("reasoning_effort") != route["effective_effort"]:
                        payload["status"] = "blocked"
                        payload.setdefault("blockers", []).append("result_effort_mismatch")
                    if agent_result.get("status") == "completed":
                        if not agent_result.get("validation"):
                            payload["status"] = "blocked"
                            payload.setdefault("blockers", []).append("validation_evidence_missing")
                        elif not _validate_completed_evidence(agent_result.get("validation"), route["role"]):
                            payload["status"] = "blocked"
                            payload.setdefault("blockers", []).append("validation_evidence_invalid")
                    claimed_values = agent_result.get("changed_files") if isinstance(agent_result.get("changed_files"), list) else []
                    claimed_changes = sorted(Path(value).as_posix() for value in claimed_values if isinstance(value, str))
                    if claimed_changes != sorted(changed_files):
                        payload["status"] = "blocked"
                        payload.setdefault("blockers", []).append("workspace_fingerprint_mismatch")
                    if not result_shape_invalid and agent_result.get("status") in {"blocked", "failed"}:
                        payload["status"] = agent_result["status"]
                    payload["agent_result"] = _sanitize(agent_result)
                    payload["cli_reported_model"] = _observed_model_from_events(events)
                    if payload["status"] == "completed" and payload["cli_reported_model"] and payload["cli_reported_model"] != route["requested_model"]:
                        payload["status"] = "blocked"
                        payload.setdefault("blockers", []).append("cli_reported_model_mismatch")
                else:
                    payload["status"] = "blocked"
                    payload.setdefault("blockers", []).append("result_not_object")
            except (OSError, json.JSONDecodeError):
                payload["status"] = "blocked"
                payload.setdefault("blockers", []).append("invalid_result_json")
        else:
            payload["status"] = "blocked"
            payload.setdefault("blockers", []).append("result_file_missing")
        if read_state(root).get("revision", 0) != start_revision:
            payload["status"] = "blocked"
            payload.setdefault("blockers", []).append("revision_changed_during_worker")
        final_operation = get_operation(root, args.operation_id)
        if not final_operation or final_operation.get("task_id") != args.task_id or final_operation.get("role") != route["role"]:
            payload["status"] = "blocked"
            payload.setdefault("blockers", []).append("operation_changed_during_worker")
        if payload["status"] != "completed":
            restored = _restore_unauthorized(root, before, changed, ["__restore_no_worker_paths__"])
            payload["restored_files"] = sorted(set(payload.get("restored_files", [])) | set(restored))
        if payload["status"] == "completed":
            return 0, payload
        if payload["status"] == "failed":
            return 2, payload
        if completed.returncode != 0:
            category = classify_worker_error(completed.stderr + "\n" + json.dumps(errors, ensure_ascii=False))
            payload["error_category"] = category
            return (3 if category == "blocked_external" else 2), payload
        validation_blockers = {
            "result_schema_incomplete", "result_schema_invalid", "result_identity_mismatch",
            "result_backend_mismatch", "result_model_mismatch", "result_effort_mismatch",
            "workspace_fingerprint_mismatch", "result_not_object", "invalid_result_json",
            "revision_changed_during_worker", "operation_changed_during_worker",
            "validation_evidence_missing", "validation_evidence_invalid",
        }
        return (2 if validation_blockers.intersection(payload.get("blockers", [])) or unauthorized else 3), payload
    except WorkerRollbackError as exc:
        return 6, {"error": "worker_rollback_incomplete", "status": "failed", "paths": exc.paths}
    except (OSError, ValueError) as exc:
        return 3, {"error": "worker_blocked", "message": str(exc)}
