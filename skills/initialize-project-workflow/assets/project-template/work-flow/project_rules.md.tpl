# Project Rules

Follow the user's current request, then the root `AGENTS.md` pointer, then this
file. Existing project rules imported below remain verbatim and retain their
meaning; resolve conflicts explicitly before implementation.

## Managed workflow boundaries

- Keep workflow assets under `work-flow/`; existing project directories remain in place.
- `work-flow/state.md` is the machine state source. Its JSON sentinel block is authoritative; do not edit it directly.
- Keep `work-flow/config.local.json`, `.runtime/`, worker output, backups, and transactions out of version control.
- External writes, production changes, permissions, payment, deletion, migration, and release require explicit confirmation, rollback, monitoring, and post-action validation.

## Git 提交规则

- 一次提交只做一件事；不得夹带与当前任务无关的修改。
- 代码提交前必须完成工作流闭环，至少通过相关自检和测试。
- 只暂存当前任务相关文件；不得提交 secret、日志、数据库、缓存、构建产物或本机素材。
- 只有用户明确要求提交时才执行 commit；推送、创建 PR、合并和发布需要分别确认目标与范围。

提交信息格式：

```text
<type>(<scope>): <subject>
```

示例：

```text
feat(auth): 增加短信登录
fix(api): 修复用户列表分页错误
docs(readme): 补充本地启动说明
```

允许的 type 为 `feat`、`fix`、`docs`、`refactor`、`style`、`test`、
`chore`、`perf`、`build`、`ci` 和 `revert`。

- Subject 应简短明确、以动词开头，建议不超过 50 个字符，不加句号，不写长段落，中英文风格保持统一。
- Scope 使用能表达影响范围的小写名称，例如 `auth`、`api`、`ui`、`config`；范围不明确时可以省略，但不能随意编造。
- 禁止使用 `update`、`fix bug` 等模糊提交信息。

<!-- workflow-managed:project-rules:v1 -->
{{IMPORTED_PROJECT_RULES}}
