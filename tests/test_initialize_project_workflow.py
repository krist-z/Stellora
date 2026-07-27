import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "initialize-project-workflow"
CLI = SKILL_ROOT / "scripts" / "workflow_cli.py"


def remove_readonly(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path):
    shutil.rmtree(path, onexc=remove_readonly)


def run_cli(*args, env=None, expect=0):
    cmd = [sys.executable, str(CLI), *args, "--json"]
    merged_env = os.environ.copy()
    merged_env.setdefault("WORKFLOW_OWNER_ID", "initializer-test-parent")
    if env:
        merged_env.update(env)
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=merged_env,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != expect:
        raise AssertionError(
            f"expected exit {expect}, got {result.returncode}\n"
            f"cmd: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"stdout was not JSON:\n{result.stdout}\nstderr:\n{result.stderr}") from exc
    return payload


class WorkflowInitializerTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="workflow-init-"))

    def tearDown(self):
        if self.root.exists():
            remove_tree(self.root)

    def write(self, relative, text, encoding="utf-8"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding, newline="")
        return path

    def read(self, relative, encoding="utf-8"):
        return (self.root / relative).read_text(encoding=encoding, newline="")

    def dry_run(self, mode="new", root=None):
        root = self.root if root is None else root
        return run_cli("init", "--root", str(root), "--mode", mode, "--dry-run")

    def apply_plan(self, plan, mode="new", root=None, env=None, expect=0):
        root = self.root if root is None else root
        return run_cli(
            "init",
            "--root",
            str(root),
            "--mode",
            mode,
            "--apply",
            "--plan-hash",
            plan["plan_hash"],
            *( ["--confirm-rule-migration"] if plan.get("rule_migration_required") else [] ),
            env=env,
            expect=expect,
        )

    def test_new_init_creates_required_layout_and_validates(self):
        self.write("README.md", "# Example\n")
        self.write("src/app.py", "print('ok')\n")

        plan = self.dry_run("new")
        self.assertEqual(plan["mode"], "new")
        self.assertFalse(plan["scan"]["is_git"])
        self.assertEqual(plan["conflicts"], [])
        self.assertFalse((self.root / "work-flow").exists())

        applied = self.apply_plan(plan, "new")
        self.assertEqual(applied["status"], "applied")
        self.assertTrue(applied["transaction_id"])
        self.assertTrue((self.root / applied["transaction_record"]).is_file())

        required = [
            "AGENTS.md",
            ".gitignore",
            "work-flow/AGENTS.md",
            "work-flow/project_rules.md",
            "work-flow/docs/PROJECT.md",
            "work-flow/config.json",
            "work-flow/config.local.json",
            "work-flow/state.md",
            "work-flow/docs/README.md",
            "work-flow/scripts/Invoke-ProjectWorkflow.ps1",
            "work-flow/scripts/invoke-project-workflow.sh",
            "work-flow/scripts/workflow.py",
            "work-flow/scripts/_runtime/workflow_cli.py",
            "work-flow/scripts/_runtime/runtime-manifest.json",
            "work-flow/scripts/_runtime/workflow_core/scanning.py",
        ]
        for rel in required:
            self.assertTrue((self.root / rel).exists(), rel)

        root_agents = self.read("AGENTS.md")
        self.assertIn("work-flow/AGENTS.md", root_agents)
        self.assertNotIn("work-flow/project_rules.md", root_agents)

        project_rules = self.read("work-flow/project_rules.md")
        self.assertIn("<type>(<scope>): <subject>", project_rules)
        self.assertIn("feat(auth): 增加短信登录", project_rules)
        self.assertIn("一次提交只做一件事", project_rules)
        self.assertIn("`update`、`fix bug`", project_rules)

        project_md = self.read("work-flow/docs/PROJECT.md")
        self.assertIn("README.md", project_md)
        self.assertIn("src/app.py", project_md)
        self.assertIn("未发现/未验证", project_md)
        self.assertNotIn("TODO", project_md)
        self.assertNotIn("TBD", project_md)

        state = self.read("work-flow/state.md")
        self.assertIn("---workflow-state-json-v1---", state)
        self.assertIn("---end-workflow-state-json---", state)

        validation = run_cli("validate", "--root", str(self.root), "--strict")
        self.assertTrue(validation["valid"], validation)

        config = json.loads(self.read("work-flow/config.json"))
        self.assertEqual(len(config["runtime_manifest_sha256"]), 64)
        self.assertEqual(
            set(config["template_baselines"]),
            {"work-flow/AGENTS.md", "work-flow/project_rules.md"},
        )

    def test_unicode_path_and_git_detection(self):
        unicode_parent = Path(tempfile.mkdtemp(prefix="workflow-unicode-"))
        unicode_root = unicode_parent / "项目 空间"
        unicode_root.mkdir(parents=True)
        try:
            subprocess.run(["git", "init", str(unicode_root)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (unicode_root / "README.md").write_text("# 名称\n", encoding="utf-8")
            plan = self.dry_run("adopt", unicode_root)
            self.assertTrue(plan["scan"]["is_git"])
            self.apply_plan(plan, "adopt", unicode_root)
            inspected = run_cli("inspect", "--root", str(unicode_root))
            self.assertTrue(inspected["scan"]["is_git"])
            self.assertEqual(Path(inspected["normalized_root"]), unicode_root.resolve())
        finally:
            if unicode_parent.exists():
                remove_tree(unicode_parent)

    def test_dry_run_writes_nothing_and_stale_hash_fails(self):
        plan = self.dry_run("new")
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertFalse((self.root / "work-flow").exists())

        self.write("README.md", "# changed after plan\n")
        failure = self.apply_plan(plan, "new", expect=2)
        self.assertEqual(failure["error"], "plan_hash_mismatch")
        self.assertFalse((self.root / "work-flow").exists())

    def test_adopt_preserves_existing_project_tree_bytes(self):
        originals = {
            "src/app.py": b"print('source')\n",
            "tests/test_app.py": b"def test_app():\n    assert True\n",
            "docs/legacy.md": "# 原有文档\n".encode("utf-8"),
            "scripts/build.ps1": b"Write-Output build\n",
            "package.json": b'{"scripts":{"test":"node test.js"}}\n',
        }
        for relative, content in originals.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        plan = self.dry_run("adopt")
        self.apply_plan(plan, "adopt")
        for relative, content in originals.items():
            self.assertEqual((self.root / relative).read_bytes(), content, relative)

    def test_adopt_does_not_reset_or_clean_dirty_git_files(self):
        subprocess.run(["git", "init", str(self.root)], check=True, capture_output=True)
        tracked = self.write("src/tracked.py", "print('base')\n")
        subprocess.run(["git", "-C", str(self.root), "add", "src/tracked.py"], check=True)
        subprocess.run([
            "git", "-C", str(self.root), "-c", "user.name=Workflow Test",
            "-c", "user.email=workflow@example.invalid", "commit", "-m", "base",
        ], check=True, capture_output=True)
        tracked.write_text("print('dirty')\n", encoding="utf-8")
        untracked = self.write("src/untracked.py", "print('untracked')\n")
        before = subprocess.run(
            ["git", "-C", str(self.root), "status", "--porcelain", "--", "src"],
            check=True, text=True, encoding="utf-8", capture_output=True,
        ).stdout
        plan = self.dry_run("adopt")
        self.apply_plan(plan, "adopt")
        after = subprocess.run(
            ["git", "-C", str(self.root), "status", "--porcelain", "--", "src"],
            check=True, text=True, encoding="utf-8", capture_output=True,
        ).stdout
        self.assertEqual(after, before)
        self.assertEqual(tracked.read_text(encoding="utf-8"), "print('dirty')\n")
        self.assertEqual(untracked.read_text(encoding="utf-8"), "print('untracked')\n")

    def test_idempotency_and_gitignore_preservation(self):
        self.write(".gitignore", "dist/\n# keep me\n")
        plan = self.dry_run("new")
        self.apply_plan(plan, "new")
        first_agents = self.read("AGENTS.md")
        first_gitignore = self.read(".gitignore")

        second_plan = self.dry_run("new")
        self.apply_plan(second_plan, "new")
        self.assertEqual(self.read("AGENTS.md"), first_agents)
        self.assertEqual(self.read(".gitignore"), first_gitignore)
        self.assertEqual(self.read(".gitignore").count("work-flow/.runtime/"), 1)
        self.assertEqual(self.read(".gitignore").count("work-flow/config.local.json"), 1)
        self.assertTrue(self.read(".gitignore").startswith("dist/\n# keep me\n"))

    def test_repeated_init_preserves_nonempty_machine_state(self):
        first_plan = self.dry_run("new")
        self.apply_plan(first_plan, "new")
        task_id = "00000000-0000-0000-0000-000000000811"
        operation_id = "00000000-0000-0000-0000-000000000812"
        run_cli(
            "lock", "acquire", "--root", str(self.root),
            "--task-id", task_id, "--role", "builder", "--operation-id", operation_id,
        )
        run_cli(
            "task", "add", "--root", str(self.root), "--task-id", task_id,
            "--title", "Preserve active state", "--kind", "code", "--level", "L2",
            "--expected-revision", "0", "--operation-id", operation_id,
        )
        run_cli(
            "lock", "release", "--root", str(self.root), "--operation-id", operation_id,
        )
        before = (self.root / "work-flow/state.md").read_bytes()

        second_plan = self.dry_run("new")
        state_action = next(action for action in second_plan["actions"] if action["path"] == "work-flow/state.md")
        self.assertEqual(state_action["kind"], "up_to_date")
        self.apply_plan(second_plan, "new")
        self.assertEqual((self.root / "work-flow/state.md").read_bytes(), before)
        state = run_cli("state", "read", "--root", str(self.root))["state"]
        self.assertEqual(state["revision"], 1)
        self.assertIn(task_id, state["tasks"])

    def test_adopt_migrates_existing_rules_verbatim_and_backs_them_up(self):
        agents = "# Existing Agent Rules\r\nKeep 中文 and punctuation.\r\nLine three.\r\n"
        rules = "# Existing Project Rules\nDo the local thing exactly.\n"
        self.write("AGENTS.md", agents)
        self.write("project_rules.md", rules)

        plan = self.dry_run("adopt")
        self.assertTrue(any(action["kind"] == "backup" for action in plan["actions"]))
        self.apply_plan(plan, "adopt")

        self.assertNotIn(agents, self.read("AGENTS.md"))
        self.assertIn(agents, self.read("work-flow/AGENTS.md"))
        self.assertIn(rules, self.read("work-flow/project_rules.md"))
        self.assertFalse((self.root / "project_rules.md").exists())
        backups = sorted((self.root / "work-flow/.runtime/migration-backups").glob("*"))
        backup_texts = [path.read_text(encoding="utf-8", newline="") for path in backups]
        self.assertIn(agents, backup_texts)
        self.assertIn(rules, backup_texts)

    def test_contradictory_legacy_subagent_rule_blocks_apply(self):
        self.write("AGENTS.md", "Only spawn subagents when explicitly asked by the user.\n")
        plan = self.dry_run("adopt")
        self.assertEqual(plan["conflicts"][0]["code"], "contradictory_legacy_subagent_rule")
        failure = self.apply_plan(plan, "adopt", expect=2)
        self.assertEqual(failure["error"], "unresolved_conflicts")
        self.assertEqual(self.read("AGENTS.md"), "Only spawn subagents when explicitly asked by the user.\n")

    def test_chinese_explicit_only_subagent_rule_blocks_apply(self):
        original = "# Rules\n只有用户明确要求并行代理或委派时，才启动多代理。\n"
        self.write("AGENTS.md", original)
        plan = self.dry_run("adopt")
        self.assertIn("contradictory_legacy_subagent_rule", {item["code"] for item in plan["conflicts"]})
        failure = self.apply_plan(plan, "adopt", expect=2)
        self.assertEqual(failure["error"], "unresolved_conflicts")
        self.assertEqual(self.read("AGENTS.md"), original)

    def test_rollback_injection_restores_replaced_files(self):
        original = "# Existing Rules\nPreserve this if apply fails.\n"
        self.write("AGENTS.md", original)
        plan = self.dry_run("adopt")
        failure = self.apply_plan(
            plan,
            "adopt",
            env={"WORKFLOW_CORE_FAIL_AFTER_ACTION": "2"},
            expect=5,
        )
        self.assertEqual(failure["error"], "transaction_failed")
        self.assertEqual(self.read("AGENTS.md"), original)
        self.assertFalse((self.root / "work-flow/config.json").exists())

    def test_rollback_restores_migrated_root_project_rules_after_delete(self):
        rules = "# Root project rules\nPreserve this through rollback.\n"
        self.write("project_rules.md", rules)
        plan = self.dry_run("adopt")
        change_count = sum(action["kind"] != "up_to_date" for action in plan["actions"])
        failure = self.apply_plan(
            plan,
            "adopt",
            env={"WORKFLOW_CORE_FAIL_AFTER_ACTION": str(change_count)},
            expect=5,
        )
        self.assertEqual(failure["error"], "transaction_failed")
        self.assertEqual(self.read("project_rules.md"), rules)
        self.assertFalse((self.root / "work-flow/config.json").exists())

    def test_incomplete_rollback_returns_exit_six(self):
        plan = self.dry_run("new")
        failure = self.apply_plan(
            plan,
            "new",
            env={
                "WORKFLOW_CORE_FAIL_AFTER_ACTION": "1",
                "WORKFLOW_CORE_FAIL_ROLLBACK": "1",
            },
            expect=6,
        )
        self.assertEqual(failure["error"], "transaction_failed")
        self.assertIn("rollback failed", failure["message"])
        recovery = self.root / failure["recovery_path"]
        self.assertTrue(recovery.is_dir(), failure)
        manifest = json.loads((recovery / "recovery-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "rollback_incomplete")
        self.assertTrue(manifest["files"])
        record = self.root / failure["transaction_record"]
        record_payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(record_payload["status"], "rollback_incomplete")
        self.assertEqual(record_payload["recovery_path"], failure["recovery_path"])

    def test_validate_strict_rejects_path_escape_in_config(self):
        plan = self.dry_run("new")
        self.apply_plan(plan, "new")
        config_path = self.root / "work-flow/config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["managed_files"].append("../escape.md")
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        validation = run_cli("validate", "--root", str(self.root), "--strict", expect=2)
        self.assertFalse(validation["valid"])
        self.assertIn("path_escape", {issue["code"] for issue in validation["issues"]})

    def test_validate_strict_rejects_wrong_hard_route_and_root_pointer(self):
        plan = self.dry_run("new")
        self.apply_plan(plan, "new")
        config_path = self.root / "work-flow/config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["routing_policy"]["code"]["model"] = "gpt-5.6-sol"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.root / "AGENTS.md").write_text("# unmanaged\n", encoding="utf-8")

        validation = run_cli("validate", "--root", str(self.root), "--strict", expect=2)
        codes = {item["code"] for item in validation["issues"]}
        self.assertIn("config_route_mismatch", codes)
        self.assertIn("root_agents_pointer_invalid", codes)

    def test_runtime_is_self_contained_and_upgrade_preserves_project_facts(self):
        legacy = "# Legacy\nUse existing naming.\n"
        self.write("AGENTS.md", legacy)
        self.write("package.json", '{"scripts":{"test":"node test.js"}}\n')
        plan = self.dry_run("adopt")
        self.apply_plan(plan, "adopt")

        project_path = self.root / "work-flow/docs/PROJECT.md"
        project_before = project_path.read_text(encoding="utf-8")
        project_path.write_text(project_before + "\nCustom fact: keep this.\n", encoding="utf-8")
        local_config = self.root / "work-flow/config.local.json"
        local_config.write_text('{"machine":"keep-local"}\n', encoding="utf-8")
        agents_before = self.read("AGENTS.md")

        upgrade_plan = run_cli("upgrade", "--root", str(self.root), "--dry-run")
        self.assertEqual(upgrade_plan["conflicts"], [])
        applied = run_cli(
            "upgrade",
            "--root",
            str(self.root),
            "--apply",
            "--plan-hash",
            upgrade_plan["plan_hash"],
        )
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(project_path.read_text(encoding="utf-8"), project_before + "\nCustom fact: keep this.\n")
        self.assertEqual(local_config.read_text(encoding="utf-8"), '{"machine":"keep-local"}\n')
        self.assertNotIn(legacy, self.read("AGENTS.md"))
        self.assertIn("Imported Existing Rules", self.read("work-flow/AGENTS.md"))

        runtime_files = list((self.root / "work-flow/scripts/_runtime").rglob("*.py"))
        self.assertTrue(runtime_files)
        for runtime_file in runtime_files:
            text = runtime_file.read_text(encoding="utf-8")
            self.assertNotIn("F:\\work-flow", text)
            self.assertNotIn("CODEX_HOME", text)

        validation = run_cli("validate", "--root", str(self.root), "--strict")
        self.assertTrue(validation["valid"], validation)

    def test_upgrade_repairs_missing_safe_control_files_and_preserves_state_bytes(self):
        plan = self.dry_run("new")
        self.apply_plan(plan, "new")
        state_path = self.root / "work-flow/state.md"
        state_before = state_path.read_bytes()
        for rel in (
            ".gitignore",
            "work-flow/.runtime/operation-lock.json",
            "work-flow/docs/evidence/.gitkeep",
        ):
            (self.root / rel).unlink()

        upgrade_plan = run_cli("upgrade", "--root", str(self.root), "--dry-run")
        actions = {item["path"]: item["kind"] for item in upgrade_plan["actions"]}
        self.assertEqual(actions[".gitignore"], "write")
        self.assertEqual(actions["work-flow/.runtime/operation-lock.json"], "write")
        self.assertEqual(actions["work-flow/docs/evidence/.gitkeep"], "write")
        applied = run_cli(
            "upgrade", "--root", str(self.root), "--apply", "--plan-hash", upgrade_plan["plan_hash"]
        )
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(state_path.read_bytes(), state_before)
        validation = run_cli("validate", "--root", str(self.root), "--strict")
        self.assertTrue(validation["valid"], validation)

    def test_upgrade_refuses_missing_state_instead_of_reinitializing_it(self):
        plan = self.dry_run("new")
        self.apply_plan(plan, "new")
        (self.root / "work-flow/state.md").unlink()
        failure = run_cli("upgrade", "--root", str(self.root), "--dry-run", expect=2)
        self.assertIn("manual recovery required", failure["message"])
        self.assertFalse((self.root / "work-flow/state.md").exists())

    def test_registered_schema_zero_to_one_migration_and_stale_state_hash(self):
        plan = self.dry_run("new")
        self.apply_plan(plan, "new")
        config_path = self.root / "work-flow/config.json"
        state_path = self.root / "work-flow/state.md"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["schema_version"] = 0
        config["routing_policy"].pop("reporter", None)
        config_path.write_text(json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        state_text = state_path.read_text(encoding="utf-8")
        start = state_text.index("---workflow-state-json-v1---") + len("---workflow-state-json-v1---")
        end = state_text.index("---end-workflow-state-json---")
        state = json.loads(state_text[start:end].strip())
        state["schema_version"] = 0
        state["revision"] = 9
        state["legacy_marker"] = "preserve-me"
        state_path.write_text(
            "# Workflow State\n\n---workflow-state-json-v1---\n"
            + json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n---end-workflow-state-json---\n",
            encoding="utf-8",
        )

        migration_plan = run_cli("upgrade", "--root", str(self.root), "--dry-run")
        self.assertEqual(migration_plan["migration_chain"], ["workflow-schema-0-to-1"])
        stale_state = state_path.read_text(encoding="utf-8") + "\n"
        state_path.write_text(stale_state, encoding="utf-8")
        stale = run_cli(
            "upgrade", "--root", str(self.root), "--apply", "--plan-hash", migration_plan["plan_hash"],
            expect=2,
        )
        self.assertEqual(stale["error"], "plan_hash_mismatch")
        state_path.write_text(stale_state.rstrip("\n") + "\n", encoding="utf-8")

        migration_plan = run_cli("upgrade", "--root", str(self.root), "--dry-run")
        applied = run_cli(
            "upgrade", "--root", str(self.root), "--apply", "--plan-hash", migration_plan["plan_hash"]
        )
        self.assertEqual(applied["status"], "applied")
        migrated = state_path.read_text(encoding="utf-8")
        migrated_data = json.loads(
            migrated[migrated.index("---workflow-state-json-v1---") + len("---workflow-state-json-v1---"):migrated.index("---end-workflow-state-json---")].strip()
        )
        self.assertEqual(migrated_data["schema_version"], 1)
        self.assertEqual(migrated_data["revision"], 9)
        self.assertEqual(migrated_data["legacy_marker"], "preserve-me")
        self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["routing_policy"]["reporter"]["model"], "gpt-5.6-luna")
        backups = list((self.root / "work-flow/.runtime/migration-backups").glob("workflow-schema-0-to-1-*-*"))
        self.assertGreaterEqual(len(backups), 2)
        self.assertTrue(run_cli("validate", "--root", str(self.root), "--strict")["valid"])

    def test_init_and_upgrade_default_to_dry_run(self):
        before = list(self.root.rglob("*"))
        init_plan = run_cli("init", "--root", str(self.root), "--mode", "new")
        self.assertEqual(init_plan["operation"], "init")
        self.assertEqual(list(self.root.rglob("*")), before)
        self.apply_plan(init_plan, "new")
        upgrade_plan = run_cli("upgrade", "--root", str(self.root))
        self.assertEqual(upgrade_plan["operation"], "upgrade")

    def test_same_version_upgrade_is_noop_after_init(self):
        plan = self.dry_run("new")
        self.apply_plan(plan, "new")

        upgrade_plan = run_cli("upgrade", "--root", str(self.root), "--dry-run")

        self.assertEqual(upgrade_plan["migration_chain"], [])
        self.assertEqual(upgrade_plan["conflicts"], [])
        self.assertTrue(upgrade_plan["actions"])
        self.assertEqual(
            {action["kind"] for action in upgrade_plan["actions"]},
            {"up_to_date"},
        )

    def test_upgrade_preserves_customized_managed_rule_files(self):
        plan = self.dry_run("new")
        self.apply_plan(plan, "new")
        workflow_agents = self.root / "work-flow/AGENTS.md"
        workflow_rules = self.root / "work-flow/project_rules.md"
        agents_custom = workflow_agents.read_text(encoding="utf-8") + "\n## Local extension\nKeep this exact rule.\n"
        rules_custom = workflow_rules.read_text(encoding="utf-8") + "\n## Local security exception\nReview manually.\n"
        workflow_agents.write_text(agents_custom, encoding="utf-8")
        workflow_rules.write_text(rules_custom, encoding="utf-8")

        upgrade_plan = run_cli("upgrade", "--root", str(self.root), "--dry-run")
        self.assertEqual(set(upgrade_plan["preserved_customizations"]), {"work-flow/AGENTS.md", "work-flow/project_rules.md"})
        applied = run_cli(
            "upgrade", "--root", str(self.root), "--apply", "--plan-hash", upgrade_plan["plan_hash"]
        )
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(workflow_agents.read_text(encoding="utf-8"), agents_custom)
        self.assertEqual(workflow_rules.read_text(encoding="utf-8"), rules_custom)

    def test_strict_validation_rejects_runtime_manifest_drift_and_upgrade_repairs_it(self):
        plan = self.dry_run("new")
        self.apply_plan(plan, "new")
        runtime_file = self.root / "work-flow/scripts/_runtime/workflow_core/routing.py"
        runtime_file.write_text(runtime_file.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

        invalid = run_cli("validate", "--root", str(self.root), "--strict", expect=2)
        self.assertFalse(invalid["valid"])
        self.assertIn("runtime_manifest_hash_mismatch", {item["code"] for item in invalid["issues"]})

        upgrade = run_cli("upgrade", "--root", str(self.root), "--dry-run")
        applied = run_cli(
            "upgrade", "--root", str(self.root), "--apply", "--plan-hash", upgrade["plan_hash"]
        )
        self.assertEqual(applied["status"], "applied")
        self.assertTrue(run_cli("validate", "--root", str(self.root), "--strict")["valid"])

    def test_upgrade_distinguishes_legacy_template_baseline_from_customization(self):
        plan = self.dry_run("new")
        self.apply_plan(plan, "new")
        rules_path = self.root / "work-flow/project_rules.md"
        bundled_template = self.root / "work-flow/scripts/_runtime/assets/project-template/work-flow/project_rules.md.tpl"
        current_rules = rules_path.read_text(encoding="utf-8")
        current_template = bundled_template.read_text(encoding="utf-8")
        rules_cut = current_rules.index("## Git ")
        template_cut = current_template.index("## Git ")
        legacy_rules = (
            current_rules[:rules_cut]
            + "<!-- workflow-managed:project-rules:v1 -->\n\n"
            + "## Local extension\nKeep this project rule.\n"
        )
        legacy_template = (
            current_template[:template_cut]
            + "<!-- workflow-managed:project-rules:v1 -->\n{{IMPORTED_PROJECT_RULES}}\n"
        )
        rules_path.write_text(legacy_rules, encoding="utf-8")
        bundled_template.write_text(legacy_template, encoding="utf-8")
        config_path = self.root / "work-flow/config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.pop("template_baselines", None)
        config.pop("runtime_manifest_sha256", None)
        config["runtime_version"] = "1.0.0"
        config_path.write_text(json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (self.root / "work-flow/scripts/_runtime/runtime-manifest.json").unlink()
        state_path = self.root / "work-flow/state.md"
        state_text = state_path.read_text(encoding="utf-8")
        state_start = state_text.index("---workflow-state-json-v1---") + len("---workflow-state-json-v1---")
        state_end = state_text.index("---end-workflow-state-json---")
        state = json.loads(state_text[state_start:state_end].strip())
        old_revision = state["revision"]
        state["runtime_version"] = "1.0.0"
        state_path.write_text(
            "# Workflow State\n\n---workflow-state-json-v1---\n"
            + json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n---end-workflow-state-json---\n",
            encoding="utf-8",
        )

        upgrade = run_cli("upgrade", "--root", str(self.root), "--dry-run")
        self.assertNotIn("work-flow/project_rules.md", upgrade["preserved_customizations"])
        self.assertIn("work-flow/project_rules.md", upgrade["merged_customizations"])
        actions = {item["path"]: item["kind"] for item in upgrade["actions"]}
        self.assertEqual(actions["work-flow/project_rules.md"], "write")
        applied = run_cli(
            "upgrade", "--root", str(self.root), "--apply", "--plan-hash", upgrade["plan_hash"]
        )
        self.assertEqual(applied["status"], "applied")
        self.assertIn("<type>(<scope>): <subject>", rules_path.read_text(encoding="utf-8"))
        self.assertIn("Keep this project rule.", rules_path.read_text(encoding="utf-8"))
        upgraded_state = state_path.read_text(encoding="utf-8")
        upgraded = json.loads(upgraded_state[
            upgraded_state.index("---workflow-state-json-v1---") + len("---workflow-state-json-v1---"):
            upgraded_state.index("---end-workflow-state-json---")
        ].strip())
        self.assertEqual(upgraded["revision"], old_revision + 1)
        self.assertTrue(run_cli("validate", "--root", str(self.root), "--strict")["valid"])


if __name__ == "__main__":
    unittest.main()
