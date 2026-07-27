import json
import os
import socket
import hashlib
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .schema import workspace_identity


READ_ROLES = {"pm", "plan-reviewer", "explorer", "code-reviewer", "risk-reviewer"}
WRITE_ROLES = {"builder", "writer", "reporter", "tester"}


class GuardMutexBusy(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _next_heartbeat(previous):
    current = _parse_time(_now())
    prior = _parse_time(previous)
    if current <= prior:
        current = prior.replace(microsecond=0) + timedelta(seconds=1)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value):
    """Parse an RFC3339-ish UTC timestamp used by a lock heartbeat."""
    if not isinstance(value, str) or not value:
        raise ValueError("heartbeat_at must be an ISO-8601 timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _heartbeat_age_seconds(lock):
    return max(0.0, (datetime.now(timezone.utc) - _parse_time(lock.get("heartbeat_at"))).total_seconds())


def _validate_lock_record(root, lock):
    """Validate immutable lock identity before acting on it.

    A lock file can outlive the process that created it.  Never operate on a
    record belonging to another workspace, malformed operation, or unknown
    role merely because its operation id happens to match.
    """
    if not isinstance(lock, dict):
        return "lock_record_invalid"
    if lock.get("schema_version") != 1:
        return "lock_record_schema_invalid"
    for field in ("operation_id", "task_id", "role", "owner_session", "workspace_id", "acquired_at", "heartbeat_at"):
        if not isinstance(lock.get(field), str) or not lock[field]:
            return f"lock_field_missing:{field}"
    try:
        uuid.UUID(lock["operation_id"])
        uuid.UUID(lock["task_id"])
    except (ValueError, AttributeError):
        return "lock_uuid_invalid"
    if lock["role"] not in READ_ROLES | WRITE_ROLES:
        return "lock_role_invalid"
    if lock["workspace_id"] != workspace_identity(root):
        return "workspace_identity_mismatch"
    try:
        _parse_time(lock["acquired_at"])
        _parse_time(lock["heartbeat_at"])
    except ValueError:
        return "lock_timestamp_invalid"
    return None


def _validate_lock_document(root, document):
    if not isinstance(document, dict):
        return "lock_document_invalid"
    if document.get("schema_version") != 1:
        return "lock_schema_version_invalid"
    if not isinstance(document.get("revision", 0), int) or document.get("revision", 0) < 0:
        return "lock_revision_invalid"
    locks = document.get("locks", [])
    if not isinstance(locks, list) or len(locks) > 3:
        return "lock_collection_invalid"
    for lock in locks:
        error = _validate_lock_record(root, lock)
        if error:
            return error
    operation_ids = [lock["operation_id"] for lock in locks]
    if len(operation_ids) != len(set(operation_ids)):
        return "duplicate_operation_id"
    writers = [lock for lock in locks if lock["role"] in WRITE_ROLES]
    if len(writers) > 1 or (writers and len(locks) > 1):
        return "writer_lock_exclusivity_invalid"
    return None


def _check_request_identity(root, args, lock, *, require_task_role=False, check_owner=True):
    """Check caller-supplied identity fields against the selected lock.

    ``task_id`` and ``role`` remain optional for heartbeat and release, but a
    parent owner identity is mandatory.  It may be supplied by ``--owner`` or
    ``WORKFLOW_OWNER_ID`` and must match the acquired lock.
    """
    error = _validate_lock_record(root, lock)
    if error:
        return error
    if require_task_role and (not args.task_id or not args.role):
        return "task_and_role_required"
    if args.task_id and args.task_id != lock.get("task_id"):
        return "task_id_mismatch"
    if args.role and args.role != lock.get("role"):
        return "role_mismatch"
    requested_workspace = getattr(args, "workspace_id", None)
    if requested_workspace and requested_workspace != lock.get("workspace_id"):
        return "workspace_identity_mismatch"
    # A supplied owner identifies the lock owner for heartbeat/release.  For
    # recovery it identifies the operator and is intentionally checked by the
    # caller separately, because recovering a dead process commonly requires a
    # different operator identity.
    if check_owner:
        requested_owner = args.owner or os.environ.get("WORKFLOW_OWNER_ID")
        if not requested_owner:
            return "owner_required"
        if requested_owner != lock.get("owner_session"):
            return "owner_mismatch"
    return None


def lock_path(root):
    return Path(root) / "work-flow" / ".runtime" / "operation-lock.json"


def guard_path(root):
    return lock_path(root).with_name(".operation-lock.guard")


def guard_mutex_path(root):
    return lock_path(root).with_name(".operation-lock.mutex")


@contextmanager
def _guard_mutex(root):
    path = guard_mutex_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise GuardMutexBusy("operation guard mutex is busy") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _owner(args):
    return args.owner or os.environ.get("WORKFLOW_OWNER_ID") or f"{socket.gethostname()}:{os.getpid()}"


def _read(path):
    if not path.exists():
        return {"schema_version": 1, "revision": 0, "locks": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if "locks" not in value:
        value = {"schema_version": 1, "revision": 0, "locks": [value]}
    return value


def _atomic_write(path, value):
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _audit(root, event):
    path = Path(root) / "work-flow" / ".runtime" / "transactions" / "lock-recovery.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _guard_descriptor(raw, path):
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        value = None
    if isinstance(value, dict) and isinstance(value.get("guard_id"), str):
        try:
            uuid.UUID(value["guard_id"])
            _parse_time(value.get("acquired_at"))
        except (ValueError, AttributeError):
            value = None
    if value is not None:
        return value
    acquired = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return {
        "schema_version": 0,
        "guard_id": "legacy-" + hashlib.sha256(raw).hexdigest()[:16],
        "owner_session": "unknown",
        "operation_id": None,
        "acquired_at": acquired.isoformat().replace("+00:00", "Z"),
    }


def _read_guard(path):
    raw = path.read_bytes()
    return raw, _guard_descriptor(raw, path)


def _recover_guard(args):
    path = guard_path(args.root)
    if not path.is_file():
        return 4, {"error": "guard_missing"}
    if not args.reason:
        return 2, {"error": "recovery_reason_required"}
    operator = args.owner or os.environ.get("WORKFLOW_OWNER_ID")
    if not operator:
        return 2, {"error": "recovery_owner_required"}
    if not getattr(args, "guard_id", None):
        try:
            _, observed = _read_guard(path)
        except OSError as exc:
            return 2, {"error": "guard_read_failed", "message": str(exc)}
        return 2, {"error": "guard_id_required", "observed_guard_id": observed["guard_id"]}
    try:
        raw, observed = _read_guard(path)
    except OSError as exc:
        return 2, {"error": "guard_read_failed", "message": str(exc)}
    if observed["guard_id"] != args.guard_id:
        return 4, {
            "error": "guard_identity_mismatch",
            "expected_guard_id": args.guard_id,
            "observed_guard_id": observed["guard_id"],
        }
    try:
        stale_after = float(getattr(args, "stale_after_seconds", 300.0))
    except (TypeError, ValueError):
        return 2, {"error": "invalid_stale_after_seconds"}
    if stale_after <= 0:
        return 2, {"error": "invalid_stale_after_seconds"}
    age_seconds = max(0.0, (datetime.now(timezone.utc) - _parse_time(observed["acquired_at"])).total_seconds())
    force_stale = bool(getattr(args, "force_stale", False))
    if not force_stale and age_seconds < stale_after:
        return 4, {
            "error": "guard_not_stale",
            "guard_id": observed["guard_id"],
            "age_seconds": round(age_seconds, 3),
            "stale_after_seconds": stale_after,
        }
    quarantine = path.with_name(f".operation-lock.guard.recovered-{observed['guard_id']}")
    try:
        if path.read_bytes() != raw:
            return 4, {"error": "guard_changed_during_recovery"}
        os.replace(path, quarantine)
    except FileNotFoundError:
        return 4, {"error": "guard_changed_during_recovery"}
    audit_payload = {
        "event": "lock.guard_recover",
        "status": "committed",
        "at": _now(),
        "operator": operator,
        "reason": args.reason,
        "guard": observed,
        "guard_age_seconds": round(age_seconds, 3),
        "forced": force_stale,
    }
    try:
        _audit(args.root, audit_payload)
    except OSError as exc:
        return 6, {
            "error": "guard_recovery_audit_incomplete",
            "status": "guard_recovered",
            "recovery_artifact": str(quarantine),
            "message": str(exc),
        }
    quarantine.unlink(missing_ok=True)
    return 0, {
        "status": "guard_recovered",
        "guard": observed,
        "reason": args.reason,
        "forced": force_stale,
        "guard_age_seconds": round(age_seconds, 3),
    }


def _release_owned_guard(path, guard_id):
    try:
        _, current = _read_guard(path)
    except FileNotFoundError:
        return
    except OSError:
        return
    if current.get("guard_id") == guard_id:
        path.unlink(missing_ok=True)


def _write_lock(root, data, expected_revision):
    current = _read(lock_path(root))
    if current.get("revision", 0) != expected_revision:
        raise RuntimeError("lock revision conflict")
    data = dict(data)
    data["revision"] = expected_revision + 1
    _atomic_write(lock_path(root), data)
    return data


def lock_command(args):
    """Serialize normal mutations and guard recovery with an OS mutex."""
    try:
        with _guard_mutex(args.root):
            return _lock_command_with_mutex(args)
    except GuardMutexBusy:
        return 4, {"error": "lock_mutation_busy"}


def _lock_command_with_mutex(args):
    """Mutate the lock while the process-scoped recovery mutex is held."""
    if args.action == "recover-guard":
        return _recover_guard(args)
    guard = guard_path(args.root)
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard_id = str(uuid.uuid4())
    guard_record = {
        "schema_version": 1,
        "guard_id": guard_id,
        "owner_session": _owner(args),
        "operation_id": getattr(args, "operation_id", None),
        "acquired_at": _now(),
    }
    try:
        fd = os.open(str(guard), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        payload = (json.dumps(guard_record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        os.write(fd, payload)
        os.fsync(fd)
        os.close(fd)
    except FileExistsError:
        try:
            _, current = _read_guard(guard)
        except OSError:
            current = None
        return 4, {"error": "lock_mutation_busy", "guard": current}
    try:
        return _lock_command_unguarded(args)
    finally:
        _release_owned_guard(guard, guard_id)


def _lock_command_unguarded(args):
    path = lock_path(args.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = _read(path)
        locks = list(current.get("locks", []))
        # Validate every existing record before applying concurrency or
        # mutation logic.  This prevents a lock copied from another checkout
        # (or a partially written lock) from being treated as authoritative.
        document_error = _validate_lock_document(args.root, current)
        if document_error:
            return 4, {"error": document_error}
        if args.action == "acquire":
            if not args.task_id or not args.role:
                return 2, {"error": "task_and_role_required"}
            if args.role not in READ_ROLES | WRITE_ROLES:
                return 2, {"error": "unsupported_role"}
            try:
                uuid.UUID(args.task_id)
            except (ValueError, AttributeError):
                return 2, {"error": "task_id_must_be_uuid"}
            requested_workspace = getattr(args, "workspace_id", None)
            actual_workspace = workspace_identity(args.root)
            if requested_workspace and requested_workspace != actual_workspace:
                return 2, {"error": "workspace_identity_mismatch"}
            is_writer = args.role in WRITE_ROLES
            if is_writer and locks:
                return 4, {"error": "write_lock_busy", "locks": locks}
            if not is_writer and any(item.get("role") in WRITE_ROLES for item in locks):
                return 4, {"error": "read_blocked_by_writer", "locks": locks}
            if not is_writer and len(locks) >= 3:
                return 4, {"error": "read_lock_limit", "locks": locks}
            operation_id = args.operation_id or str(uuid.uuid4())
            try:
                uuid.UUID(operation_id)
            except ValueError:
                return 2, {"error": "operation_id_must_be_uuid"}
            if any(item.get("operation_id") == operation_id for item in locks):
                return 4, {"error": "operation_exists"}
            workspace_id = actual_workspace
            lock = {
                "schema_version": 1,
                "operation_id": operation_id,
                "task_id": args.task_id,
                "role": args.role,
                "owner_session": _owner(args),
                "workspace_id": workspace_id,
                "acquired_at": _now(),
                "heartbeat_at": _now(),
            }
            data = {"schema_version": 1, "revision": current.get("revision", 0), "locks": locks + [lock]}
            if not locks and not path.exists():
                try:
                    with path.open("x", encoding="utf-8", newline="\n") as handle:
                        data["revision"] = 1
                        json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
                        handle.write("\n")
                    return 0, {"status": "acquired", "lock": lock, "revision": 1}
                except FileExistsError:
                    current = _read(path)
                    locks = list(current.get("locks", []))
                    return 4, {"error": "lock_race", "locks": locks}
            written = _write_lock(args.root, data, current.get("revision", 0))
            return 0, {"status": "acquired", "lock": lock, "revision": written["revision"]}

        if not locks:
            return 4, {"error": "lock_missing"}
        if args.action in {"heartbeat", "release"} and not (args.owner or os.environ.get("WORKFLOW_OWNER_ID")):
            return 2, {"error": "owner_required"}
        index = next((i for i, item in enumerate(locks) if item.get("operation_id") == args.operation_id), None)
        if args.action in {"heartbeat", "release"} and index is None:
            return 4, {"error": "operation_mismatch"}
        if args.action in {"heartbeat", "release"} and index is not None:
            identity_error = _check_request_identity(args.root, args, locks[index])
            if identity_error:
                return 4, {"error": identity_error}
        if args.action == "heartbeat":
            locks[index] = dict(locks[index], heartbeat_at=_next_heartbeat(locks[index]["heartbeat_at"]))
            data = _write_lock(args.root, {"schema_version": 1, "revision": current.get("revision", 0), "locks": locks}, current.get("revision", 0))
            return 0, {"status": "heartbeat", "lock": locks[index], "revision": data["revision"]}
        if args.action == "release":
            locks.pop(index)
            # Keep an empty lock document and advance its revision instead of
            # unlinking it.  This preserves the CAS history and avoids a
            # check-then-delete race with a concurrent acquire.
            data = _write_lock(args.root, {"schema_version": 1, "revision": current.get("revision", 0), "locks": locks}, current.get("revision", 0))
            return 0, {"status": "released", "operation_id": args.operation_id, "revision": data["revision"]}
        if args.action == "recover":
            if not args.reason:
                return 2, {"error": "recovery_reason_required"}
            if not args.operation_id or index is None:
                return 4, {"error": "operation_mismatch"}
            identity_error = _check_request_identity(args.root, args, locks[index], require_task_role=True, check_owner=False)
            if identity_error:
                return 4, {"error": identity_error}
            operator = args.owner or os.environ.get("WORKFLOW_OWNER_ID")
            if not operator:
                return 2, {"error": "recovery_owner_required"}
            force_stale = bool(getattr(args, "force_stale", False))
            stale_after = getattr(args, "stale_after_seconds", 300.0)
            try:
                stale_after = float(stale_after)
            except (TypeError, ValueError):
                return 2, {"error": "invalid_stale_after_seconds"}
            if stale_after <= 0:
                return 2, {"error": "invalid_stale_after_seconds"}
            old = locks[index]
            try:
                age_seconds = _heartbeat_age_seconds(old)
            except ValueError as exc:
                return 2, {"error": "invalid_heartbeat", "message": str(exc)}
            if not force_stale and age_seconds < stale_after:
                return 4, {
                    "error": "lock_not_stale",
                    "age_seconds": round(age_seconds, 3),
                    "stale_after_seconds": stale_after,
                    "operation_id": args.operation_id,
                }
            old_revision = current.get("revision", 0)
            locks = [item for item in locks if item is not old]
            written = _write_lock(args.root, {"schema_version": 1, "revision": current.get("revision", 0), "locks": locks}, current.get("revision", 0))
            audit_payload = {"event": "lock.recover", "status": "committed", "at": _now(), "operator": operator, "reason": args.reason, "old_operation_id": old.get("operation_id"), "old_revision": old_revision, "new_revision": written["revision"], "heartbeat_age_seconds": round(age_seconds, 3), "forced": force_stale}
            try:
                _audit(args.root, audit_payload)
            except OSError as audit_exc:
                return 6, {
                    "error": "lock_recovery_audit_incomplete",
                    "status": "recovered",
                    "old_operation_id": old.get("operation_id"),
                    "revision": written["revision"],
                    "message": str(audit_exc),
                }
            return 0, {"status": "recovered", "old_lock": old, "reason": args.reason, "revision": written["revision"], "forced": force_stale, "heartbeat_age_seconds": round(age_seconds, 3)}
        return 2, {"error": "unsupported_lock_action"}
    except RuntimeError as exc:
        return 4, {"error": "lock_revision_conflict", "message": str(exc)}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return 2, {"error": "lock_error", "message": str(exc)}


def get_operation(root, operation_id, *, task_id=None, role=None, owner=None, workspace_id=None):
    """Return a lock only when its workspace and optional identity match.

    State and worker code use this helper as their authorization check.  Do not
    let a copied lock file from another checkout authorize a write just because
    the operation UUID is the same.
    """
    if not operation_id:
        return None
    try:
        document = _read(lock_path(root))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if _validate_lock_document(root, document):
        return None
    locks = document.get("locks", [])
    for item in locks:
        if item.get("operation_id") != operation_id:
            continue
        if _validate_lock_record(root, item):
            return None
        if task_id and item.get("task_id") != task_id:
            return None
        if role and item.get("role") != role:
            return None
        if owner and item.get("owner_session") != owner:
            return None
        if workspace_id and item.get("workspace_id") != workspace_id:
            return None
        return item
    return None


def current_operation(root, operation_id, **identity):
    return get_operation(root, operation_id, **identity) is not None
