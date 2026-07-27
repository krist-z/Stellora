import json
from pathlib import Path, PurePosixPath

from .constants import RUNTIME_VERSION, TEMPLATE_VERSION
from .schema import pretty_json, sha256_bytes, sha256_file


RUNTIME_PREFIX = "work-flow/scripts/_runtime/"
RUNTIME_MANIFEST_NAME = "runtime-manifest.json"
RUNTIME_MANIFEST_RELATIVE = RUNTIME_PREFIX + RUNTIME_MANIFEST_NAME


def _included_runtime_relative(relative):
    path = PurePosixPath(relative)
    return (
        relative != RUNTIME_MANIFEST_NAME
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )


def manifest_for_targets(targets):
    files = {}
    for target, content in sorted(targets.items(), key=lambda item: item[0].lower()):
        if not target.startswith(RUNTIME_PREFIX):
            continue
        relative = target[len(RUNTIME_PREFIX):]
        if _included_runtime_relative(relative):
            files[relative] = sha256_bytes(content)
    return {
        "schema_version": 1,
        "runtime_version": RUNTIME_VERSION,
        "template_version": TEMPLATE_VERSION,
        "files": files,
    }


def render_runtime_manifest(targets):
    return pretty_json(manifest_for_targets(targets)).encode("utf-8")


def runtime_file_hashes(runtime_root):
    root = Path(runtime_root)
    hashes = {}
    if not root.is_dir():
        return hashes
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().lower()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _included_runtime_relative(relative):
            hashes[relative] = sha256_file(path)
    return hashes


def load_runtime_manifest(runtime_root):
    path = Path(runtime_root) / RUNTIME_MANIFEST_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ValueError("runtime manifest must be an object with a files map")
    return data
