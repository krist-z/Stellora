import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "initialize-project-workflow" / "scripts" / "workflow_cli.py"
sys.path.insert(0, str(CLI.parent))

from workflow_core.schema import sha256_bytes, workspace_identity
from workflow_core.transactions import FileChange, TransactionError, apply_file_changes
from workflow_core.workers import build_worker_command
from workflow_core.workers import worker_command
from workflow_core.routing import resolve_route


def cli(root, *args, expect=0):
    result = subprocess.run(
        [sys.executable, str(CLI), *args, "--json"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode != expect:
        raise AssertionError(
            f"expected {expect}, got {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return json.loads(result.stdout)


class WorkflowP1ContractsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="workflow-p1-"))
        plan = cli(self.root, "init", "--root", str(self.root), "--mode", "new", "--dry-run")
        cli(
            self.root,
            "init", "--root", str(self.root), "--mode", "new", "--apply",
            "--plan-hash", plan["plan_hash"],
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _acquire(self, task_id, operation_id, role="builder", owner="parent-session"):
        return cli(
            self.root,
            "lock", "acquire", "--root", str(self.root), "--task-id", task_id,
            "--role", role, "--operation-id", operation_id, "--owner", owner,
        )

    def test_l1_uses_direct_validating_to_reporting_transition(self):
        task_id = "00000000-0000-0000-0000-000000001001"
        operation_id = "00000000-0000-0000-0000-000000001002"
        self._acquire(task_id, operation_id)
        state = cli(
            self.root, "task", "add", "--root", str(self.root), "--task-id", task_id,
            "--title", "L1 direct chain", "--kind", "code", "--level", "L1",
            "--expected-revision", "0", "--operation-id", operation_id,
        )["state"]
        state = cli(
            self.root, "transition", "--root", str(self.root), "--task-id", task_id,
            "--to", "implementing", "--expected-revision", str(state["revision"]),
            "--operation-id", operation_id,
        )["state"]
        evidence = self.root / "work-flow/docs/evidence/l1-validation.md"
        evidence.write_text(f"task_id: {task_id}\nvalidation: passed\n", encoding="utf-8")
        state = cli(
            self.root, "transition", "--root", str(self.root), "--task-id", task_id,
            "--to", "validating", "--validation-evidence", "work-flow/docs/evidence/l1-validation.md",
            "--expected-revision", str(state["revision"]), "--operation-id", operation_id,
        )["state"]
        reporting = cli(
            self.root, "transition", "--root", str(self.root), "--task-id", task_id,
            "--to", "reporting", "--expected-revision", str(state["revision"]),
            "--operation-id", operation_id,
        )
        self.assertEqual(reporting["task"]["phase"], "reporting")

    def test_repeated_init_refuses_missing_corrupt_or_future_state(self):
        state_path = self.root / "work-flow/state.md"
        original = state_path.read_bytes()
        cases = [
            (None, "missing"),
            (b"corrupt\n", "invalid"),
            (original.replace(b'"schema_version": 1', b'"schema_version": 99'), "unsupported"),
        ]
        for content, _label in cases:
            with self.subTest(label=_label):
                if content is None:
                    state_path.unlink(missing_ok=True)
                else:
                    state_path.write_bytes(content)
                failure = cli(
                    self.root, "init", "--root", str(self.root), "--mode", "new", "--dry-run",
                    expect=2,
                )
                self.assertIn("manual recovery required", failure["message"])
                state_path.write_bytes(original)

    def test_repeated_init_refuses_active_or_invalid_operation_lock(self):
        task_id = "00000000-0000-0000-0000-000000001011"
        operation_id = "00000000-0000-0000-0000-000000001012"
        self._acquire(task_id, operation_id)
        active = cli(
            self.root, "init", "--root", str(self.root), "--mode", "new", "--dry-run",
            expect=2,
        )
        self.assertIn("active workflow operation", active["message"])
        lock_path = self.root / "work-flow/.runtime/operation-lock.json"
        lock_path.write_text("{not-json", encoding="utf-8")
        invalid = cli(
            self.root, "init", "--root", str(self.root), "--mode", "new", "--dry-run",
            expect=2,
        )
        self.assertIn("operation lock is invalid", invalid["message"])

    def test_heartbeat_and_release_require_explicit_matching_owner(self):
        task_id = "00000000-0000-0000-0000-000000001021"
        operation_id = "00000000-0000-0000-0000-000000001022"
        self._acquire(task_id, operation_id, owner="owner-a")
        for action in ("heartbeat", "release"):
            with self.subTest(action=action):
                missing = cli(
                    self.root, "lock", action, "--root", str(self.root),
                    "--operation-id", operation_id, expect=2,
                )
                self.assertEqual(missing["error"], "owner_required")
        mismatch = cli(
            self.root, "lock", "release", "--root", str(self.root),
            "--operation-id", operation_id, "--owner", "owner-b", expect=4,
        )
        self.assertEqual(mismatch["error"], "owner_mismatch")
        cli(
            self.root, "lock", "release", "--root", str(self.root),
            "--operation-id", operation_id, "--owner", "owner-a",
        )

    def test_completion_rechecks_recorded_evidence_hash(self):
        task_id = "00000000-0000-0000-0000-000000001031"
        operation_id = "00000000-0000-0000-0000-000000001032"
        self._acquire(task_id, operation_id)
        state = cli(
            self.root, "task", "add", "--root", str(self.root), "--task-id", task_id,
            "--title", "Evidence CAS", "--kind", "code", "--level", "L1",
            "--expected-revision", "0", "--operation-id", operation_id,
        )["state"]
        state = cli(
            self.root, "transition", "--root", str(self.root), "--task-id", task_id,
            "--to", "implementing", "--expected-revision", str(state["revision"]),
            "--operation-id", operation_id,
        )["state"]
        evidence = self.root / "work-flow/docs/evidence/hash-validation.md"
        evidence.write_text(f"task_id: {task_id}\nvalidation: passed\n", encoding="utf-8")
        state = cli(
            self.root, "transition", "--root", str(self.root), "--task-id", task_id,
            "--to", "validating", "--validation-evidence", "work-flow/docs/evidence/hash-validation.md",
            "--expected-revision", str(state["revision"]), "--operation-id", operation_id,
        )["state"]
        state = cli(
            self.root, "transition", "--root", str(self.root), "--task-id", task_id,
            "--to", "reporting", "--expected-revision", str(state["revision"]),
            "--operation-id", operation_id,
        )["state"]
        result = self.root / "work-flow/docs/requirements/0000_Evidence-CAS_L1/result.md"
        result.parent.mkdir(parents=True)
        result.write_text(f"task_id: {task_id}\n", encoding="utf-8")
        evidence.write_text(f"task_id: {task_id}\nvalidation: passed\nchanged\n", encoding="utf-8")
        blocked = cli(
            self.root, "transition", "--root", str(self.root), "--task-id", task_id,
            "--to", "complete", "--result-ref", result.relative_to(self.root).as_posix(),
            "--expected-revision", str(state["revision"]), "--operation-id", operation_id,
            expect=2,
        )
        self.assertEqual(blocked["error"], "evidence_changed_since_recorded")

    def test_transaction_rechecks_each_target_immediately_before_write(self):
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        first.write_text("first-before\n", encoding="utf-8")
        second.write_text("second-before\n", encoding="utf-8")
        changes = [
            FileChange("first.txt", b"first-after\n", sha256_bytes(first.read_bytes())),
            FileChange("second.txt", b"second-after\n", sha256_bytes(second.read_bytes())),
        ]
        from workflow_core import transactions
        real_copy = transactions._copy_existing
        calls = 0

        def mutate_after_first_backup(target, backup):
            nonlocal calls
            calls += 1
            result = real_copy(target, backup)
            if calls == 1:
                second.write_text("concurrent-user-edit\n", encoding="utf-8")
            return result

        with mock.patch("workflow_core.transactions._copy_existing", side_effect=mutate_after_first_backup):
            with self.assertRaises(TransactionError) as raised:
                apply_file_changes(self.root, changes)
        self.assertEqual(raised.exception.exit_code, 4)
        self.assertEqual(first.read_text(encoding="utf-8"), "first-before\n")
        self.assertEqual(second.read_text(encoding="utf-8"), "concurrent-user-edit\n")

    def test_committed_audit_failure_rolls_back_changes(self):
        target = self.root / "audit.txt"
        target.write_text("before\n", encoding="utf-8")
        change = FileChange("audit.txt", b"after\n", sha256_bytes(target.read_bytes()))
        from workflow_core import transactions
        real_record = transactions._write_transaction_record

        def fail_commit(*args, **kwargs):
            status = args[2]
            if status == "committed":
                raise OSError("audit storage unavailable")
            return real_record(*args, **kwargs)

        with mock.patch("workflow_core.transactions._write_transaction_record", side_effect=fail_commit):
            with self.assertRaises(TransactionError):
                apply_file_changes(self.root, [change])
        self.assertEqual(target.read_text(encoding="utf-8"), "before\n")

    def test_unresolved_recovery_bundle_blocks_new_transaction(self):
        recovery = self.root / "work-flow/.runtime/transactions/recovery-unresolved"
        recovery.mkdir(parents=True)
        (recovery / "recovery-manifest.json").write_text(
            json.dumps({"schema_version": 1, "status": "rollback_incomplete"}), encoding="utf-8"
        )
        with self.assertRaises(TransactionError) as raised:
            apply_file_changes(self.root, [FileChange("blocked.txt", b"x", None)])
        self.assertEqual(raised.exception.exit_code, 6)
        self.assertFalse((self.root / "blocked.txt").exists())

    def test_schema_migration_backups_preserve_bom_and_crlf_bytes(self):
        config_path = self.root / "work-flow/config.json"
        state_path = self.root / "work-flow/state.md"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["schema_version"] = 0
        config["routing_policy"].pop("reporter", None)
        config_bytes = ("\ufeff" + json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2).replace("\n", "\r\n") + "\r\n").encode("utf-8")
        state_text = state_path.read_text(encoding="utf-8")
        start = state_text.index("---workflow-state-json-v1---") + len("---workflow-state-json-v1---")
        end = state_text.index("---end-workflow-state-json---")
        state = json.loads(state_text[start:end].strip())
        state["schema_version"] = 0
        state_bytes = ("\ufeff# Workflow State\r\n\r\n---workflow-state-json-v1---\r\n"
                       + json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2).replace("\n", "\r\n")
                       + "\r\n---end-workflow-state-json---\r\n").encode("utf-8")
        config_path.write_bytes(config_bytes)
        state_path.write_bytes(state_bytes)
        plan = cli(self.root, "upgrade", "--root", str(self.root), "--dry-run")
        backup_paths = plan["migration"]["backup_paths"]
        cli(
            self.root, "upgrade", "--root", str(self.root), "--apply",
            "--plan-hash", plan["plan_hash"],
        )
        self.assertEqual((self.root / backup_paths["config"]).read_bytes(), config_bytes)
        self.assertEqual((self.root / backup_paths["state"]).read_bytes(), state_bytes)

    def test_non_git_worker_requires_workspace_bound_local_trust_and_disables_delegation(self):
        route = resolve_route("code")
        schema = self.root / "schema.json"
        result = self.root / "result.json"
        with self.assertRaises(ValueError):
            build_worker_command(self.root, route, None, schema, result)
        granted = cli(
            self.root, "trust", "grant-non-git", "--root", str(self.root)
        )
        self.assertEqual(granted["workspace_id"], workspace_identity(self.root))
        self.assertTrue(granted["non_git_trusted"])
        command = build_worker_command(self.root, route, None, schema, result)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--disable", command)
        self.assertEqual(command[command.index("--disable") + 1], "multi_agent")
        self.assertIn("agents.enabled=false", command)

    def test_project_agent_template_requires_full_leaf_identity_and_read_order(self):
        template = (
            ROOT / "skills/initialize-project-workflow/assets/project-template/work-flow/AGENTS.md.tpl"
        ).read_text(encoding="utf-8")
        for required in (
            "work-flow/AGENTS.md", "project_rules.md", "config.json", "state.md",
            "requirement", "evidence", "result", "task ID", "operation ID", "role",
        ):
            self.assertIn(required, template)

    def test_worker_prevalidation_does_not_delete_existing_operation_result(self):
        task_id = "00000000-0000-0000-0000-000000001041"
        operation_id = "00000000-0000-0000-0000-000000001042"
        self._acquire(task_id, operation_id)
        result = self.root / f"work-flow/.runtime/worker-results/{task_id}-{operation_id}.json"
        result.write_bytes(b"existing-parent-result\n")
        args = Namespace(
            root=str(self.root), task_id=task_id, role="builder", operation_id=operation_id,
            expected_revision=0, prompt_file=None, allowed_path=["work-flow"], timeout_seconds=30,
        )
        code, payload = worker_command(args)
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["error"], "allowed_path_protected")
        self.assertEqual(result.read_bytes(), b"existing-parent-result\n")


if __name__ == "__main__":
    unittest.main()
