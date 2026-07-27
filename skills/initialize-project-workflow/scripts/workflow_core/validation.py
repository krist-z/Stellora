import ast
import json
from pathlib import Path

from .constants import IGNORE_ENTRIES, RUNTIME_VERSION, SCHEMA_VERSION, STATE_END, STATE_START, STATIC_REQUIRED_FILES, TEMPLATE_VERSION, runtime_core_required_files
from .locking import _validate_lock_document
from .runtime_manifest import load_runtime_manifest, runtime_file_hashes
from .schema import issue, read_text_preserve, safe_join, sha256_file, workspace_identity

PLACEHOLDER_TOKENS = ("TODO", "TBD", "[TODO", "PLACEHOLDER", "???", "{{", "}}")
EXPECTED_ROUTES = {
    "plan": {"role": "pm", "model": "gpt-5.6-sol", "effort_chain": ["ultra", "max", "xhigh", "high"]},
    "plan-review": {"role": "plan-reviewer", "model": "gpt-5.6-sol", "effort_chain": ["ultra", "max", "xhigh", "high"]},
    "code": {"role": "builder", "model": "gpt-5.6-terra", "effort_chain": ["xhigh", "high", "medium"]},
    "text": {"role": "writer", "model": "gpt-5.6-luna", "effort_chain": ["xhigh", "high", "medium"]},
    "reporter": {"role": "reporter", "model": "gpt-5.6-luna", "effort_chain": ["xhigh", "high", "medium"]},
    "explore": {"role": "explorer", "model": "gpt-5.6-luna", "effort_chain": ["high", "medium"]},
    "test": {"role": "tester", "model": "gpt-5.6-terra", "effort_chain": ["xhigh", "high"]},
    "code-review": {"role": "code-reviewer", "model": "gpt-5.6-terra", "effort_chain": ["xhigh", "high"]},
    "risk": {"role": "risk-reviewer", "model": "gpt-5.6-sol", "effort_chain": ["ultra", "max", "xhigh", "high"]},
    "other": {"role": "explorer", "model": "gpt-5.6-terra", "effort_chain": ["high", "medium"]},
}


def _load_config(root, issues):
    path = root / "work-flow/config.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(issue("config_invalid_json", f"config.json is not valid JSON: {exc}", "work-flow/config.json"))
        return None


def _validate_state(root, issues):
    path = root / "work-flow/state.md"
    if not path.is_file():
        return
    text = read_text_preserve(path)
    if text.count(STATE_START) != 1 or text.count(STATE_END) != 1:
        issues.append(issue("state_sentinels_missing", "state.md must contain exactly one JSON sentinel pair.", "work-flow/state.md"))
        return
    try:
        start = text.index(STATE_START) + len(STATE_START)
        data = json.loads(text[start:text.index(STATE_END)].strip())
    except Exception as exc:
        issues.append(issue("state_invalid_json", f"state JSON is invalid: {exc}", "work-flow/state.md"))
        return
    if data.get("schema_version") != SCHEMA_VERSION:
        issues.append(issue("state_schema_version", "state schema version is incorrect.", "work-flow/state.md"))
    if data.get("runtime_version") != RUNTIME_VERSION:
        issues.append(issue("state_runtime_version", "state runtime version is incorrect.", "work-flow/state.md"))
    if data.get("template_version") != TEMPLATE_VERSION:
        issues.append(issue("state_template_version", "state template version is incorrect.", "work-flow/state.md"))
    required = {"revision", "workspace_id", "active_task_id", "tasks", "completed_tasks", "recent_events"}
    missing = sorted(required - set(data))
    if missing:
        issues.append(issue("state_fields_missing", f"state is missing required fields: {', '.join(missing)}.", "work-flow/state.md"))
    if not isinstance(data.get("revision"), int) or data.get("revision", -1) < 0:
        issues.append(issue("state_revision_invalid", "state revision must be a non-negative integer.", "work-flow/state.md"))
    if not isinstance(data.get("workspace_id"), str) or data.get("workspace_id") != workspace_identity(root):
        issues.append(issue("state_workspace_invalid", "state workspace_id must be opaque and non-empty.", "work-flow/state.md"))
    if not isinstance(data.get("tasks"), dict) or not isinstance(data.get("completed_tasks"), dict):
        issues.append(issue("state_tasks_invalid", "state task indexes must be objects.", "work-flow/state.md"))
    if not isinstance(data.get("recent_events"), list) or len(data.get("recent_events", [])) > 50:
        issues.append(issue("state_events_invalid", "state recent_events must contain at most 50 entries.", "work-flow/state.md"))
    try:
        from .state import _validated_result_ref, evidence_records_are_current, read_state

        hydrated = read_state(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        issues.append(issue("state_task_index_invalid", str(exc), "work-flow/state.md"))
        return
    for task in hydrated.get("tasks", {}).values():
        if task.get("phase") != "complete":
            continue
        if not task.get("validation") or (task.get("level") in {"L2", "L3", "L4"} and not task.get("review")):
            issues.append(issue("complete_task_evidence_missing", "complete task is missing required evidence.", "work-flow/state.md"))
            continue
        try:
            result_ref = _validated_result_ref(root, task, task.get("result_ref"))
            if not evidence_records_are_current(root, task) or sha256_file(Path(root) / result_ref) != task.get("result_sha256"):
                raise ValueError("complete task evidence or result hash changed")
        except (OSError, ValueError) as exc:
            issues.append(issue("complete_task_closure_invalid", str(exc), "work-flow/state.md"))
    for completed in hydrated.get("completed_tasks", {}).values():
        result_ref = completed.get("result")
        if completed.get("final_status") != "complete" or not result_ref or not completed.get("result_sha256"):
            issues.append(issue("completed_task_index_invalid", "completed task index is incomplete.", "work-flow/state.md"))
            continue
        try:
            result = safe_join(root, result_ref)
            if not result.is_file() or sha256_file(result) != completed["result_sha256"]:
                raise ValueError("completed task result changed or is missing")
            if not evidence_records_are_current(root, completed):
                raise ValueError("completed task evidence changed or is missing")
        except (OSError, ValueError) as exc:
            issues.append(issue("completed_task_closure_invalid", str(exc), "work-flow/state.md"))


def _validate_gitignore(root, issues):
    path = root / ".gitignore"
    if not path.is_file():
        issues.append(issue("gitignore_missing", ".gitignore is missing.", ".gitignore"))
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    for entry in IGNORE_ENTRIES:
        if lines.count(entry) != 1:
            issues.append(issue("gitignore_entry", f".gitignore must contain exactly one {entry}.", ".gitignore"))


def _validate_lock(root, issues):
    path = root / "work-flow/.runtime/operation-lock.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        error = _validate_lock_document(root, data)
        if error:
            raise ValueError(error)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        issues.append(issue("lock_invalid", str(exc), "work-flow/.runtime/operation-lock.json"))
    for relative in ("work-flow/.runtime/.operation-lock.guard", "work-flow/.state-write.guard"):
        if (root / relative).exists():
            issues.append(issue("operation_guard_present", "an atomic operation guard is still present; inspect before recovery.", relative))


def _validate_placeholders(root, issues):
    checked = ["AGENTS.md", "work-flow/config.json", "work-flow/docs/PROJECT.md", "work-flow/docs/README.md", "work-flow/docs/decisions.md"]
    for rel in checked:
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in PLACEHOLDER_TOKENS:
            if token in text:
                issues.append(issue("placeholder_token", f"managed file contains {token}.", rel))


def _validate_runtime(root, config, issues):
    runtime = root / "work-flow/scripts/_runtime"
    if not runtime.is_dir():
        issues.append(issue("runtime_missing", "self-contained runtime directory is missing.", "work-flow/scripts/_runtime"))
        return
    manifest_path = runtime / "runtime-manifest.json"
    try:
        manifest = load_runtime_manifest(runtime)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        issues.append(issue("runtime_manifest_invalid", str(exc), "work-flow/scripts/_runtime/runtime-manifest.json"))
        manifest = None
    if manifest:
        if (
            manifest.get("schema_version") != 1
            or manifest.get("runtime_version") != RUNTIME_VERSION
            or manifest.get("template_version") != TEMPLATE_VERSION
        ):
            issues.append(issue("runtime_manifest_version", "runtime manifest version is incorrect.", "work-flow/scripts/_runtime/runtime-manifest.json"))
        expected = manifest.get("files", {})
        if not all(isinstance(key, str) and isinstance(value, str) and len(value) == 64 for key, value in expected.items()):
            issues.append(issue("runtime_manifest_invalid", "runtime manifest file hashes are invalid.", "work-flow/scripts/_runtime/runtime-manifest.json"))
        else:
            actual = runtime_file_hashes(runtime)
            for relative in sorted(set(expected) | set(actual)):
                if expected.get(relative) != actual.get(relative):
                    issues.append(issue(
                        "runtime_manifest_hash_mismatch",
                        "runtime file is missing, unexpected, or changed from the installed manifest.",
                        f"work-flow/scripts/_runtime/{relative}",
                    ))
        if isinstance(config, dict) and config.get("runtime_manifest_sha256") != sha256_file(manifest_path):
            issues.append(issue(
                "runtime_manifest_config_mismatch",
                "config.json does not identify the installed runtime manifest.",
                "work-flow/config.json",
            ))
    forbidden = ("F:" + "\\work-flow", "CODEX" + "_HOME")
    for path in sorted(runtime.rglob("*.py"), key=lambda item: item.as_posix().lower()):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in forbidden:
            if token in text:
                issues.append(issue("runtime_external_reference", f"runtime references {token}.", rel))
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            issues.append(issue("runtime_syntax", f"runtime Python syntax error: {exc}", rel))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "initialize-project-workflow" in node.module:
                issues.append(issue("runtime_external_import", "runtime imports the source skill by name.", rel))


def _validate_path_escapes(root, config, issues):
    managed = config.get("managed_files", []) if isinstance(config, dict) else []
    if not isinstance(managed, list):
        issues.append(issue("config_managed_files", "managed_files must be a list.", "work-flow/config.json"))
        return
    for rel in managed:
        if not isinstance(rel, str):
            issues.append(issue("config_managed_files", "managed_files entries must be strings.", "work-flow/config.json"))
            continue
        try:
            safe_join(root, rel)
        except ValueError:
            issues.append(issue("path_escape", f"managed path escapes project root: {rel}", "work-flow/config.json"))


def _validate_root_pointer(root, issues):
    path = root / "AGENTS.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    marker = "<!-- workflow-managed:root-agents:v1 -->"
    if text.count(marker) != 1 or "work-flow/AGENTS.md" not in text:
        issues.append(issue(
            "root_agents_pointer_invalid",
            "root AGENTS.md must be the single managed pointer to work-flow/AGENTS.md.",
            "AGENTS.md",
        ))


def _validate_routing_policy(config, issues):
    actual = config.get("routing_policy") if isinstance(config, dict) else None
    if not isinstance(actual, dict):
        issues.append(issue("config_routing_policy", "routing_policy must be an object.", "work-flow/config.json"))
        return
    for name, expected in EXPECTED_ROUTES.items():
        if actual.get(name) != expected:
            issues.append(issue(
                "config_route_mismatch",
                f"routing policy for {name} must match the hard model, role, and effort chain.",
                "work-flow/config.json",
            ))


def validate_project(root, strict=False):
    root = Path(root).resolve()
    issues = []
    required = list(STATIC_REQUIRED_FILES) + list(runtime_core_required_files())
    for rel in required:
        if not (root / rel).is_file():
            issues.append(issue("required_missing", "required workflow file is missing.", rel))
    config = None
    if (root / "work-flow/config.json").is_file():
        config = _load_config(root, issues)
        if config:
            if config.get("schema_version") != SCHEMA_VERSION:
                issues.append(issue("config_schema_version", "config schema version is incorrect.", "work-flow/config.json"))
            if config.get("runtime_version") != RUNTIME_VERSION:
                issues.append(issue("config_runtime_version", "runtime version is incorrect.", "work-flow/config.json"))
            if config.get("template_version") != TEMPLATE_VERSION:
                issues.append(issue("config_template_version", "template version is incorrect.", "work-flow/config.json"))
            baselines = config.get("template_baselines")
            expected_baselines = {"work-flow/AGENTS.md", "work-flow/project_rules.md"}
            if not isinstance(baselines, dict) or set(baselines) != expected_baselines or not all(
                isinstance(value, str) and len(value) == 64 for value in baselines.values()
            ):
                issues.append(issue("config_template_baselines", "template baseline hashes are missing or invalid.", "work-flow/config.json"))
            _validate_routing_policy(config, issues)
            if config.get("concurrency") != {"max_readers": 3, "max_writers": 1}:
                issues.append(issue("config_concurrency", "concurrency must allow three readers and one writer.", "work-flow/config.json"))
            if set(config.get("assurance_levels", {})) != {"L1", "L2", "L3", "L4"}:
                issues.append(issue("config_assurance_levels", "assurance_levels must define L1 through L4.", "work-flow/config.json"))
    if strict:
        if (root / ".concord").exists() or (root / "docs/concord").exists():
            issues.append(issue("parallel_control_plane", "parallel .concord control plane must be resolved.", ".concord"))
        _validate_state(root, issues)
        _validate_gitignore(root, issues)
        _validate_placeholders(root, issues)
        _validate_runtime(root, config, issues)
        _validate_lock(root, issues)
        _validate_root_pointer(root, issues)
        if config:
            _validate_path_escapes(root, config, issues)
    return {"valid": not issues, "issues": issues, "strict": bool(strict)}
