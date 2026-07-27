"""Registered, deterministic project-workflow schema migrations."""

import json
from pathlib import Path

from .constants import RUNTIME_VERSION, SCHEMA_VERSION, STATE_END, STATE_START, TEMPLATE_VERSION
from .schema import pretty_json, sha256_bytes, workspace_identity


SUPPORTED_MIGRATIONS = {(0, 1): "workflow-schema-0-to-1"}


def parse_state_document(text):
    if text.count(STATE_START) != 1 or text.count(STATE_END) != 1:
        raise ValueError("workflow state sentinels are invalid")
    start = text.index(STATE_START) + len(STATE_START)
    end = text.index(STATE_END)
    try:
        data = json.loads(text[start:end].strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"workflow state JSON is invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("workflow state JSON must be an object")
    return data


def render_state_document(data):
    return "# Workflow State\n\n" + STATE_START + "\n" + pretty_json(data) + STATE_END + "\n"


def _migrate_v0_to_v1(root, config, state, managed_files, current_defaults):
    expected_workspace = workspace_identity(root)
    if state.get("workspace_id") != expected_workspace:
        raise ValueError("workflow state workspace identity mismatch")
    migrated_state = dict(state)
    migrated_state.update({
        "schema_version": SCHEMA_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "template_version": TEMPLATE_VERSION,
    })
    for key, default in (
        ("revision", 0),
        ("active_task_id", None),
        ("tasks", {}),
        ("completed_tasks", {}),
        ("recent_events", []),
    ):
        migrated_state.setdefault(key, default)
    if not isinstance(migrated_state["recent_events"], list) or len(migrated_state["recent_events"]) > 50:
        raise ValueError("schema 0 state recent_events must be a list with at most 50 entries")

    migrated_config = dict(config)
    migrated_config.update({
        "schema_version": SCHEMA_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "template_version": TEMPLATE_VERSION,
        "managed_files": sorted(managed_files),
        "runtime_manifest_sha256": current_defaults["runtime_manifest_sha256"],
        "template_baselines": current_defaults["template_baselines"],
        "routing_policy": current_defaults["routing_policy"],
        "concurrency": current_defaults["concurrency"],
        "assurance_levels": current_defaults["assurance_levels"],
    })
    return migrated_config, migrated_state


def build_registered_migration(root, config, config_bytes, state_bytes, managed_files, current_defaults):
    root = Path(root).resolve()
    try:
        state_text = state_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"workflow state is not UTF-8: {exc}") from exc
    source = config.get("schema_version")
    if source == SCHEMA_VERSION:
        state = parse_state_document(state_text)
        if state.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("config and state schema versions differ")
        return None
    migration_id = SUPPORTED_MIGRATIONS.get((source, SCHEMA_VERSION))
    if not migration_id:
        raise ValueError(f"schema migration unavailable: {source!r} -> {SCHEMA_VERSION}")
    state = parse_state_document(state_text)
    if state.get("schema_version") != source:
        raise ValueError("config and state schema versions differ")
    config_hash = sha256_bytes(config_bytes)
    state_hash = sha256_bytes(state_bytes)
    migrated_config, migrated_state = _migrate_v0_to_v1(
        root, config, state, managed_files, current_defaults
    )
    backup_prefix = f"work-flow/.runtime/migration-backups/{migration_id}"
    backup_paths = {
        "config": f"{backup_prefix}-config-{config_hash[:12]}.json",
        "state": f"{backup_prefix}-state-{state_hash[:12]}.md",
    }
    return {
        "migration_id": migration_id,
        "source_schema": source,
        "target_schema": SCHEMA_VERSION,
        "input_hashes": {"work-flow/config.json": config_hash, "work-flow/state.md": state_hash},
        "output_hashes": {
            "work-flow/config.json": sha256_bytes(
                json.dumps(migrated_config, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
            ),
            "work-flow/state.md": sha256_bytes(render_state_document(migrated_state).encode("utf-8")),
        },
        "backup_paths": backup_paths,
        "desired": {
            backup_paths["config"]: config_bytes,
            backup_paths["state"]: state_bytes,
            "work-flow/state.md": render_state_document(migrated_state).encode("utf-8"),
        },
        "config": migrated_config,
    }
