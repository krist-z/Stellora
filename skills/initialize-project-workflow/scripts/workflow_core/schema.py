import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath

from .constants import SCHEMA_VERSION


def normalize_root(root):
    path = Path(root).expanduser()
    if not path.exists():
        raise ValueError(f"root does not exist: {root}")
    if not path.is_dir():
        raise ValueError(f"root is not a directory: {root}")
    return path.resolve()


def posix_rel(path, root):
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def stable_json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pretty_json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def workspace_identity(root, is_git=None, git_root=None):
    """Return an opaque workspace identity stable for a checkout/worktree."""
    root = Path(root).resolve()
    if is_git is None:
        import subprocess
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        is_git = result.returncode == 0 and bool(result.stdout.strip())
        git_root = Path(result.stdout.strip()).resolve() if is_git else None
    if is_git and git_root:
        identity = f"git:{Path(git_root).resolve()}|worktree:{root}"
    else:
        identity = f"path:{root}"
    return "ws-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def plan_hash(public_plan):
    payload = dict(public_plan)
    payload.pop("plan_hash", None)
    return sha256_bytes(stable_json(payload).encode("utf-8"))


def add_plan_hash(public_plan):
    payload = dict(public_plan)
    payload["plan_hash"] = plan_hash(payload)
    return payload


def safe_join(root, relative):
    rel = PurePosixPath(str(relative).replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or str(rel) in {"", "."}:
        raise ValueError(f"path escapes root: {relative}")
    candidate = Path(root).joinpath(*rel.parts)
    resolved_root = Path(root).resolve()
    current = resolved_root
    for part in rel.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            metadata = current.lstat()
            attributes = getattr(metadata, "st_file_attributes", 0)
            if current.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError(f"path traverses symlink or reparse point: {relative}")
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"path escapes root: {relative}") from exc
    return candidate


def read_text_preserve(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def write_mode_for(path):
    suffix = Path(path).suffix.lower()
    if suffix in {".sh"}:
        return 0o755
    return None


def rel_sort_key(value):
    return str(value).replace(os.sep, "/").lower()


def issue(code, message, path=None):
    payload = {"schema_version": SCHEMA_VERSION, "code": code, "message": message}
    if path is not None:
        payload["path"] = str(path).replace("\\", "/")
    return payload
