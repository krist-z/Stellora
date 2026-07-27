from pathlib import PurePosixPath


SCHEMA_VERSION = 1
RUNTIME_VERSION = "1.1.0"
TEMPLATE_VERSION = "1.0.0"

STATE_START = "---workflow-state-json-v1---"
STATE_END = "---end-workflow-state-json---"

IGNORE_ENTRIES = ("work-flow/.runtime/", "work-flow/config.local.json")

MANAGED_MARKERS = (
    "<!-- workflow-managed:root-agents:v1 -->",
    "<!-- workflow-managed:work-flow-agents:v1 -->",
    "<!-- workflow-managed:project-rules:v1 -->",
)

IMPORT_START_PREFIX = "<!-- workflow-imported-rules:start:"
IMPORT_END_PREFIX = "<!-- workflow-imported-rules:end:"

CONFLICT_SUBAGENT_RULES = (
    "only spawn subagents when explicitly asked",
    "only spawn sub-agents when explicitly asked",
    "只有用户明确要求并行代理或委派时，才启动多代理",
    "只有用户明确要求并行 agent、子 agent 或多 agent 执行时，才拆分代理",
    "只有用户明确要求才能使用子 agent",
)

STATIC_REQUIRED_FILES = (
    "AGENTS.md",
    ".gitignore",
    "work-flow/AGENTS.md",
    "work-flow/project_rules.md",
    "work-flow/docs/PROJECT.md",
    "work-flow/config.json",
    "work-flow/config.local.json",
    "work-flow/state.md",
    "work-flow/docs/README.md",
    "work-flow/docs/requirements/.gitkeep",
    "work-flow/docs/decisions/.gitkeep",
    "work-flow/docs/handoffs/.gitkeep",
    "work-flow/docs/archive/.gitkeep",
    "work-flow/.runtime/worker-results/.gitkeep",
    "work-flow/.runtime/migration-backups/.gitkeep",
    "work-flow/.runtime/transactions/.gitkeep",
    "work-flow/.runtime/operation-lock.json",
    "work-flow/docs/evidence/.gitkeep",
    "work-flow/scripts/Invoke-ProjectWorkflow.ps1",
    "work-flow/scripts/invoke-project-workflow.sh",
    "work-flow/scripts/workflow.py",
    "work-flow/scripts/Test-ProjectWorkflow.ps1",
    "work-flow/scripts/test-project-workflow.sh",
    "work-flow/scripts/_runtime/workflow_cli.py",
    "work-flow/scripts/_runtime/runtime-manifest.json",
)

RUNTIME_CORE_MODULES = (
    "__init__.py",
    "constants.py",
    "schema.py",
    "scanning.py",
    "templates.py",
    "plan_generation.py",
    "initialization.py",
    "transactions.py",
    "validation.py",
    "upgrades.py",
    "state.py",
    "locking.py",
    "routing.py",
    "workers.py",
    "archiving.py",
    "scanner.py",
    "planner.py",
    "initializer.py",
    "migration.py",
    "runtime_manifest.py",
)

SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".mjs",
    ".php",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}

MANIFEST_NAMES = {
    "Cargo.toml",
    "go.mod",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "Pipfile",
    "poetry.lock",
    "Gemfile",
    "composer.json",
    "pom.xml",
    "build.gradle",
    "settings.gradle",
    "Makefile",
}

README_NAMES = {"README", "README.md", "README.txt", "Readme.md", "readme.md"}


def runtime_core_required_files():
    return tuple(
        str(PurePosixPath("work-flow/scripts/_runtime/workflow_core") / name)
        for name in RUNTIME_CORE_MODULES
    )
