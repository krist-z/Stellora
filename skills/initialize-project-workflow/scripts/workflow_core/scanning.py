import json
import os
import re
import stat
import subprocess
import tomllib
from pathlib import Path

from .constants import MANIFEST_NAMES, README_NAMES, SOURCE_EXTENSIONS
from .schema import posix_rel, sha256_file


EXCLUDED_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".pytest_cache", "work-flow"}


def _walk_files(root):
    root = Path(root).resolve()
    files = []

    def visit(directory):
        for entry in sorted(os.scandir(directory), key=lambda item: item.name.casefold()):
            path = Path(entry.path)
            rel = path.relative_to(root)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ValueError(f"cannot inspect project path during scan: {path}: {exc}") from exc
            is_reparse = bool(
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            )
            if entry.is_symlink() or is_reparse:
                raise ValueError(f"symlink/reparse point is not allowed during scan: {path}")
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in EXCLUDED_DIRS:
                    visit(path)
                continue
            if entry.is_file(follow_symlinks=False) and not any(part in EXCLUDED_DIRS for part in rel.parts):
                files.append(path)

    visit(root)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix().lower())


def _category_for(path, root):
    rel = path.relative_to(root)
    name = path.name
    rel_parts = {part.lower() for part in rel.parts}
    lower_name = name.lower()
    if name in MANIFEST_NAMES:
        return "manifests"
    if name in README_NAMES or lower_name.startswith("readme."):
        return "readmes"
    if "test" in rel_parts or "tests" in rel_parts or lower_name.startswith("test_") or lower_name.endswith("_test.py"):
        return "tests"
    if "script" in rel_parts or "scripts" in rel_parts:
        return "scripts"
    if path.suffix.lower() in SOURCE_EXTENSIONS:
        return "source"
    return None


def _make_targets(path):
    targets = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?![=])", line)
            if match and not match.group(1).startswith("."):
                targets.append(match.group(1))
    except OSError:
        return []
    return list(dict.fromkeys(targets))


def _discovered_commands(root, categories):
    commands = {}
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
            if isinstance(scripts, dict):
                for name, body in sorted(scripts.items()):
                    if isinstance(body, str) and body.strip():
                        commands[f"node:{name}"] = {
                            "command": f"npm run {name}",
                            "evidence": f"package.json scripts.{name}",
                        }
        except (OSError, ValueError):
            commands["node:manifest"] = {"status": "未验证", "evidence": "package.json is unreadable"}
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            pyproject_data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project_scripts = pyproject_data.get("project", {}).get("scripts", {})
            if isinstance(project_scripts, dict):
                for name, target in sorted(project_scripts.items()):
                    commands[f"python:entrypoint:{name}"] = {
                        "command": name,
                        "evidence": f"pyproject.toml project.scripts.{name}={target}",
                    }
            tools = pyproject_data.get("tool", {})
            if "pytest" in tools:
                commands["python:test"] = {
                    "command": "python -m pytest",
                    "evidence": "pyproject.toml tool.pytest",
                }
            if "ruff" in tools:
                commands["python:lint"] = {
                    "command": "python -m ruff check .",
                    "evidence": "pyproject.toml tool.ruff",
                }
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            commands["python:manifest"] = {"status": "未验证", "evidence": "pyproject.toml is unreadable"}
    makefile = root / "Makefile"
    if makefile.is_file():
        for target in _make_targets(makefile):
            commands[f"make:{target}"] = {"command": f"make {target}", "evidence": f"Makefile target {target}"}
    standard_manifests = (
        ("Cargo.toml", {"rust:build": "cargo build", "rust:test": "cargo test"}),
        ("go.mod", {"go:build": "go build ./...", "go:test": "go test ./..."}),
        ("pom.xml", {"maven:test": "mvn test", "maven:package": "mvn package"}),
    )
    for manifest, manifest_commands in standard_manifests:
        if (root / manifest).is_file():
            for name, command in manifest_commands.items():
                commands[name] = {"command": command, "evidence": manifest}
    for script_path in categories.get("scripts", []):
        suffix = Path(script_path).suffix.lower()
        prefix = {".py": "python", ".ps1": "powershell -File", ".sh": "bash"}.get(suffix)
        if prefix:
            commands[f"script:{script_path}"] = {
                "command": f"{prefix} {script_path}",
                "evidence": script_path,
            }
    return commands


def scan_project(root):
    root = Path(root).resolve()
    categories = {"manifests": [], "source": [], "tests": [], "scripts": [], "readmes": []}
    file_hashes = {}
    for path in _walk_files(root):
        category = _category_for(path, root)
        if category:
            rel = posix_rel(path, root)
            categories[category].append(rel)
            file_hashes[rel] = sha256_file(path)

    source_inputs = {}
    for name in ("AGENTS.md", "project_rules.md", ".gitignore"):
        path = root / name
        if path.exists() and path.is_file():
            source_inputs[name] = sha256_file(path)

    git_root = None
    git_result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if git_result.returncode == 0 and git_result.stdout.strip():
        candidate = Path(git_result.stdout.strip()).resolve()
        try:
            root.relative_to(candidate)
            git_root = candidate
        except ValueError:
            git_root = None

    return {
        "is_git": git_root is not None,
        "git_root": str(git_root) if git_root else None,
        "counts": {key: len(value) for key, value in categories.items()},
        "files": categories,
        "file_hashes": file_hashes,
        "source_inputs": source_inputs,
        "commands": _discovered_commands(root, categories),
        "sensitive_patterns": ["*.env", "*.pem", "*.key", "*token*", "*secret*"],
    }
