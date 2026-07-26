import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .schema import safe_join, sha256_file, write_mode_for


class TransactionError(RuntimeError):
    def __init__(self, message, exit_code=5, details=None):
        super().__init__(message)
        self.exit_code = exit_code
        self.details = dict(details or {})


@dataclass(frozen=True)
class FileChange:
    relative_path: str
    content: bytes | None
    expected_sha256: str | None
    mode: int | None = None


def _copy_existing(target, backup):
    if target.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        return True
    return False


def _restore(root, backups):
    if os.environ.get("WORKFLOW_CORE_FAIL_ROLLBACK") == "1":
        raise OSError("injected rollback failure")
    for target, backup, existed in reversed(backups):
        if existed:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        else:
            if target.exists():
                target.unlink()
    # Never remove project directories during rollback. The transaction only
    # restores file contents; empty user directories are not workflow-owned.


def _remove_empty_dirs(start):
    start = Path(start)
    if not start.exists():
        return
    for path in sorted([p for p in start.rglob("*") if p.is_dir()], key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass
    try:
        start.rmdir()
    except OSError:
        pass


def _write_transaction_record(runtime_dir, transaction_id, status, changes, detail=None, recovery_path=None):
    record_dir = Path(runtime_dir) / "transactions"
    record_dir.mkdir(parents=True, exist_ok=True)
    path = record_dir / f"transaction-{transaction_id}.json"
    payload = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "status": status,
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "paths": [change.relative_path for change in changes],
    }
    if detail:
        payload["detail"] = str(detail)
    if recovery_path:
        payload["recovery_path"] = str(recovery_path)
    temp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)
    return path


def _write_recovery_manifest(tx_dir, root, transaction_id, backups, error, rollback_error):
    files = []
    for target, backup, existed in backups:
        relative = target.relative_to(root).as_posix()
        files.append({
            "path": relative,
            "originally_existed": bool(existed),
            "backup_path": f"backup/{relative}" if backup.is_file() else None,
            "backup_sha256": sha256_file(backup) if backup.is_file() else None,
        })
    payload = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "status": "rollback_incomplete",
        "failure": str(error),
        "rollback_failure": str(rollback_error),
        "files": files,
    }
    path = Path(tx_dir) / "recovery-manifest.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def apply_file_changes(root, changes, fail_after=None, post_validate=None):
    root = Path(root).resolve()
    recovery_root = root / "work-flow" / ".runtime" / "transactions"
    for manifest_path in recovery_root.glob("recovery-*/recovery-manifest.json") if recovery_root.is_dir() else ():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TransactionError(
                f"manual recovery required: unreadable recovery bundle: {manifest_path}",
                exit_code=6,
            ) from exc
        if manifest.get("status") == "rollback_incomplete":
            raise TransactionError(
                f"manual recovery required: unresolved rollback bundle: {manifest_path}",
                exit_code=6,
                details={"recovery_path": manifest_path.parent.relative_to(root).as_posix()},
            )
    if not changes:
        if post_validate is not None:
            validation = post_validate()
            if not validation or not validation.get("valid", False):
                raise TransactionError("post-apply strict validation failed", exit_code=2)
        return {"changed": 0}

    runtime_dir = root / "work-flow" / ".runtime"
    transaction_id = str(uuid.uuid4())
    guard = runtime_dir / ".transaction.guard"
    guard_owned = False
    tx_dir = None
    try:
        if runtime_dir.is_symlink():
            raise TransactionError("runtime directory is a symlink", exit_code=5)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        try:
            guard_fd = os.open(str(guard), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            guard_owned = True
            os.close(guard_fd)
        except FileExistsError as exc:
            raise TransactionError("another workflow transaction is active", exit_code=4) from exc
        tx_dir = Path(tempfile.mkdtemp(prefix=".transaction-", dir=str(runtime_dir)))
    except TransactionError:
        if guard_owned:
            guard.unlink(missing_ok=True)
        raise
    except OSError as exc:
        if guard_owned:
            guard.unlink(missing_ok=True)
        raise TransactionError(str(exc), exit_code=5) from exc
    staged_dir = tx_dir / "staged"
    backup_dir = tx_dir / "backup"
    backups = []
    changed = 0
    record = None

    try:
        for change in changes:
            target = safe_join(root, change.relative_path)
            current_hash = sha256_file(target) if target.is_file() else None
            if current_hash != change.expected_sha256:
                raise TransactionError(f"target changed after dry-run: {change.relative_path}", exit_code=4)
        for index, change in enumerate(changes):
            if change.content is None:
                continue
            staged = safe_join(staged_dir, change.relative_path)
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(change.content)
            mode = change.mode if change.mode is not None else write_mode_for(change.relative_path)
            if mode is not None:
                try:
                    os.chmod(staged, mode)
                except OSError:
                    pass

        for index, change in enumerate(changes, start=1):
            target = safe_join(root, change.relative_path)
            staged = safe_join(staged_dir, change.relative_path)
            backup = safe_join(backup_dir, change.relative_path)
            current_hash = sha256_file(target) if target.is_file() else None
            if current_hash != change.expected_sha256:
                raise TransactionError(f"target changed before write: {change.relative_path}", exit_code=4)
            existed = _copy_existing(target, backup)
            backups.append((target, backup, existed))
            if change.content is None:
                if target.exists() or target.is_symlink():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, target)
            changed += 1
            if fail_after is not None and changed >= fail_after:
                raise TransactionError(f"injected failure after {changed} actions")
        if post_validate is not None:
            validation = post_validate()
            if not validation or not validation.get("valid", False):
                raise TransactionError("post-apply strict validation failed")
        record = _write_transaction_record(runtime_dir, transaction_id, "committed", changes)
    except Exception as exc:
        try:
            _restore(root, backups)
        except Exception as restore_exc:
            recovery_parent = runtime_dir / "transactions"
            recovery_parent.mkdir(parents=True, exist_ok=True)
            recovery_dir = recovery_parent / f"recovery-{transaction_id}"
            recovery_relative = recovery_dir.relative_to(root).as_posix()
            try:
                _write_recovery_manifest(tx_dir, root, transaction_id, backups, exc, restore_exc)
                os.replace(tx_dir, recovery_dir)
                tx_dir = None
            except OSError as preserve_exc:
                recovery_dir = tx_dir
                recovery_relative = recovery_dir.relative_to(root).as_posix()
                restore_exc = OSError(f"{restore_exc}; preserving recovery directory failed: {preserve_exc}")
            record = None
            try:
                record = _write_transaction_record(
                    runtime_dir,
                    transaction_id,
                    "rollback_incomplete",
                    changes,
                    f"{exc}; rollback failed: {restore_exc}",
                    recovery_relative,
                )
            except OSError:
                pass
            details = {"recovery_path": recovery_relative}
            if record is not None:
                details["transaction_record"] = record.relative_to(root).as_posix()
            raise TransactionError(
                f"{exc}; rollback failed: {restore_exc}",
                exit_code=6,
                details=details,
            ) from exc
        try:
            _write_transaction_record(runtime_dir, transaction_id, "rolled_back", changes, exc)
        except OSError:
            pass
        exit_code = exc.exit_code if isinstance(exc, TransactionError) else 5
        raise TransactionError(str(exc), exit_code=exit_code) from exc
    finally:
        if tx_dir is not None:
            shutil.rmtree(tx_dir, ignore_errors=True)
        if guard_owned:
            guard.unlink(missing_ok=True)

    return {
        "changed": changed,
        "transaction_id": transaction_id,
        "transaction_record": record.relative_to(root).as_posix(),
    }
