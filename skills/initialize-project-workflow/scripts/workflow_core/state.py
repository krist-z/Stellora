import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .constants import STATE_END, STATE_START, SCHEMA_VERSION
from .locking import WRITE_ROLES, current_operation, get_operation
from .schema import pretty_json, safe_join, sha256_file, workspace_identity


PHASES = ("intake", "planned", "approved", "implementing", "validating", "reviewing", "reporting", "complete")
KIND_VALUES = {"plan", "plan-review", "code", "text", "explore", "test", "code-review", "risk", "other"}
LEVEL_VALUES = {"L1", "L2", "L3", "L4"}
L2_CONFIRMATION_REASONS = {
    "behavior_or_compatibility_ambiguous",
    "public_api_change",
    "rule_conflict",
    "scope_expansion",
    "new_runtime_dependency",
}
TRANSITIONS = {
    "intake": {"planned", "implementing"},
    "planned": {"approved", "implementing"},
    "approved": {"implementing"},
    "implementing": {"validating"},
    "validating": {"reviewing", "reporting", "implementing"},
    "reviewing": {"reporting", "implementing"},
    "reporting": {"complete"},
    "complete": set(),
}


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_path(root):
    return Path(root) / "work-flow" / "state.md"


def read_state(root):
    path = state_path(root)
    if not path.exists():
        raise ValueError("workflow state is missing")
    text = path.read_text(encoding="utf-8")
    if text.count(STATE_START) != 1 or text.count(STATE_END) != 1:
        raise ValueError("workflow state sentinels are invalid")
    start = text.index(STATE_START) + len(STATE_START)
    end = text.index(STATE_END)
    data = json.loads(text[start:end].strip())
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("workflow state schema version is unsupported")
    expected_workspace = workspace_identity(root)
    if data.get("workspace_id") != expected_workspace:
        raise ValueError("workflow state workspace identity mismatch")
    for key, default in (("revision", 0), ("tasks", {}), ("completed_tasks", {}), ("recent_events", []), ("active_task_id", None)):
        data.setdefault(key, default)
    if len(data["recent_events"]) > 50:
        data["recent_events"] = data["recent_events"][-50:]
    _hydrate_task_summaries(root, data)
    return data


def _render_state(data):
    return f"# Workflow State\n\n{STATE_START}\n{pretty_json(data)}{STATE_END}\n\n人类可读投影由 runtime 维护；JSON 哨兵块和引用哈希是机器权威。\n"


TASK_STATE_START = "---workflow-task-json-v1---"
TASK_STATE_END = "---end-workflow-task-json---"


def _display_name(task):
    title = re.sub(r"[^\w\u3400-\u9fff.-]+", "-", str(task.get("title", "task")), flags=re.UNICODE).strip("-._")
    return title or "task"


def _task_state_relative(task):
    directory = f"{task.get('display_seq')}_{_display_name(task)}_{task.get('level')}"
    return f"work-flow/docs/requirements/{directory}/task-state.md"


def _render_task_state(task):
    return (
        "---\n"
        f"task_id: {task.get('task_id')}\n"
        f"display_seq: {task.get('display_seq')}\n"
        f"level: {task.get('level')}\n"
        "---\n\n"
        + TASK_STATE_START + "\n"
        + pretty_json(task)
        + TASK_STATE_END + "\n"
    )


def _write_task_state(root, task):
    relative = _task_state_relative(task)
    path = safe_join(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temp.write_text(_render_task_state(task), encoding="utf-8", newline="\n")
    os.replace(temp, path)
    return relative, sha256_file(path)


def _read_task_state(root, summary):
    relative = summary.get("state_ref")
    expected_hash = summary.get("state_sha256")
    if not relative or not expected_hash:
        raise ValueError("inactive task summary is missing its state reference")
    path = safe_join(root, relative)
    if not path.is_file() or sha256_file(path) != expected_hash:
        raise ValueError("inactive task state is missing or changed")
    text = path.read_text(encoding="utf-8")
    if text.count(TASK_STATE_START) != 1 or text.count(TASK_STATE_END) != 1:
        raise ValueError("inactive task state sentinels are invalid")
    start = text.index(TASK_STATE_START) + len(TASK_STATE_START)
    end = text.index(TASK_STATE_END)
    task = json.loads(text[start:end].strip())
    if task.get("task_id") != summary.get("task_id"):
        raise ValueError("inactive task state identity mismatch")
    return task


def _hydrate_task_summaries(root, data):
    for task_id, task in list(data.get("tasks", {}).items()):
        if isinstance(task, dict) and task.get("state_ref"):
            data["tasks"][task_id] = _read_task_state(root, task)


def _compact_inactive_tasks(root, data):
    stored = json.loads(json.dumps(data))
    active_task_id = stored.get("active_task_id")
    for task_id, task in list(stored.get("tasks", {}).items()):
        if task_id == active_task_id:
            continue
        relative, digest = _write_task_state(root, task)
        stored["tasks"][task_id] = {
            "task_id": task["task_id"],
            "display_seq": task.get("display_seq"),
            "title": task.get("title", ""),
            "kind": task.get("kind"),
            "level": task.get("level"),
            "phase": task.get("phase"),
            "updated_at": task.get("updated_at"),
            "state_ref": relative,
            "state_sha256": digest,
        }
    return stored


def _archive_dropped_events(root, events):
    if not events:
        return None
    archive = Path(root) / "work-flow" / "docs" / "archive" / f"{datetime.now(timezone.utc).year}.md"
    archive.parent.mkdir(parents=True, exist_ok=True)
    existed = archive.exists()
    original = archive.read_bytes() if existed else b""
    text = original.decode("utf-8") if original else ""
    if "## State events" not in text:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n## State events\n\n"
    for event in events:
        text += f"- `{event.get('at', '')}` `{event.get('name', '')}` {json.dumps(event.get('detail', {}), ensure_ascii=False, sort_keys=True)}\n"
    temp = archive.with_name(f".{archive.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, archive)
    return archive, existed, original


def write_state(root, data, expected_revision=None, operation_id=None):
    operation = get_operation(root, operation_id)
    if not operation or operation.get("role") not in WRITE_ROLES:
        raise PermissionError("operation lock is missing or operation_id does not match")
    guard = state_path(root).with_name(".state-write.guard")
    try:
        fd = os.open(str(guard), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError as exc:
        raise RuntimeError("state mutation is already in progress") from exc
    try:
        return _write_state_unguarded(root, data, expected_revision)
    finally:
        guard.unlink(missing_ok=True)


def _write_state_unguarded(root, data, expected_revision=None):
    path = state_path(root)
    current = read_state(root)
    current_revision = int(current.get("revision", 0))
    if expected_revision is not None and current_revision != expected_revision:
        raise RuntimeError(f"revision conflict: expected {expected_revision}, current {current_revision}")
    data = dict(data)
    data["schema_version"] = SCHEMA_VERSION
    data["workspace_id"] = workspace_identity(root)
    data["revision"] = current_revision + 1
    events = list(data.get("recent_events", []))
    archived = _archive_dropped_events(root, events[:-50]) if len(events) > 50 else None
    data["recent_events"] = events[-50:]
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        stored = _compact_inactive_tasks(root, data)
        temp.write_text(_render_state(stored), encoding="utf-8", newline="\n")
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        if archived:
            archive, existed, original = archived
            if existed:
                archive.write_bytes(original)
            else:
                archive.unlink(missing_ok=True)
        raise
    return data


def _event(data, name, detail=None):
    event = {"at": _now(), "name": name}
    if detail:
        event["detail"] = detail
    data.setdefault("recent_events", []).append(event)


def _next_seq(data):
    values = [int(task.get("display_seq", 0)) for task in data.get("tasks", {}).values()]
    values += [int(task.get("display_seq", 0)) for task in data.get("completed_tasks", {}).values()]
    return max(values, default=-1) + 1


def _next_action(task):
    phase = task.get("phase", "intake")
    level = task.get("level", "L1")
    if phase == "intake":
        if level == "L1" and task.get("kind") in {"code", "text", "plan"}:
            return {"action": "spawn", "role": {"code": "builder", "text": "writer", "plan": "pm"}[task["kind"]], "reason": "L1 hard-route worker"}
        return {"action": "spawn", "role": "pm", "reason": "route intent and scope"}
    if phase == "planned":
        if level in {"L3", "L4"}:
            return {"action": "wait_user", "gate": "plan_confirmation"}
        confirmation = task.get("confirmation_gate") or {}
        if level == "L2" and confirmation.get("required"):
            return {
                "action": "wait_user",
                "gate": "l2_confirmation",
                "reasons": list(confirmation.get("reasons") or []),
            }
        return {"action": "transition", "to": "implementing"}
    if phase == "approved":
        if level == "L4":
            return {"action": "wait_user", "gate": "batch_freeze_and_l4_risk_authorization"}
        if level == "L3":
            return {"action": "wait_user", "gate": "batch_freeze"}
        return {"action": "spawn", "role": "builder", "reason": "implement approved work"}
    if phase == "implementing":
        return {"action": "spawn", "role": "tester", "reason": "validate implementation"}
    if phase == "validating":
        return {"action": "spawn", "role": "code-reviewer", "reason": "review current diff"} if level != "L1" else {"action": "spawn", "role": "reporter", "reason": "record result"}
    if phase == "reviewing":
        return {"action": "spawn", "role": "reporter", "reason": "record evidence and result"}
    if phase == "reporting":
        return {"action": "complete", "reason": "report is recorded"}
    return {"action": "complete", "reason": "task is complete"}


def _validated_result_ref(root, task, value):
    if not value:
        raise ValueError("result_ref_required")
    normalized = Path(str(value).replace("\\", "/")).as_posix()
    path = safe_join(root, normalized)
    expected_prefix = f"{task.get('display_seq')}_"
    expected_suffix = f"_{task.get('level')}"
    if (
        path.name != "result.md"
        or path.parent.parent != Path(root) / "work-flow" / "docs" / "requirements"
        or not path.parent.name.startswith(expected_prefix)
        or not path.parent.name.endswith(expected_suffix)
        or not path.is_file()
    ):
        raise ValueError("result_ref_invalid")
    marker = f"task_id: {task.get('task_id')}"
    if marker not in path.read_text(encoding="utf-8", errors="strict").splitlines():
        raise ValueError("result_task_id_mismatch")
    return path.relative_to(Path(root)).as_posix()


def _validated_evidence_records(root, task, values, kind):
    values = list(dict.fromkeys(values or []))
    if not values:
        raise ValueError(f"{kind}_evidence_required")
    project_root = Path(root)
    allowed_roots = (
        project_root / "work-flow" / "docs" / "evidence",
        project_root / "work-flow" / "docs" / "requirements",
    )
    records = []
    for value in values:
        try:
            path = safe_join(root, value)
        except ValueError as exc:
            raise ValueError(f"{kind}_evidence_ref_invalid") from exc
        if not path.is_file() or not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
            raise ValueError(f"{kind}_evidence_ref_invalid")
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        marker = f"task_id: {task.get('task_id')}"
        if marker not in lines:
            raise ValueError(f"{kind}_evidence_task_id_mismatch")
        if f"{kind}: passed" not in lines:
            raise ValueError(f"{kind}_evidence_not_passed")
        records.append({
            "kind": kind,
            "ref": path.relative_to(project_root).as_posix(),
            "sha256": sha256_file(path),
            "status": "passed",
            "recorded_at": _now(),
        })
    return records


def evidence_records_are_current(root, task):
    for kind in ("validation", "review"):
        for record in task.get(kind, []):
            if not isinstance(record, dict) or not record.get("ref") or not record.get("sha256"):
                return False
            try:
                current = _validated_evidence_records(root, task, [record["ref"]], kind)[0]
            except (OSError, ValueError):
                return False
            if current["sha256"] != record["sha256"]:
                return False
    return True


def _mutating_operation(args):
    if not getattr(args, "operation_id", None):
        return None
    operation = get_operation(args.root, args.operation_id)
    return operation if operation and operation.get("role") in WRITE_ROLES else None


def state_command(args):
    try:
        data = read_state(args.root)
        action = args.action
        operation = _mutating_operation(args) if action in {"add", "transition"} else None
        if action in {"add", "transition"} and not operation:
            return 4, {"error": "operation_lock_required"}
        if action == "read":
            return 0, {"state": data}
        if action == "list":
            return 0, {"revision": data.get("revision", 0), "tasks": list(data.get("tasks", {}).values()), "completed_tasks": list(data.get("completed_tasks", {}).values())}
        if action == "next-action":
            task = data.get("tasks", {}).get(args.task_id or data.get("active_task_id"))
            if not task:
                return 2, {"error": "task_not_found"}
            return 0, {"revision": data.get("revision", 0), "task_id": task["task_id"], "next": _next_action(task)}
        if action == "add":
            if not args.title or args.kind not in KIND_VALUES or args.level not in LEVEL_VALUES or args.expected_revision is None:
                return 2, {"error": "invalid_task_fields"}
            confirmation_reasons = list(dict.fromkeys(getattr(args, "confirmation_reason", None) or []))
            if any(reason not in L2_CONFIRMATION_REASONS for reason in confirmation_reasons):
                return 2, {"error": "invalid_confirmation_reason"}
            requires_confirmation = bool(getattr(args, "requires_confirmation", False) or confirmation_reasons)
            if requires_confirmation and args.level != "L2":
                return 2, {"error": "confirmation_gate_is_l2_only"}
            task_id = args.task_id or operation.get("task_id")
            try:
                uuid.UUID(task_id)
            except ValueError:
                return 2, {"error": "task_id_must_be_uuid"}
            if operation.get("task_id") != task_id:
                return 4, {"error": "operation_identity_mismatch"}
            if task_id in data["tasks"]:
                return 2, {"error": "task_exists"}
            now = _now()
            task = {
                "task_id": task_id, "display_seq": f"{_next_seq(data):04d}", "title": args.title,
                "kind": args.kind, "level": args.level, "phase": "intake", "intent_hash": None,
                "pending_gate": None, "approvals": {}, "batch": None, "route": None, "artifacts": [],
                "validation": [], "review": [], "result_ref": None,
                "residual_risk": [], "created_at": now, "updated_at": now,
                "confirmation_gate": {"required": requires_confirmation, "reasons": confirmation_reasons},
            }
            data["tasks"][task_id] = task
            data["active_task_id"] = task_id
            _event(data, "task.add", {"task_id": task_id, "kind": args.kind, "level": args.level})
            return 0, {"state": write_state(args.root, data, args.expected_revision, args.operation_id), "task": task}
        if action == "transition":
            if not args.task_id or args.to not in PHASES or args.expected_revision is None:
                return 2, {"error": "invalid_transition_fields"}
            task = data["tasks"].get(args.task_id)
            if not task:
                return 2, {"error": "task_not_found"}
            if operation.get("task_id") != args.task_id:
                return 4, {"error": "operation_identity_mismatch"}
            data["active_task_id"] = args.task_id
            if (
                args.to not in TRANSITIONS.get(task.get("phase"), set())
                or (task.get("phase") == "intake" and args.to == "implementing" and task.get("level") != "L1")
                or (task.get("phase") == "planned" and args.to == "implementing" and task.get("level") in {"L3", "L4"})
            ):
                return 2, {"error": "invalid_phase_transition", "from": task.get("phase"), "to": args.to}
            phase = task.get("phase")
            level = task.get("level")
            if phase == "validating" and args.to == "reviewing" and level == "L1":
                return 2, {"error": "invalid_phase_transition", "from": phase, "to": args.to}
            if phase == "validating" and args.to == "reporting" and level != "L1":
                return 2, {"error": "invalid_phase_transition", "from": phase, "to": args.to}
            if (
                level == "L2"
                and phase == "planned"
                and args.to == "implementing"
                and (task.get("confirmation_gate") or {}).get("required")
            ):
                return 2, {
                    "error": "confirmation_required",
                    "gate": "l2_confirmation",
                    "reasons": list((task.get("confirmation_gate") or {}).get("reasons") or []),
                }
            if phase == "implementing" and args.to == "validating":
                try:
                    records = _validated_evidence_records(
                        args.root, task, getattr(args, "validation_evidence", None), "validation"
                    )
                except ValueError as exc:
                    return 2, {"error": str(exc)}
                task.setdefault("validation", []).extend(records)
            if phase == "reviewing" and args.to == "reporting":
                review_evidence = getattr(args, "review_evidence", None)
                if review_evidence or level in {"L2", "L3", "L4"}:
                    try:
                        records = _validated_evidence_records(args.root, task, review_evidence, "review")
                    except ValueError as exc:
                        return 2, {"error": str(exc)}
                    task.setdefault("review", []).extend(records)
            if phase == "reporting" and args.to == "complete":
                if not task.get("validation"):
                    return 2, {"error": "validation_evidence_required"}
                if level in {"L2", "L3", "L4"} and not task.get("review"):
                    return 2, {"error": "review_evidence_required"}
                if not evidence_records_are_current(args.root, task):
                    return 2, {"error": "evidence_changed_since_recorded"}
                try:
                    result_ref = _validated_result_ref(args.root, task, getattr(args, "result_ref", None))
                except ValueError as exc:
                    return 2, {"error": str(exc)}
                task["result_ref"] = result_ref
                task["result_sha256"] = sha256_file(Path(args.root) / result_ref)
                if result_ref not in task.setdefault("artifacts", []):
                    task["artifacts"].append(result_ref)
            if level in {"L3", "L4"} and phase == "intake" and args.to == "planned":
                if not getattr(args, "intent_hash", None):
                    return 2, {"error": "gate_required", "gate": "intent_and_scope_confirmation"}
                task["intent_hash"] = args.intent_hash
                task.setdefault("approvals", {})["intent_and_scope"] = args.intent_hash
            if level in {"L3", "L4"} and phase == "planned" and args.to == "approved":
                if not getattr(args, "technical_plan_hash", None):
                    return 2, {"error": "gate_required", "gate": "technical_plan_confirmation"}
                if not getattr(args, "authorization_id", None):
                    return 2, {"error": "gate_required", "gate": "implementation_authorization"}
                task.setdefault("approvals", {})["technical_plan"] = args.technical_plan_hash
                task["approvals"]["implementation_authorization"] = args.authorization_id
            if level in {"L3", "L4"} and phase == "approved" and args.to == "implementing":
                batch_ids = list(dict.fromkeys(getattr(args, "batch_task_id", None) or []))
                if not 3 <= len(batch_ids) <= 5 or args.task_id not in batch_ids:
                    return 2, {"error": "gate_required", "gate": "batch_freeze", "required_batch_size": "3-5", "must_include": args.task_id}
                try:
                    for batch_task_id in batch_ids:
                        uuid.UUID(batch_task_id)
                except ValueError:
                    return 2, {"error": "invalid_batch_task_id"}
                missing_batch_tasks = [batch_task_id for batch_task_id in batch_ids if batch_task_id not in data.get("tasks", {})]
                if missing_batch_tasks:
                    return 2, {"error": "batch_task_not_found", "task_ids": missing_batch_tasks}
                if level == "L4":
                    for field, gate in (
                        ("risk_confirmation", "human_risk_confirmation"),
                        ("target_system", "target_system"),
                        ("target_environment", "target_environment"),
                        ("target_object", "target_object"),
                        ("backup_ref", "backup_or_snapshot"),
                        ("rollback_ref", "rollback_plan"),
                        ("monitoring_ref", "monitoring_and_stop_conditions"),
                        ("stop_condition", "stop_conditions"),
                        ("external_write_scope", "external_write_scope"),
                        ("post_action_validation_ref", "post_action_validation"),
                        ("audit_result_ref", "audit_result_location"),
                    ):
                        if not getattr(args, field, None):
                            return 2, {"error": "gate_required", "gate": gate}
                    task.setdefault("approvals", {})["l4"] = {
                        field: getattr(args, field)
                        for field in (
                            "risk_confirmation", "target_system", "target_environment", "target_object",
                            "backup_ref", "rollback_ref", "monitoring_ref", "stop_condition",
                            "external_write_scope", "post_action_validation_ref", "audit_result_ref",
                        )
                    }
                task["batch"] = {"task_ids": batch_ids, "frozen_at": _now()}
            task["phase"] = args.to
            task["pending_gate"] = None
            task["updated_at"] = _now()
            _event(data, "task.transition", {"task_id": args.task_id, "to": args.to})
            return 0, {"state": write_state(args.root, data, args.expected_revision, args.operation_id), "task": task}
        return 2, {"error": "unsupported_state_action"}
    except PermissionError as exc:
        return 4, {"error": "operation_lock_required", "message": str(exc)}
    except RuntimeError as exc:
        return 4, {"error": "revision_conflict", "message": str(exc)}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return 2, {"error": "state_invalid", "message": str(exc)}
