import argparse
import json
import sys
from pathlib import Path

from workflow_core.initialization import init_apply, init_dry_run
from workflow_core.scanning import scan_project
from workflow_core.schema import normalize_root, pretty_json
from workflow_core.upgrades import upgrade_apply, upgrade_dry_run
from workflow_core.validation import validate_project
from workflow_core.state import state_command
from workflow_core.locking import lock_command
from workflow_core.routing import route_command
from workflow_core.workers import trust_command, worker_command
from workflow_core.archiving import archive_command


class WorkflowArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"error": "invalid_arguments", "message": message}, ensure_ascii=False))
        raise SystemExit(2)


def _source_layout():
    here = Path(__file__).resolve()
    if here.parent.name == "_runtime":
        runtime_root = here.parent / "workflow_core"
        assets_root = here.parent / "assets" / "project-template"
    else:
        runtime_root = here.parent / "workflow_core"
        assets_root = here.parent.parent / "assets" / "project-template"
    return assets_root, runtime_root, here


def _emit(payload, as_json):
    if as_json:
        print(pretty_json(payload), end="")
    else:
        if "error" in payload:
            print(f"error: {payload['error']}")
        elif "plan_hash" in payload:
            print(payload["plan_hash"])
        else:
            print(json.dumps(payload, ensure_ascii=False))


def _add_json(parser):
    parser.add_argument("--json", action="store_true", help="emit JSON")


def build_parser():
    parser = WorkflowArgumentParser(prog="workflow_cli.py")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=WorkflowArgumentParser)

    init = sub.add_parser("init")
    init.add_argument("--root", required=True)
    init.add_argument("--mode", choices=("new", "adopt"), required=True)
    group = init.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    init.add_argument("--plan-hash")
    init.add_argument("--confirm-rule-migration", action="store_true")
    _add_json(init)

    upgrade = sub.add_parser("upgrade")
    upgrade.add_argument("--root", required=True)
    group = upgrade.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    upgrade.add_argument("--plan-hash")
    upgrade.add_argument("--confirm-rule-migration", action="store_true")
    _add_json(upgrade)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--root", required=True)
    _add_json(inspect)

    validate = sub.add_parser("validate")
    validate.add_argument("--root", required=True)
    validate.add_argument("--strict", action="store_true")
    _add_json(validate)

    state = sub.add_parser("state")
    state.add_argument("action", choices=("read", "add", "list", "next-action", "transition"))
    state.add_argument("--root", required=True)
    state.add_argument("--task-id")
    state.add_argument("--title")
    state.add_argument("--kind")
    state.add_argument("--level")
    state.add_argument("--to")
    state.add_argument("--expected-revision", type=int)
    state.add_argument("--operation-id")
    state.add_argument("--intent-hash")
    state.add_argument("--technical-plan-hash")
    state.add_argument("--authorization-id")
    state.add_argument("--batch-task-id", action="append")
    state.add_argument("--risk-confirmation")
    state.add_argument("--rollback-ref")
    state.add_argument("--monitoring-ref")
    state.add_argument("--target-system")
    state.add_argument("--target-environment")
    state.add_argument("--target-object")
    state.add_argument("--backup-ref")
    state.add_argument("--external-write-scope")
    state.add_argument("--stop-condition")
    state.add_argument("--post-action-validation-ref")
    state.add_argument("--audit-result-ref")
    state.add_argument("--requires-confirmation", action="store_true")
    state.add_argument("--confirmation-reason", action="append")
    state.add_argument("--validation-evidence", action="append")
    state.add_argument("--review-evidence", action="append")
    state.add_argument("--result-ref")
    _add_json(state)

    task = sub.add_parser("task")
    task_sub = task.add_subparsers(dest="task_action", required=True)
    for action in ("add", "list"):
        task_cmd = task_sub.add_parser(action)
        task_cmd.add_argument("--root", required=True)
        task_cmd.add_argument("--task-id")
        task_cmd.add_argument("--title")
        task_cmd.add_argument("--kind")
        task_cmd.add_argument("--level")
        task_cmd.add_argument("--expected-revision", type=int)
        task_cmd.add_argument("--operation-id")
        if action == "add":
            task_cmd.add_argument("--requires-confirmation", action="store_true")
            task_cmd.add_argument("--confirmation-reason", action="append")
        _add_json(task_cmd)

    next_action = sub.add_parser("next-action")
    next_action.add_argument("--root", required=True)
    next_action.add_argument("--task-id")
    _add_json(next_action)

    transition = sub.add_parser("transition")
    transition.add_argument("--root", required=True)
    transition.add_argument("--task-id", required=True)
    transition.add_argument("--to", required=True)
    transition.add_argument("--expected-revision", type=int, required=True)
    transition.add_argument("--operation-id", required=True)
    transition.add_argument("--intent-hash")
    transition.add_argument("--technical-plan-hash")
    transition.add_argument("--authorization-id")
    transition.add_argument("--batch-task-id", action="append")
    transition.add_argument("--risk-confirmation")
    transition.add_argument("--rollback-ref")
    transition.add_argument("--monitoring-ref")
    transition.add_argument("--target-system")
    transition.add_argument("--target-environment")
    transition.add_argument("--target-object")
    transition.add_argument("--backup-ref")
    transition.add_argument("--external-write-scope")
    transition.add_argument("--stop-condition")
    transition.add_argument("--post-action-validation-ref")
    transition.add_argument("--audit-result-ref")
    transition.add_argument("--validation-evidence", action="append")
    transition.add_argument("--review-evidence", action="append")
    transition.add_argument("--result-ref")
    _add_json(transition)

    lock = sub.add_parser("lock")
    lock.add_argument("action", choices=("acquire", "heartbeat", "release", "recover"))
    lock.add_argument("--root", required=True)
    lock.add_argument("--task-id")
    lock.add_argument("--role")
    lock.add_argument("--workspace-id")
    lock.add_argument("--owner")
    lock.add_argument("--operation-id")
    lock.add_argument("--reason")
    lock.add_argument("--force-stale", action="store_true", help="explicitly authorize recovery without waiting for heartbeat age")
    lock.add_argument("--stale-after-seconds", type=float, default=300.0, help="heartbeat age required for lock recover")
    _add_json(lock)

    route = sub.add_parser("route")
    route.add_argument("--root", required=True)
    route.add_argument("--kind", required=True)
    _add_json(route)

    worker = sub.add_parser("worker")
    worker.add_argument("action", choices=("run",))
    worker.add_argument("--root", required=True)
    worker.add_argument("--task-id", required=True)
    worker.add_argument("--role", required=True)
    worker.add_argument("--operation-id", required=True)
    worker.add_argument("--expected-revision", type=int, required=True)
    worker.add_argument("--prompt-file")
    worker.add_argument("--allowed-path", action="append")
    worker.add_argument("--timeout-seconds", type=int, default=300)
    _add_json(worker)

    trust = sub.add_parser("trust")
    trust.add_argument("action", choices=("status", "grant-non-git", "revoke-non-git"))
    trust.add_argument("--root", required=True)
    _add_json(trust)

    archive = sub.add_parser("archive")
    archive.add_argument("--root", required=True)
    archive.add_argument("--task-id", required=True)
    archive.add_argument("--expected-revision", type=int, required=True)
    archive.add_argument("--operation-id", required=True)
    _add_json(archive)

    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    assets_root, runtime_root, cli_path = _source_layout()

    try:
        root = normalize_root(args.root)
        if args.command == "init":
            if args.apply and not args.plan_hash:
                payload = {"error": "plan_hash_required", "command": "init"}
                _emit(payload, getattr(args, "json", False)); return 2
            if not args.apply:
                payload = init_dry_run(root, args.mode, assets_root, runtime_root, cli_path)
                code = 0
            else:
                code, payload = init_apply(root, args.mode, args.plan_hash, assets_root, runtime_root, cli_path, confirm_rule_migration=args.confirm_rule_migration)
        elif args.command == "upgrade":
            if args.apply and not args.plan_hash:
                payload = {"error": "plan_hash_required", "command": "upgrade"}
                _emit(payload, getattr(args, "json", False)); return 2
            if not args.apply:
                payload = upgrade_dry_run(root, assets_root, runtime_root, cli_path)
                code = 0
            else:
                code, payload = upgrade_apply(root, args.plan_hash, assets_root, runtime_root, cli_path, confirm_rule_migration=args.confirm_rule_migration)
        elif args.command == "inspect":
            validation = validate_project(root, strict=False)
            payload = {
                "normalized_root": str(root),
                "initialized": (root / "work-flow/config.json").exists(),
                "scan": scan_project(root),
                "validation": validation,
            }
            code = 0
        elif args.command == "validate":
            payload = validate_project(root, strict=args.strict)
            code = 0 if payload["valid"] else 2
        elif args.command == "state":
            code, payload = state_command(args)
        elif args.command == "task":
            args.action = args.task_action
            code, payload = state_command(args)
        elif args.command == "next-action":
            args.action = "next-action"
            code, payload = state_command(args)
        elif args.command == "transition":
            args.action = "transition"
            code, payload = state_command(args)
        elif args.command == "lock":
            code, payload = lock_command(args)
        elif args.command == "route":
            code, payload = route_command(args)
        elif args.command == "worker":
            code, payload = worker_command(args)
        elif args.command == "trust":
            code, payload = trust_command(args)
        elif args.command == "archive":
            code, payload = archive_command(args)
        else:
            parser.error("unknown command")
    except ValueError as exc:
        payload = {"error": "invalid_request", "message": str(exc)}
        code = 2
    except Exception as exc:
        payload = {"error": "internal_error", "message": str(exc)}
        code = 10

    _emit(payload, getattr(args, "json", False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
