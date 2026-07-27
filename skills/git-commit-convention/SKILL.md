---
name: git-commit-convention
description: Git commit message and commit-scope rules for this project. Use whenever preparing, generating, reviewing, or rewriting a commit.
---

# Git 提交规则

## 基本要求

- 一次提交只做一件事。
- 代码提交前必须完成工作流闭环，至少通过相关自检和测试。
- 只暂存当前任务相关文件，禁止夹带无关修改。
- 提交内容必须真实反映本次改动，明确说明改了什么和为什么改。
- 不提交 secret、日志、数据库、缓存、构建产物或本机素材。
- 只有用户明确要求提交时才执行 commit；推送、创建 PR、合并和发布需要分别确认目标与范围。

## 提交信息格式

```text
<type>(<scope>): <subject>
```

示例：

```text
feat(auth): 增加短信登录
fix(api): 修复用户列表分页错误
docs(readme): 补充本地启动说明
```

## Type

- `feat`：新增功能。
- `fix`：修复缺陷。
- `docs`：文档修改。
- `refactor`：重构，不新增功能、不修复缺陷。
- `style`：格式调整，不影响逻辑。
- `test`：测试相关。
- `chore`：构建、脚本、依赖和杂项维护。
- `perf`：性能优化。
- `build`：构建系统或依赖打包调整。
- `ci`：CI/CD 配置调整。
- `revert`：回滚提交。

## Subject 与 Scope

- Subject 使用简短明确、以动词开头的描述，建议不超过 50 个字符。
- Subject 不加句号，不写长段落，中英文风格保持统一。
- Scope 使用能表达影响范围的小写名称，例如 `auth`、`api`、`ui`、`config`。
- 范围不明确时可以省略 scope，但不能随意编造。
- 禁止使用 `update`、`fix bug` 等模糊提交信息。

## 生成提交信息

- 只依据当前待提交改动生成信息。
- 提交前检查 `git status` 和 staged diff，确认没有无关文件。
- 提交信息只描述当前提交，不罗列历史提交。
- 未获得用户提交授权时，只输出建议的提交信息，不自动执行 commit。
