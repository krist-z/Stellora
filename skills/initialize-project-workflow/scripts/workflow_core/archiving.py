from datetime import datetime, timezone
from pathlib import Path

from .locking import current_operation
from .schema import sha256_file
from .state import _validated_result_ref, evidence_records_are_current, read_state, write_state

def archive_command(args):
    try:
        if not current_operation(args.root, args.operation_id, task_id=args.task_id):
            return 4, {"error": "operation_lock_required"}
        data = read_state(args.root)
        task = data.get("tasks", {}).get(args.task_id)
        if not task:
            if args.task_id in data.get("completed_tasks", {}):
                return 0, {"status": "already_archived", "task_id": args.task_id}
            return 2, {"error": "task_not_found"}
        if task.get("phase") != "complete":
            return 2, {"error": "task_not_complete"}
        if not task.get("validation"):
            return 2, {"error": "validation_evidence_required"}
        if task.get("level") in {"L2", "L3", "L4"} and not task.get("review"):
            return 2, {"error": "review_evidence_required"}
        if not evidence_records_are_current(args.root, task):
            return 2, {"error": "evidence_changed_or_missing"}
        docs_root = Path(args.root) / "work-flow" / "docs"
        result_ref = _validated_result_ref(args.root, task, task.get("result_ref"))
        result_file = Path(args.root) / result_ref
        if sha256_file(result_file) != task.get("result_sha256"):
            return 2, {"error": "result_changed_or_missing"}
        task_dir = result_file.parent
        archive_dir = docs_root / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_file = archive_dir / f"{datetime.now(timezone.utc).year}.md"
        marker = f"`{task['task_id']}`"
        existing = archive_file.read_text(encoding="utf-8") if archive_file.exists() else ""
        archive_changed = False
        if marker not in existing:
            with archive_file.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"- {marker} {task.get('title', '')} ({task.get('level', '')}) -> `{result_file.relative_to(Path(args.root)).as_posix()}`\n")
            archive_changed = True
        data.setdefault("completed_tasks", {})[args.task_id] = {
            "task_id": task["task_id"], "display_seq": task["display_seq"], "title": task.get("title", ""),
            "level": task.get("level"), "result": result_file.relative_to(Path(args.root)).as_posix(),
            "result_sha256": task.get("result_sha256"),
            "validation": list(task.get("validation", [])),
            "review": list(task.get("review", [])),
            "final_status": "complete",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        del data["tasks"][args.task_id]
        if data.get("active_task_id") == args.task_id:
            data["active_task_id"] = None
        try:
            written = write_state(args.root, data, args.expected_revision, args.operation_id)
        except Exception:
            # State CAS is the final commit point. If it rejects a stale
            # revision or loses its write lock, remove only artifacts created
            # by this invocation so state cannot point at an orphan result.
            if archive_changed:
                if existing:
                    archive_file.write_text(existing, encoding="utf-8", newline="\n")
                elif archive_file.exists():
                    archive_file.unlink()
            raise
        return 0, {"status": "archived", "task_id": args.task_id, "state": written, "result": str(result_file)}
    except PermissionError as exc:
        return 4, {"error": "operation_lock_required", "message": str(exc)}
    except RuntimeError as exc:
        return 4, {"error": "revision_conflict", "message": str(exc)}
    except (OSError, ValueError) as exc:
        return 2, {"error": "archive_error", "message": str(exc)}
