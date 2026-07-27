import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "initialize-project-workflow" / "scripts" / "workflow_cli.py"
sys.path.insert(0, str(ROOT / "skills" / "initialize-project-workflow" / "scripts"))
from workflow_core.locking import get_operation, lock_command
from workflow_core.plan_generation import _three_way_merge
from workflow_core.routing import classify_worker_error, next_effort, resolve_route
from workflow_core.schema import safe_join, sha256_bytes, workspace_identity
from workflow_core.state import read_state, write_state
from workflow_core.transactions import FileChange, TransactionError, apply_file_changes
from workflow_core.workers import (
    _snapshot,
    _validate_completed_evidence,
    _worker_output_schema,
    build_worker_command,
    worker_command,
)


def cli(root, *args, expect=0):
    env = os.environ.copy()
    env["WORKFLOW_OWNER_ID"] = "runtime-contract-parent"
    result = subprocess.run([sys.executable, str(CLI), *args, "--json"], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, env=env)
    if result.returncode != expect:
        raise AssertionError(f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}")
    return json.loads(result.stdout)


class RuntimeContractsTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="workflow-contract-"))
        plan = cli(self.temp, "init", "--root", str(self.temp), "--mode", "new", "--dry-run")
        cli(self.temp, "init", "--root", str(self.temp), "--mode", "new", "--apply", "--plan-hash", plan["plan_hash"])
        local = self.temp / "work-flow/config.local.json"
        local.write_text(json.dumps({
            "non_git_trust": {"trusted": True, "workspace_id": workspace_identity(self.temp)}
        }), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_hard_routes_and_error_classification(self):
        self.assertEqual(resolve_route("plan")["requested_model"], "gpt-5.6-sol")
        self.assertEqual(resolve_route("code")["requested_model"], "gpt-5.6-terra")
        self.assertEqual(resolve_route("test")["requested_model"], "gpt-5.6-terra")
        self.assertEqual(resolve_route("code-review")["requested_model"], "gpt-5.6-terra")
        self.assertEqual(resolve_route("text")["requested_model"], "gpt-5.6-luna")
        self.assertEqual(resolve_route("explore")["requested_model"], "gpt-5.6-luna")
        self.assertEqual(resolve_route("explorer")["kind"], "explore")
        self.assertEqual(resolve_route("explorer")["requested_model"], "gpt-5.6-luna")
        self.assertEqual(resolve_route("other")["requested_model"], "gpt-5.6-terra")
        reporter = resolve_route("reporter")
        self.assertEqual(reporter["role"], "reporter")
        self.assertEqual(reporter["requested_model"], "gpt-5.6-luna")
        self.assertEqual(reporter["requested_efforts"], ["xhigh", "high", "medium"])
        self.assertEqual(classify_worker_error("unsupported reasoning effort"), "unsupported_effort")
        self.assertEqual(classify_worker_error("HTTP 429 quota exceeded"), "blocked_external")
        self.assertEqual(classify_worker_error("worker test assertion failed"), "worker_failure")
        route = resolve_route("plan")
        self.assertEqual(next_effort(route, "ultra", "unsupported reasoning effort"), "max")
        self.assertEqual(next_effort(route, "max", "model does not support effort"), "xhigh")
        self.assertIsNone(next_effort(route, "xhigh", "HTTP 429 quota exceeded"))

    def test_template_three_way_merge_combines_nonoverlap_and_reports_overlap(self):
        merged, conflicts = _three_way_merge(
            b"first\nsecond\n",
            b"first\nsecond\nlocal\n",
            b"first\nnew\nsecond\n",
        )
        self.assertEqual(conflicts, [])
        self.assertEqual(merged, b"first\nnew\nsecond\nlocal\n")

        merged, conflicts = _three_way_merge(
            b"first\nsecond\n",
            b"first\nlocal-second\n",
            b"first\nnew-second\n",
        )
        self.assertIsNone(merged)
        self.assertTrue(conflicts)

    def test_worker_command_is_structured_and_git_conditional(self):
        route = resolve_route("code")
        schema = self.temp / "schema.json"
        result = self.temp / "result.json"
        non_git = build_worker_command(self.temp, route, None, schema, result)
        self.assertIn("--skip-git-repo-check", non_git)
        self.assertEqual(non_git[non_git.index("--model") + 1], "gpt-5.6-terra")
        self.assertEqual(non_git[non_git.index("--sandbox") + 1], "workspace-write")
        self.assertIn("--output-schema", non_git)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", non_git)
        self.assertNotIn("--ignore-rules", non_git)
        subprocess.run(["git", "init", str(self.temp)], check=True, capture_output=True)
        git_command = build_worker_command(self.temp, route, None, schema, result)
        self.assertNotIn("--skip-git-repo-check", git_command)

    def test_safe_join_rejects_symlink_traversal(self):
        target = self.temp / "real"
        target.mkdir()
        link = self.temp / "linked"
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink unavailable: {exc}")
        with self.assertRaises(ValueError):
            safe_join(self.temp, "linked/file.txt")

    def test_workspace_snapshot_includes_git_metadata_and_symlinks(self):
        git_config = self.temp / ".git/config"
        git_config.parent.mkdir(parents=True, exist_ok=True)
        git_config.write_text("[core]\n", encoding="utf-8")
        target = self.temp / "target.txt"
        target.write_text("target\n", encoding="utf-8")
        link = self.temp / "linked-target"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink unavailable: {exc}")
        snapshot = _snapshot(self.temp)
        self.assertIn(".git/config", snapshot)
        self.assertIn("linked-target", snapshot)

    def test_workspace_snapshot_records_directories_and_empty_directories(self):
        empty = self.temp / "src/empty/nested"
        empty.mkdir(parents=True)
        snapshot = _snapshot(self.temp)
        self.assertEqual(snapshot["src"]["kind"], "directory")
        self.assertEqual(snapshot["src/empty"]["kind"], "directory")
        self.assertEqual(snapshot["src/empty/nested"]["kind"], "directory")

    def test_workspace_snapshot_uses_streamed_hashes_and_disk_backups(self):
        target = self.temp / "src/large.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"workflow-snapshot\n" * 131072)

        fingerprint = _snapshot(self.temp)
        self.assertNotIn("content", fingerprint["src/large.bin"])
        self.assertEqual(fingerprint["src/large.bin"]["size"], target.stat().st_size)
        self.assertEqual(len(fingerprint["src/large.bin"]["sha256"]), 64)

        recoverable = _snapshot(self.temp, capture_backups=True)
        try:
            backup_path = Path(recoverable["src/large.bin"]["backup_path"])
            self.assertTrue(backup_path.is_file())
            self.assertNotIn("content", recoverable["src/large.bin"])
        finally:
            recoverable.close()
        self.assertFalse(backup_path.exists())

    def test_workspace_snapshot_enforces_backup_byte_limit(self):
        target = self.temp / "src/limited.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 2048)
        with self.assertRaisesRegex(ValueError, "snapshot backup limit exceeded"):
            _snapshot(self.temp, capture_backups=True, max_backup_bytes=1024)

    def test_worker_output_schema_requires_validation_only_for_completed(self):
        schema = _worker_output_schema()
        self.assertNotIn("minItems", schema["properties"]["validation"])
        completed_rule = next(
            rule for rule in schema["allOf"]
            if rule["if"]["properties"]["status"].get("const") == "completed"
        )
        validation = completed_rule["then"]["properties"]["validation"]
        self.assertEqual(validation["minItems"], 1)
        self.assertEqual(validation["items"]["type"], "object")

    def test_completed_worker_evidence_must_be_structured_and_passing(self):
        invalid = [
            [],
            ["tests passed"],
            [{}],
            [{"command": "unit tests", "exit_code": 1}],
            [{"command": "unit tests"}],
            [{"evidence": "reviewed source", "status": "not_applicable"}],
        ]
        for evidence in invalid:
            with self.subTest(evidence=evidence):
                self.assertFalse(_validate_completed_evidence(evidence, "builder"))
        self.assertTrue(_validate_completed_evidence(
            [{"command": "python -m unittest", "exit_code": 0}], "builder"
        ))
        self.assertTrue(_validate_completed_evidence(
            [{"evidence": "read-only review completed", "status": "not_applicable"}], "code-reviewer"
        ))

    def test_worker_rejects_malformed_or_failing_validation_and_restores_changes(self):
        task_id = "00000000-0000-0000-0000-000000000725"
        operation_id = "00000000-0000-0000-0000-000000000726"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        real_run = subprocess.run
        result_values = ["tests passed", {}, {"command": "unit", "exit_code": 1}]
        for number, invalid_evidence in enumerate(result_values):
            target = self.temp / f"src/invalid-evidence-{number}.txt"

            def fake_run(command, **kwargs):
                if command and command[0] == "git":
                    return real_run(command, **kwargs)
                result_path = Path(command[command.index("--output-last-message") + 1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("unverified\n", encoding="utf-8")
                result_path.write_text(json.dumps({
                    "schema_version": 1, "task_id": task_id, "operation_id": operation_id,
                    "role": "builder", "backend": "codex-exec", "model": "gpt-5.6-terra",
                    "reasoning_effort": "xhigh", "status": "completed", "summary": "done",
                    "changed_files": [target.relative_to(self.temp).as_posix()],
                    "validation": [invalid_evidence], "findings": [],
                    "new_backlog_items": [], "blockers": [],
                }), encoding="utf-8")
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-terra"}) + "\n",
                    stderr="",
                )

            args = Namespace(
                root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
                expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30,
            )
            with self.subTest(evidence=invalid_evidence), mock.patch(
                "workflow_core.workers.subprocess.run", side_effect=fake_run
            ):
                code, payload = worker_command(args)
                self.assertEqual(code, 2, payload)
                self.assertEqual(payload["status"], "blocked")
                self.assertIn("validation_evidence_invalid", payload["blockers"])
                self.assertFalse(target.exists())

    def test_worker_rejects_non_array_changed_files_without_internal_error(self):
        task_id = "00000000-0000-0000-0000-000000000765"
        operation_id = "00000000-0000-0000-0000-000000000766"
        cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", task_id, "--role", "builder", "--operation-id", operation_id)
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            result_path = Path(command[command.index("--output-last-message") + 1])
            target = self.temp / "src/null-changes.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("rollback\n", encoding="utf-8")
            result_path.write_text(json.dumps({
                "schema_version": 1, "task_id": task_id, "operation_id": operation_id,
                "role": "builder", "backend": "codex-exec", "model": "gpt-5.6-terra",
                "reasoning_effort": "xhigh", "status": "completed", "summary": "done",
                "changed_files": None, "validation": [{"command": "test", "exit_code": 0}],
                "findings": [], "new_backlog_items": [], "blockers": [],
            }), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-terra"}) + "\n", stderr="")

        args = Namespace(root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id, expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30)
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run):
            code, payload = worker_command(args)
        self.assertEqual(code, 2, payload)
        self.assertIn("result_schema_invalid", payload["blockers"])
        self.assertFalse((self.temp / "src/null-changes.txt").exists())

    def test_worker_rejects_and_restores_out_of_scope_empty_directory(self):
        task_id = "00000000-0000-0000-0000-000000000727"
        operation_id = "00000000-0000-0000-0000-000000000728"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        outside_dir = self.temp / "not-allowed/empty"

        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            result_path = Path(command[command.index("--output-last-message") + 1])
            outside_dir.mkdir(parents=True)
            result_path.write_text(json.dumps({
                "schema_version": 1, "task_id": task_id, "operation_id": operation_id,
                "role": "builder", "backend": "codex-exec", "model": "gpt-5.6-terra",
                "reasoning_effort": "xhigh", "status": "completed", "summary": "done",
                "changed_files": [],
                "validation": [{"command": "targeted-test", "exit_code": 0}],
                "findings": [], "new_backlog_items": [], "blockers": [],
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-terra"}) + "\n",
                stderr="",
            )

        args = Namespace(
            root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
            expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30,
        )
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run):
            code, payload = worker_command(args)
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse((self.temp / "not-allowed").exists())

    def test_worker_rejects_symlink_as_an_allowed_write_root(self):
        task_id = "00000000-0000-0000-0000-000000000707"
        operation_id = "00000000-0000-0000-0000-000000000708"
        outside = Path(tempfile.mkdtemp(prefix="workflow-outside-"))
        linked = self.temp / "linked-outside"
        try:
            try:
                os.symlink(outside, linked, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            cli(
                self.temp, "lock", "acquire", "--root", str(self.temp),
                "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
            )
            args = Namespace(
                root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
                expected_revision=0, prompt_file=None, allowed_path=["linked-outside"], timeout_seconds=30,
            )
            with mock.patch("workflow_core.workers.subprocess.run") as run:
                code, payload = worker_command(args)
            self.assertEqual(code, 2)
            self.assertEqual(payload["error"], "allowed_path_escape")
            self.assertFalse(any(call.args and call.args[0] and call.args[0][0] == "codex" for call in run.call_args_list))
        finally:
            if linked.is_symlink():
                linked.unlink()
            shutil.rmtree(outside, ignore_errors=True)

    def test_worker_rejects_parent_owned_allowed_paths_before_spawn(self):
        task_id = "00000000-0000-0000-0000-000000000729"
        operation_id = "00000000-0000-0000-0000-000000000730"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        for protected in (".git", "work-flow", "work-flow/state.md", "work-flow/.runtime"):
            args = Namespace(
                root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
                expected_revision=0, prompt_file=None, allowed_path=[protected], timeout_seconds=30,
            )
            with self.subTest(path=protected), mock.patch("workflow_core.workers.subprocess.run") as run:
                code, payload = worker_command(args)
                self.assertEqual(code, 2, payload)
                self.assertEqual(payload["error"], "allowed_path_protected")
                self.assertFalse(any(
                    call.args and call.args[0] and call.args[0][0] == "codex"
                    for call in run.call_args_list
                ))

    def test_transaction_rejects_target_changed_after_plan(self):
        target = self.temp / "user.txt"
        target.write_text("planned\n", encoding="utf-8")
        change = FileChange(
            relative_path="user.txt", content=b"workflow\n",
            expected_sha256=sha256_bytes(b"planned\n"),
        )
        target.write_text("concurrent user edit\n", encoding="utf-8")
        with self.assertRaises(TransactionError) as raised:
            apply_file_changes(self.temp, [change])
        self.assertEqual(raised.exception.exit_code, 4)
        self.assertEqual(target.read_text(encoding="utf-8"), "concurrent user edit\n")

    def test_noop_transaction_still_runs_post_validation(self):
        with self.assertRaises(TransactionError) as raised:
            apply_file_changes(
                self.temp,
                [],
                post_validate=lambda: {"valid": False, "issues": [{"code": "required_missing"}]},
            )
        self.assertEqual(raised.exception.exit_code, 2)

    def test_transaction_contender_does_not_remove_another_owners_guard(self):
        runtime = self.temp / "work-flow/.runtime"
        guard = runtime / ".transaction.guard"
        guard.write_text("owner-operation\n", encoding="utf-8")
        change = FileChange(
            relative_path="contended.txt",
            content=b"must not be written\n",
            expected_sha256=None,
        )
        with self.assertRaises(TransactionError) as raised:
            apply_file_changes(self.temp, [change])
        self.assertEqual(raised.exception.exit_code, 4)
        self.assertEqual(guard.read_text(encoding="utf-8"), "owner-operation\n")
        self.assertFalse((self.temp / "contended.txt").exists())

    def test_worker_rejects_and_restores_protected_changes(self):
        task_id = "00000000-0000-0000-0000-000000000701"
        operation_id = "00000000-0000-0000-0000-000000000702"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        state_path = self.temp / "work-flow/state.md"
        original_state = state_path.read_bytes()

        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            result_path = Path(command[command.index("--output-last-message") + 1])
            source_path = self.temp / "src/out.txt"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("worker output\n", encoding="utf-8")
            state_path.write_text("unauthorized\n", encoding="utf-8")
            result_path.write_text(json.dumps({
                "schema_version": 1, "task_id": task_id, "operation_id": operation_id,
                "role": "builder", "backend": "codex-exec", "model": "gpt-5.6-terra",
                "reasoning_effort": "xhigh", "status": "completed", "summary": "done",
                "changed_files": ["src/out.txt", "work-flow/state.md"], "validation": [],
                "findings": [], "new_backlog_items": [], "blockers": [],
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-terra"}) + "\n",
                stderr="",
            )

        args = Namespace(
            root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
            expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30,
        )
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run):
            code, payload = worker_command(args)
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("work-flow/state.md", payload["unauthorized_changes"])
        self.assertEqual(state_path.read_bytes(), original_state)
        self.assertFalse((self.temp / "src/out.txt").exists())

    def test_worker_requires_validation_evidence_before_accepting_changes(self):
        task_id = "00000000-0000-0000-0000-000000000705"
        operation_id = "00000000-0000-0000-0000-000000000706"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            result_path = Path(command[command.index("--output-last-message") + 1])
            target = self.temp / "src/no-evidence.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("unverified\n", encoding="utf-8")
            result_path.write_text(json.dumps({
                "schema_version": 1, "task_id": task_id, "operation_id": operation_id,
                "role": "builder", "backend": "codex-exec", "model": "gpt-5.6-terra",
                "reasoning_effort": "xhigh", "status": "completed", "summary": "done",
                "changed_files": ["src/no-evidence.txt"], "validation": [], "findings": [],
                "new_backlog_items": [], "blockers": [],
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-terra"}) + "\n",
                stderr="",
            )

        args = Namespace(
            root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
            expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30,
        )
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run):
            code, payload = worker_command(args)
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("validation_evidence_missing", payload["blockers"])
        self.assertFalse((self.temp / "src/no-evidence.txt").exists())

    def test_worker_preserves_parent_owned_lock_heartbeat(self):
        task_id = "00000000-0000-0000-0000-000000000709"
        operation_id = "00000000-0000-0000-0000-000000000710"
        acquired = cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        self.assertEqual(acquired["revision"], 1)
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            heartbeat_code, heartbeat = lock_command(Namespace(
                action="heartbeat", root=str(self.temp), task_id=task_id, role="builder",
                workspace_id=None, owner="runtime-contract-parent", operation_id=operation_id, reason=None,
                force_stale=False, stale_after_seconds=300,
            ))
            self.assertEqual(heartbeat_code, 0)
            self.assertEqual(heartbeat["revision"], 2)
            result_path = Path(command[command.index("--output-last-message") + 1])
            target = self.temp / "src/heartbeat-safe.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("accepted\n", encoding="utf-8")
            result_path.write_text(json.dumps({
                "schema_version": 1, "task_id": task_id, "operation_id": operation_id,
                "role": "builder", "backend": "codex-exec", "model": "gpt-5.6-terra",
                "reasoning_effort": "xhigh", "status": "completed", "summary": "done",
                "changed_files": ["src/heartbeat-safe.txt"],
                "validation": [{"command": "targeted-test", "exit_code": 0}],
                "findings": [], "new_backlog_items": [], "blockers": [],
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-terra"}) + "\n",
                stderr="",
            )

        args = Namespace(
            root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
            expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30,
        )
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run):
            code, payload = worker_command(args)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["changed_files"], ["src/heartbeat-safe.txt"])
        self.assertEqual(
            json.loads((self.temp / "work-flow/.runtime/operation-lock.json").read_text(encoding="utf-8"))["revision"],
            2,
        )

    def test_worker_automatically_heartbeats_while_cli_is_running(self):
        task_id = "00000000-0000-0000-0000-000000000749"
        operation_id = "00000000-0000-0000-0000-000000000750"
        acquired = cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        initial_heartbeat = acquired["lock"]["heartbeat_at"]

        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            time.sleep(0.08)
            result_path = Path(command[command.index("--output-last-message") + 1])
            target = self.temp / "src/automatic-heartbeat.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("accepted\n", encoding="utf-8")
            result_path.write_text(json.dumps({
                "schema_version": 1, "task_id": task_id, "operation_id": operation_id,
                "role": "builder", "backend": "codex-exec", "model": "gpt-5.6-terra",
                "reasoning_effort": "xhigh", "status": "completed", "summary": "done",
                "changed_files": ["src/automatic-heartbeat.txt"],
                "validation": [{"command": "targeted-test", "exit_code": 0}],
                "findings": [], "new_backlog_items": [], "blockers": [],
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-terra"}) + "\n",
                stderr="",
            )

        args = Namespace(
            root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
            expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30,
            heartbeat_interval_seconds=0.01,
        )
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run):
            code, payload = worker_command(args)

        self.assertEqual(code, 0, payload)
        self.assertGreaterEqual(payload["heartbeat"]["successful"], 1)
        operation = get_operation(self.temp, operation_id)
        self.assertGreater(operation["heartbeat_at"], initial_heartbeat)

    def test_concurrent_reader_heartbeat_is_not_reverted_by_worker_snapshot(self):
        task_a = "00000000-0000-0000-0000-000000000754"
        operation_a = "00000000-0000-0000-0000-000000000755"
        task_b = "00000000-0000-0000-0000-000000000756"
        operation_b = "00000000-0000-0000-0000-000000000757"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_a, "--role", "explorer", "--operation-id", operation_a,
        )
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_b, "--role", "explorer", "--operation-id", operation_b,
        )
        before_b = get_operation(self.temp, operation_b)["heartbeat_at"]
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            code, heartbeat = lock_command(Namespace(
                action="heartbeat", root=str(self.temp), task_id=task_b, role="explorer",
                workspace_id=None, owner="runtime-contract-parent", operation_id=operation_b,
                reason=None, guard_id=None, force_stale=False, stale_after_seconds=300,
            ))
            self.assertEqual(code, 0, heartbeat)
            result_path = Path(command[command.index("--output-last-message") + 1])
            result_path.write_text(json.dumps({
                "schema_version": 1, "task_id": task_a, "operation_id": operation_a,
                "role": "explorer", "backend": "codex-exec", "model": "gpt-5.6-luna",
                "reasoning_effort": "high", "status": "completed", "summary": "done",
                "changed_files": [],
                "validation": [{"evidence": "read-only review", "status": "not_applicable"}],
                "findings": [], "new_backlog_items": [], "blockers": [],
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-luna"}) + "\n",
                stderr="",
            )

        args = Namespace(
            root=str(self.temp), task_id=task_a, role="explorer", operation_id=operation_a,
            expected_revision=0, prompt_file=None, allowed_path=[], timeout_seconds=30,
            heartbeat_interval_seconds=60, snapshot_max_bytes=1024 * 1024 * 1024,
        )
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run):
            code, payload = worker_command(args)
        self.assertEqual(code, 0, payload)
        self.assertGreater(get_operation(self.temp, operation_b)["heartbeat_at"], before_b)

    def test_worker_blocks_when_heartbeat_guard_stays_busy(self):
        task_id = "00000000-0000-0000-0000-000000000761"
        operation_id = "00000000-0000-0000-0000-000000000762"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            time.sleep(0.08)
            result_path = Path(command[command.index("--output-last-message") + 1])
            target = self.temp / "src/stalled-heartbeat.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("must roll back\n", encoding="utf-8")
            result_path.write_text(json.dumps({
                "schema_version": 1, "task_id": task_id, "operation_id": operation_id,
                "role": "builder", "backend": "codex-exec", "model": "gpt-5.6-terra",
                "reasoning_effort": "xhigh", "status": "completed", "summary": "done",
                "changed_files": ["src/stalled-heartbeat.txt"],
                "validation": [{"command": "targeted-test", "exit_code": 0}],
                "findings": [], "new_backlog_items": [], "blockers": [],
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-terra"}) + "\n",
                stderr="",
            )

        args = Namespace(
            root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
            expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30,
            heartbeat_interval_seconds=0.01, heartbeat_stall_seconds=0.03,
            snapshot_max_bytes=1024 * 1024 * 1024,
        )
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run), mock.patch(
            "workflow_core.workers.lock_command",
            return_value=(4, {"error": "lock_mutation_busy"}),
        ):
            code, payload = worker_command(args)
        self.assertEqual(code, 3, payload)
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("operation_heartbeat_failed", payload["blockers"])
        self.assertFalse((self.temp / "src/stalled-heartbeat.txt").exists())

    def test_worker_reports_incomplete_rollback_for_malformed_lock_and_restores_business_changes(self):
        task_id = "00000000-0000-0000-0000-000000000731"
        operation_id = "00000000-0000-0000-0000-000000000732"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        lock_path = self.temp / "work-flow/.runtime/operation-lock.json"
        lock_before = lock_path.read_bytes()
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            target = self.temp / "src/malformed-lock.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("must roll back\n", encoding="utf-8")
            malformed = json.loads(lock_before.decode("utf-8"))
            malformed["revision"] = "not-an-integer"
            lock_path.write_text(json.dumps(malformed), encoding="utf-8")
            result_path = Path(command[command.index("--output-last-message") + 1])
            result_path.write_text(json.dumps({
                "schema_version": 1, "task_id": task_id, "operation_id": operation_id,
                "role": "builder", "backend": "codex-exec", "model": "gpt-5.6-terra",
                "reasoning_effort": "xhigh", "status": "completed", "summary": "done",
                "changed_files": ["src/malformed-lock.txt", "work-flow/.runtime/operation-lock.json"],
                "validation": [{"command": "targeted-test", "exit_code": 0}],
                "findings": [], "new_backlog_items": [], "blockers": [],
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-terra"}) + "\n",
                stderr="",
            )

        args = Namespace(
            root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
            expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30,
        )
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run):
            code, payload = worker_command(args)
        self.assertEqual(code, 6, payload)
        self.assertEqual(payload["error"], "worker_rollback_incomplete")
        self.assertEqual(payload["paths"], ["work-flow/.runtime/operation-lock.json"])
        self.assertNotEqual(lock_path.read_bytes(), lock_before)
        self.assertFalse((self.temp / "src/malformed-lock.txt").exists())

    def test_worker_retries_effort_only_for_explicit_unsupported_error(self):
        task_id = "00000000-0000-0000-0000-000000000711"
        operation_id = "00000000-0000-0000-0000-000000000712"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        real_run = subprocess.run
        calls = []

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            calls.append(command)
            effort_config = command[command.index("--config") + 1]
            if len(calls) == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported reasoning effort: xhigh")
            self.assertIn('"high"', effort_config)
            result_path = Path(command[command.index("--output-last-message") + 1])
            target = self.temp / "src/retry.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("retried\n", encoding="utf-8")
            result_path.write_text(json.dumps({
                "schema_version": 1, "task_id": task_id, "operation_id": operation_id,
                "role": "builder", "backend": "codex-exec", "model": "gpt-5.6-terra",
                "reasoning_effort": "high", "status": "completed", "summary": "done",
                "changed_files": ["src/retry.txt"],
                "validation": [{"command": "targeted-test", "exit_code": 0}], "findings": [],
                "new_backlog_items": [], "blockers": [],
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"type": "thread.started", "model": "gpt-5.6-terra"}) + "\n",
                stderr="",
            )

        args = Namespace(
            root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
            expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30,
        )
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run):
            code, payload = worker_command(args)
        self.assertEqual(code, 0)
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(payload["effort_fallback_reason"], "explicit_unsupported_effort")
        self.assertEqual(len(payload["attempts"]), 2)
        self.assertTrue(payload["result_file"].endswith(f"{task_id}-{operation_id}.json"))
        self.assertEqual(payload["requested_model"], "gpt-5.6-terra")
        self.assertEqual(payload["configured_model"], "gpt-5.6-terra")
        self.assertIsNone(payload["provider_observed_model"])
        self.assertEqual(payload["provider_attestation"], "unavailable")

    def test_worker_does_not_retry_quota_error(self):
        task_id = "00000000-0000-0000-0000-000000000721"
        operation_id = "00000000-0000-0000-0000-000000000722"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        real_run = subprocess.run
        calls = []

        def fake_run(command, **kwargs):
            if command and command[0] == "git":
                return real_run(command, **kwargs)
            calls.append(command)
            return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 429 quota exceeded")

        args = Namespace(
            root=str(self.temp), task_id=task_id, role="builder", operation_id=operation_id,
            expected_revision=0, prompt_file=None, allowed_path=["src"], timeout_seconds=30,
        )
        with mock.patch("workflow_core.workers.subprocess.run", side_effect=fake_run):
            code, payload = worker_command(args)
        self.assertEqual(code, 3)
        self.assertEqual(payload["error_category"], "blocked_external")
        self.assertEqual(len(calls), 1)

    def test_three_readers_and_single_writer(self):
        for number in range(3):
            payload = cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", f"00000000-0000-0000-0000-00000000000{number+1}", "--role", "explorer", "--operation-id", f"00000000-0000-0000-0000-00000000010{number}")
            self.assertEqual(payload["status"], "acquired")
        fourth = cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", "00000000-0000-0000-0000-000000000004", "--role", "explorer", "--operation-id", "00000000-0000-0000-0000-000000000103", expect=4)
        self.assertEqual(fourth["error"], "read_lock_limit")
        for number in range(3):
            cli(self.temp, "lock", "release", "--root", str(self.temp), "--operation-id", f"00000000-0000-0000-0000-00000000010{number}")
        writer = cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", "00000000-0000-0000-0000-000000000010", "--role", "builder", "--operation-id", "00000000-0000-0000-0000-000000000201")
        self.assertEqual(writer["status"], "acquired")
        blocked = cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", "00000000-0000-0000-0000-000000000011", "--role", "explorer", "--operation-id", "00000000-0000-0000-0000-000000000204", expect=4)
        self.assertEqual(blocked["error"], "read_blocked_by_writer")
        cli(self.temp, "lock", "release", "--root", str(self.temp), "--operation-id", "00000000-0000-0000-0000-000000000201")

    def test_state_revision_and_operation_lock(self):
        task = cli(self.temp, "task", "add", "--root", str(self.temp), "--title", "contract", "--kind", "code", "--level", "L1", "--expected-revision", "0", "--operation-id", "00000000-0000-0000-0000-000000000999", expect=4)
        self.assertEqual(task["error"], "operation_lock_required")
        cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", "00000000-0000-0000-0000-000000000020", "--role", "builder", "--operation-id", "00000000-0000-0000-0000-000000000202")
        added = cli(self.temp, "task", "add", "--root", str(self.temp), "--title", "contract", "--kind", "code", "--level", "L1", "--expected-revision", "0", "--operation-id", "00000000-0000-0000-0000-000000000202")
        self.assertEqual(added["state"]["revision"], 1)
        stale = cli(self.temp, "transition", "--root", str(self.temp), "--task-id", added["task"]["task_id"], "--to", "planned", "--expected-revision", "0", "--operation-id", "00000000-0000-0000-0000-000000000202", expect=4)
        self.assertEqual(stale["error"], "revision_conflict")
        cli(self.temp, "lock", "release", "--root", str(self.temp), "--operation-id", "00000000-0000-0000-0000-000000000202")

    def test_state_stores_only_active_task_in_full_and_hydrates_inactive_index(self):
        first_id = "00000000-0000-0000-0000-000000000761"
        first_operation = "00000000-0000-0000-0000-000000000762"
        cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", first_id, "--role", "builder", "--operation-id", first_operation)
        first = cli(
            self.temp, "task", "add", "--root", str(self.temp), "--task-id", first_id,
            "--title", "First pending task", "--kind", "code", "--level", "L1",
            "--expected-revision", "0", "--operation-id", first_operation,
        )
        cli(self.temp, "lock", "release", "--root", str(self.temp), "--operation-id", first_operation)
        second_id = "00000000-0000-0000-0000-000000000763"
        second_operation = "00000000-0000-0000-0000-000000000764"
        cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", second_id, "--role", "builder", "--operation-id", second_operation)
        cli(
            self.temp, "task", "add", "--root", str(self.temp), "--task-id", second_id,
            "--title", "Second active task", "--kind", "code", "--level", "L1",
            "--expected-revision", str(first["state"]["revision"]), "--operation-id", second_operation,
        )
        state_text = (self.temp / "work-flow/state.md").read_text(encoding="utf-8")
        start = state_text.index("---workflow-state-json-v1---") + len("---workflow-state-json-v1---")
        end = state_text.index("---end-workflow-state-json---")
        stored = json.loads(state_text[start:end].strip())
        self.assertEqual(stored["active_task_id"], second_id)
        self.assertIn("state_ref", stored["tasks"][first_id])
        self.assertNotIn("approvals", stored["tasks"][first_id])
        self.assertIn("approvals", stored["tasks"][second_id])
        task_state = self.temp / stored["tasks"][first_id]["state_ref"]
        self.assertTrue(task_state.is_file())
        self.assertIn(f"task_id: {first_id}", task_state.read_text(encoding="utf-8"))
        hydrated = read_state(self.temp)
        self.assertIn("approvals", hydrated["tasks"][first_id])
        self.assertEqual(hydrated["tasks"][first_id]["title"], "First pending task")

    def test_l2_continues_by_default_and_gates_only_declared_confirmation_risks(self):
        first_task = "00000000-0000-0000-0000-000000000231"
        first_operation = "00000000-0000-0000-0000-000000000232"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", first_task, "--role", "builder", "--operation-id", first_operation,
        )
        added = cli(
            self.temp, "task", "add", "--root", str(self.temp), "--task-id", first_task,
            "--title", "Clear L2 task", "--kind", "code", "--level", "L2",
            "--expected-revision", "0", "--operation-id", first_operation,
        )
        planned = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", first_task,
            "--to", "planned", "--expected-revision", str(added["state"]["revision"]),
            "--operation-id", first_operation,
        )
        next_action = cli(self.temp, "next-action", "--root", str(self.temp), "--task-id", first_task)
        self.assertEqual(next_action["next"], {"action": "transition", "to": "implementing"})
        cli(self.temp, "lock", "release", "--root", str(self.temp), "--operation-id", first_operation)

        gated_task = "00000000-0000-0000-0000-000000000233"
        gated_operation = "00000000-0000-0000-0000-000000000234"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", gated_task, "--role", "builder", "--operation-id", gated_operation,
        )
        gated = cli(
            self.temp, "task", "add", "--root", str(self.temp), "--task-id", gated_task,
            "--title", "Ambiguous L2 task", "--kind", "code", "--level", "L2",
            "--requires-confirmation", "--confirmation-reason", "public_api_change",
            "--expected-revision", str(planned["state"]["revision"]), "--operation-id", gated_operation,
        )
        gated_planned = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", gated_task,
            "--to", "planned", "--expected-revision", str(gated["state"]["revision"]),
            "--operation-id", gated_operation,
        )
        gated_next = cli(self.temp, "next-action", "--root", str(self.temp), "--task-id", gated_task)
        self.assertEqual(gated_next["next"]["action"], "wait_user")
        self.assertEqual(gated_next["next"]["gate"], "l2_confirmation")
        self.assertEqual(gated_next["next"]["reasons"], ["public_api_change"])
        blocked = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", gated_task,
            "--to", "implementing", "--expected-revision", str(gated_planned["state"]["revision"]),
            "--operation-id", gated_operation, expect=2,
        )
        self.assertEqual(blocked["error"], "confirmation_required")
        approved = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", gated_task,
            "--to", "approved", "--expected-revision", str(gated_planned["state"]["revision"]),
            "--operation-id", gated_operation,
        )
        self.assertEqual(approved["task"]["phase"], "approved")

    def test_state_event_window_archives_dropped_events(self):
        task_id = "00000000-0000-0000-0000-000000000211"
        operation_id = "00000000-0000-0000-0000-000000000212"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "reporter", "--operation-id", operation_id,
        )
        state = read_state(self.temp)
        state["recent_events"] = [
            {"at": f"2026-07-26T00:00:{index:02d}Z", "name": f"event-{index}", "detail": {"index": index}}
            for index in range(55)
        ]
        written = write_state(self.temp, state, expected_revision=0, operation_id=operation_id)
        self.assertEqual(len(written["recent_events"]), 50)
        archive = self.temp / "work-flow/docs/archive/2026.md"
        text = archive.read_text(encoding="utf-8")
        self.assertIn("event-0", text)
        self.assertIn("event-4", text)
        self.assertNotIn("event-5`", text)

    def test_l3_requires_intent_plan_authorization_and_batch_freeze(self):
        task_id = "00000000-0000-0000-0000-000000000221"
        operation_id = "00000000-0000-0000-0000-000000000222"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        added = cli(
            self.temp, "task", "add", "--root", str(self.temp), "--task-id", task_id,
            "--title", "L3 gated task", "--kind", "code", "--level", "L3",
            "--expected-revision", "0", "--operation-id", operation_id,
        )
        revision = added["state"]["revision"]
        cli(self.temp, "lock", "release", "--root", str(self.temp), "--operation-id", operation_id)
        batch_children = [
            ("00000000-0000-0000-0000-000000000223", "00000000-0000-0000-0000-000000000225"),
            ("00000000-0000-0000-0000-000000000224", "00000000-0000-0000-0000-000000000226"),
        ]
        for child_task, child_operation in batch_children:
            cli(
                self.temp, "lock", "acquire", "--root", str(self.temp),
                "--task-id", child_task, "--role", "builder", "--operation-id", child_operation,
            )
            child = cli(
                self.temp, "task", "add", "--root", str(self.temp), "--task-id", child_task,
                "--title", "L3 batch child", "--kind", "code", "--level", "L3",
                "--expected-revision", str(revision), "--operation-id", child_operation,
            )
            revision = child["state"]["revision"]
            cli(self.temp, "lock", "release", "--root", str(self.temp), "--operation-id", child_operation)
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        missing_intent = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "planned", "--expected-revision", str(revision), "--operation-id", operation_id,
            expect=2,
        )
        self.assertEqual(missing_intent["gate"], "intent_and_scope_confirmation")
        planned = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "planned", "--intent-hash", "intent-sha256",
            "--expected-revision", str(revision), "--operation-id", operation_id,
        )
        revision = planned["state"]["revision"]
        missing_plan = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "approved", "--expected-revision", str(revision), "--operation-id", operation_id,
            expect=2,
        )
        self.assertEqual(missing_plan["gate"], "technical_plan_confirmation")
        approved = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "approved", "--technical-plan-hash", "plan-sha256",
            "--authorization-id", "user-authorization",
            "--expected-revision", str(revision), "--operation-id", operation_id,
        )
        revision = approved["state"]["revision"]
        missing_batch = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "implementing", "--expected-revision", str(revision), "--operation-id", operation_id,
            expect=2,
        )
        self.assertEqual(missing_batch["gate"], "batch_freeze")
        implementing = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "implementing",
            "--batch-task-id", task_id,
            "--batch-task-id", batch_children[0][0],
            "--batch-task-id", batch_children[1][0],
            "--expected-revision", str(revision), "--operation-id", operation_id,
        )
        self.assertEqual(len(implementing["task"]["batch"]["task_ids"]), 3)

    def test_l4_requires_complete_risk_release_gate(self):
        task_id = "00000000-0000-0000-0000-000000000741"
        operation_id = "00000000-0000-0000-0000-000000000742"
        cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", task_id, "--role", "builder", "--operation-id", operation_id)
        added = cli(
            self.temp, "task", "add", "--root", str(self.temp), "--task-id", task_id,
            "--title", "L4 gate", "--kind", "risk", "--level", "L4",
            "--expected-revision", "0", "--operation-id", operation_id,
        )
        revision = added["state"]["revision"]
        cli(self.temp, "lock", "release", "--root", str(self.temp), "--operation-id", operation_id)
        batch_ids = [task_id]
        for number in (3, 4):
            child_id = f"00000000-0000-0000-0000-00000000074{number}"
            child_operation = f"00000000-0000-0000-0000-00000000075{number}"
            batch_ids.append(child_id)
            cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", child_id, "--role", "builder", "--operation-id", child_operation)
            child = cli(
                self.temp, "task", "add", "--root", str(self.temp), "--task-id", child_id,
                "--title", f"batch {number}", "--kind", "code", "--level", "L1",
                "--expected-revision", str(revision), "--operation-id", child_operation,
            )
            revision = child["state"]["revision"]
            cli(self.temp, "lock", "release", "--root", str(self.temp), "--operation-id", child_operation)
        cli(self.temp, "lock", "acquire", "--root", str(self.temp), "--task-id", task_id, "--role", "builder", "--operation-id", operation_id)
        planned = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "planned", "--intent-hash", "intent", "--expected-revision", str(revision),
            "--operation-id", operation_id,
        )
        approved = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "approved", "--technical-plan-hash", "plan", "--authorization-id", "human-auth",
            "--expected-revision", str(planned["state"]["revision"]), "--operation-id", operation_id,
        )
        batch_args = sum((["--batch-task-id", value] for value in batch_ids), [])
        missing = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "implementing", *batch_args,
            "--expected-revision", str(approved["state"]["revision"]), "--operation-id", operation_id,
            expect=2,
        )
        self.assertEqual(missing["gate"], "human_risk_confirmation")
        implementing = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "implementing", *batch_args,
            "--risk-confirmation", "confirmed", "--target-system", "service-a",
            "--target-environment", "production", "--target-object", "deployment-a",
            "--backup-ref", "backup.md", "--rollback-ref", "rollback.md",
            "--monitoring-ref", "monitoring.md", "--stop-condition", "error-rate threshold",
            "--external-write-scope", "deployment-a only",
            "--post-action-validation-ref", "post-validation.md", "--audit-result-ref", "audit.md",
            "--expected-revision", str(approved["state"]["revision"]), "--operation-id", operation_id,
        )
        self.assertEqual(implementing["task"]["approvals"]["l4"]["target_environment"], "production")
        self.assertEqual(len(implementing["task"]["batch"]["task_ids"]), 3)

    def test_lock_identity_and_explicit_stale_recovery(self):
        task_id = "00000000-0000-0000-0000-000000000301"
        operation_id = "00000000-0000-0000-0000-000000000302"
        cli(
            self.temp,
            "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder",
            "--owner", "owner-a", "--operation-id", operation_id,
        )
        self.assertIsNotNone(get_operation(self.temp, operation_id))
        self.assertIsNone(get_operation(self.temp, operation_id, workspace_id="ws-not-this-project"))

        wrong_task = cli(
            self.temp,
            "lock", "heartbeat", "--root", str(self.temp),
            "--task-id", "00000000-0000-0000-0000-000000000399",
            "--role", "builder", "--operation-id", operation_id,
            expect=4,
        )
        self.assertEqual(wrong_task["error"], "task_id_mismatch")

        wrong_workspace = cli(
            self.temp,
            "lock", "heartbeat", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder",
            "--workspace-id", "ws-not-this-project", "--operation-id", operation_id,
            expect=4,
        )
        self.assertEqual(wrong_workspace["error"], "workspace_identity_mismatch")

        wrong_owner = cli(
            self.temp,
            "lock", "release", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--owner", "owner-b",
            "--operation-id", operation_id,
            expect=4,
        )
        self.assertEqual(wrong_owner["error"], "owner_mismatch")

        fresh_recovery = cli(
            self.temp,
            "lock", "recover", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--owner", "operator-a",
            "--reason", "test recovery must be explicitly stale",
            "--operation-id", operation_id,
            expect=4,
        )
        self.assertEqual(fresh_recovery["error"], "lock_not_stale")

        recovered = cli(
            self.temp,
            "lock", "recover", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--owner", "operator-a",
            "--reason", "forced test recovery",
            "--force-stale", "--operation-id", operation_id,
        )
        self.assertEqual(recovered["status"], "recovered")
        self.assertTrue(recovered["forced"])

    def test_stale_operation_guard_requires_exact_explicit_recovery(self):
        guard = self.temp / "work-flow/.runtime/.operation-lock.guard"
        guard_id = "00000000-0000-0000-0000-000000000751"
        guard.write_text(json.dumps({
            "schema_version": 1,
            "guard_id": guard_id,
            "owner_session": "dead-parent",
            "operation_id": "00000000-0000-0000-0000-000000000752",
            "acquired_at": "2000-01-01T00:00:00Z",
        }) + "\n", encoding="utf-8")

        mismatch = cli(
            self.temp, "lock", "recover-guard", "--root", str(self.temp),
            "--guard-id", "00000000-0000-0000-0000-000000000753",
            "--owner", "recovery-operator", "--reason", "stale test guard",
            expect=4,
        )
        self.assertEqual(mismatch["error"], "guard_identity_mismatch")
        self.assertTrue(guard.exists())

        recovered = cli(
            self.temp, "lock", "recover-guard", "--root", str(self.temp),
            "--guard-id", guard_id, "--owner", "recovery-operator",
            "--reason", "stale test guard",
        )
        self.assertEqual(recovered["status"], "guard_recovered")
        self.assertFalse(guard.exists())
        audit = self.temp / "work-flow/.runtime/transactions/lock-recovery.jsonl"
        self.assertIn("lock.guard_recover", audit.read_text(encoding="utf-8"))

    def test_guard_recovery_mutex_blocks_path_reuse_during_atomic_claim(self):
        guard = self.temp / "work-flow/.runtime/.operation-lock.guard"
        guard_id = "00000000-0000-0000-0000-000000000758"
        guard.write_text(json.dumps({
            "schema_version": 1,
            "guard_id": guard_id,
            "owner_session": "dead-parent",
            "operation_id": None,
            "acquired_at": "2000-01-01T00:00:00Z",
        }) + "\n", encoding="utf-8")
        original_replace = os.replace
        nested = []

        def replace_with_contender(source, destination):
            code, payload = lock_command(Namespace(
                action="acquire", root=str(self.temp),
                task_id="00000000-0000-0000-0000-000000000759", role="explorer",
                workspace_id=None, owner="new-parent",
                operation_id="00000000-0000-0000-0000-000000000760",
                reason=None, guard_id=None, force_stale=False, stale_after_seconds=300,
            ))
            nested.append((code, payload))
            return original_replace(source, destination)

        args = Namespace(
            action="recover-guard", root=str(self.temp), task_id=None, role=None,
            workspace_id=None, owner="recovery-operator", operation_id=None,
            reason="atomic claim test", guard_id=guard_id,
            force_stale=False, stale_after_seconds=300,
        )
        with mock.patch("workflow_core.locking.os.replace", side_effect=replace_with_contender):
            code, payload = lock_command(args)
        self.assertEqual(code, 0, payload)
        self.assertEqual(nested[0][0], 4)
        self.assertEqual(nested[0][1]["error"], "lock_mutation_busy")

    def test_lock_recovery_audit_is_written_only_after_lock_cas(self):
        task_id = "00000000-0000-0000-0000-000000000733"
        operation_id = "00000000-0000-0000-0000-000000000734"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--owner", "owner-a",
            "--operation-id", operation_id,
        )
        args = Namespace(
            action="recover", root=str(self.temp), task_id=task_id, role="builder",
            workspace_id=None, owner="operator-a", operation_id=operation_id,
            reason="CAS failure test", force_stale=True, stale_after_seconds=300,
        )
        with mock.patch("workflow_core.locking._write_lock", side_effect=RuntimeError("lock revision conflict")), mock.patch(
            "workflow_core.locking._audit"
        ) as audit:
            code, payload = lock_command(args)
        self.assertEqual(code, 4, payload)
        self.assertEqual(payload["error"], "lock_revision_conflict")
        audit.assert_not_called()

    def test_project_wrapper_uses_bundled_runtime_import_path(self):
        wrapper = self.temp / "work-flow" / "scripts" / "workflow.py"
        result = subprocess.run(
            [sys.executable, str(wrapper), "route", "--root", str(self.temp), "--kind", "code", "--json"],
            cwd=self.temp,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["requested_model"], "gpt-5.6-terra")

    def test_validating_transition_requires_recorded_validation_evidence(self):
        task_id = "00000000-0000-0000-0000-000000000611"
        operation_id = "00000000-0000-0000-0000-000000000612"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        added = cli(
            self.temp, "task", "add", "--root", str(self.temp), "--task-id", task_id,
            "--title", "Evidence Gate", "--kind", "code", "--level", "L1",
            "--expected-revision", "0", "--operation-id", operation_id,
        )
        implementing = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "implementing", "--expected-revision", str(added["state"]["revision"]),
            "--operation-id", operation_id,
        )
        blocked = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "validating", "--expected-revision", str(implementing["state"]["revision"]),
            "--operation-id", operation_id, expect=2,
        )
        self.assertEqual(blocked["error"], "validation_evidence_required")
        invalid_evidence = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "validating", "--validation-evidence", "unit tests: exit 0",
            "--expected-revision", str(implementing["state"]["revision"]),
            "--operation-id", operation_id, expect=2,
        )
        self.assertEqual(invalid_evidence["error"], "validation_evidence_ref_invalid")
        failed_evidence = self.temp / f"work-flow/docs/evidence/{task_id}-failed.md"
        failed_evidence.write_text(f"task_id: {task_id}\nvalidation: failed\n", encoding="utf-8")
        failed = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "validating", "--validation-evidence", failed_evidence.relative_to(self.temp).as_posix(),
            "--expected-revision", str(implementing["state"]["revision"]),
            "--operation-id", operation_id, expect=2,
        )
        self.assertEqual(failed["error"], "validation_evidence_not_passed")
        evidence = self.temp / f"work-flow/docs/evidence/{task_id}-validation.md"
        evidence.write_text(f"task_id: {task_id}\nvalidation: passed\n", encoding="utf-8")
        validating = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "validating", "--validation-evidence", evidence.relative_to(self.temp).as_posix(),
            "--expected-revision", str(implementing["state"]["revision"]),
            "--operation-id", operation_id,
        )
        revision = validating["state"]["revision"]
        transitioned = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "reporting", "--expected-revision", str(revision), "--operation-id", operation_id,
        )
        revision = transitioned["state"]["revision"]
        missing_result = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "complete", "--expected-revision", str(revision),
            "--operation-id", operation_id, expect=2,
        )
        self.assertEqual(missing_result["error"], "result_ref_required")

    def test_archive_uses_display_name_and_rolls_back_on_stale_revision(self):
        task_id = "00000000-0000-0000-0000-000000000601"
        operation_id = "00000000-0000-0000-0000-000000000602"
        cli(
            self.temp, "lock", "acquire", "--root", str(self.temp),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        state = cli(
            self.temp, "task", "add", "--root", str(self.temp), "--task-id", task_id,
            "--title", "Archive Display Name", "--kind", "code", "--level", "L1",
            "--expected-revision", "0", "--operation-id", operation_id,
        )
        revision = state["state"]["revision"]
        state = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "implementing", "--expected-revision", str(revision), "--operation-id", operation_id,
        )
        revision = state["state"]["revision"]
        archive_evidence = self.temp / "work-flow/docs/evidence/archive-validation.md"
        archive_evidence.write_text(f"task_id: {task_id}\nvalidation: passed\n", encoding="utf-8")
        state = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "validating", "--validation-evidence", "work-flow/docs/evidence/archive-validation.md",
            "--expected-revision", str(revision), "--operation-id", operation_id,
        )
        revision = state["state"]["revision"]
        state = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "reporting", "--expected-revision", str(revision), "--operation-id", operation_id,
        )
        revision = state["state"]["revision"]
        result = self.temp / "work-flow/docs/requirements/0000_Archive-Display-Name_L1/result.md"
        result.parent.mkdir(parents=True)
        result.write_text(
            f"---\ntask_id: {task_id}\ndisplay_seq: 0000\nlevel: L1\n---\n\n# Result\n",
            encoding="utf-8",
        )
        state = cli(
            self.temp, "transition", "--root", str(self.temp), "--task-id", task_id,
            "--to", "complete", "--result-ref", result.relative_to(self.temp).as_posix(),
            "--expected-revision", str(revision), "--operation-id", operation_id,
        )
        revision = state["state"]["revision"]
        stale = cli(
            self.temp, "archive", "--root", str(self.temp), "--task-id", task_id,
            "--expected-revision", "0", "--operation-id", operation_id, expect=4,
        )
        self.assertEqual(stale["error"], "revision_conflict")
        self.assertFalse((self.temp / "work-flow/docs/archive/2026.md").exists())
        self.assertTrue(result.exists())
        archived = cli(
            self.temp, "archive", "--root", str(self.temp), "--task-id", task_id,
            "--expected-revision", str(revision), "--operation-id", operation_id,
        )
        archived_result = Path(archived["result"])
        self.assertEqual(archived_result, result)
        self.assertTrue(archived_result.exists())
        self.assertEqual(archived_result.parent.name, "0000_Archive-Display-Name_L1")
        self.assertIn(f"task_id: {task_id}", archived_result.read_text(encoding="utf-8"))
        completed = archived["state"]["completed_tasks"][task_id]
        self.assertEqual(completed["final_status"], "complete")
        self.assertEqual(completed["result_sha256"], sha256_bytes(result.read_bytes()))
        self.assertEqual(completed["validation"][0]["status"], "passed")
        self.assertTrue(cli(self.temp, "validate", "--root", str(self.temp), "--strict")["valid"])


if __name__ == "__main__":
    unittest.main()
