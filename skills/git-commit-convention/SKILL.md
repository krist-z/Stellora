---
name: git-commit-convention
description: Git commit message convention for this project. Use whenever generating, reviewing, or rewriting commit messages to ensure consistency.
---

# Git Commit 规范

## 格式

所有 commit message 必须严格遵循以下格式：

```
<TYPE>(range): 中文消息
```

- `<TYPE>`：必须为大写英文，用尖括号包裹
- `(range)`：小写英文，用圆括号包裹，表示影响范围
- `: `：冒号后必须跟一个空格
- `中文消息`：使用中文描述本次改动的内容，句尾不加句号

## TYPE 列表

| TYPE | 含义 | 使用场景 |
|------|------|----------|
| FEAT | 新功能 | 新增功能、新增模块、新增接口 |
| FIX | 修复 | 修复 bug、修复异常行为 |
| DOCS | 文档 | 修改注释、更新文档、修改说明文字 |
| STYLE | 格式 | 代码格式化、调整缩进、换行等不影响逻辑的调整 |
| REFACTOR | 重构 | 重构代码结构、重命名变量/函数（不改变外部行为） |
| PERF | 性能 | 性能优化、算法改进 |
| TEST | 测试 | 新增或修改测试用例 |
| BUILD | 构建 | 修改构建脚本、编译配置、依赖库变更 |
| CI | 持续集成 | 修改 CI/CD 流水线配置（如 CI 配置文件） |
| CHORE | 杂项 | 工具配置更新、.gitignore 修改、版本号更新等非业务改动 |
| REVERT | 回滚 | 撤销之前的 commit |

## Range 列表

| Range | 含义 |
|-------|------|
| db | 数据库相关（表结构、SQL、迁移脚本等） |
| deps | 依赖/第三方库（引入、升级、移除第三方库） |
| git | Git 配置（.gitignore、子模块等） |
| build | 构建系统（构建脚本、编译配置等） |
| ui | 界面相关（UI 布局、样式、资源文件等） |
| core | 核心逻辑（业务核心算法、主流程等） |
| model | 数据模型（实体类、数据结构、DTO 等） |
| device | 设备相关（通信协议、硬件接口等） |
| report | 报告相关（报告生成、打印、导出等） |
| public | 公共模块（工具类、公共函数、全局配置等） |

当涉及多个范围时，使用逗号分隔，如 `(db,deps)`。

## 示例

```
<FEAT>(db): 将数据库文件名从 data.db 修改为 app.db
<CHORE>(git): 将 .vscode 目录加入 git 忽略列表
<FEAT>(deps): 将 nlohmann/json 库集成到项目
<BUILD>(deps): 将 spdlog 预编译库和头文件加入版本控制
<DOCS>(db): 更新所有引用 data.db 的注释和脚本为 app.db
<FIX>(ui): 修复主界面表格列宽异常的问题
<REFACTOR>(core): 重构用户记录的数据查询逻辑
<PERF>(core): 优化批量数据处理的内存占用
```

## 使用规则

1. **TYPE 必须大写**，且必须使用尖括号包裹，如 `<FEAT>`、`<FIX>`
2. **Range 必须小写**，使用圆括号包裹，如 `(db)`、`(deps)`
3. **消息必须使用中文**，简洁明了，不超过 50 个汉字
4. **句尾不加标点符号**（句号、感叹号等）
5. **避免使用模糊词汇**，如"修改了一些东西"、"更新代码"等
6. **一次 commit 只做一件事**，若涉及多个独立改动，应拆分为多个 commit

## 生成提交信息时的行为规范

- **只关注当前待提交的改动**，基于 `git diff --cached` 或 `git status` 的输出生成 message
- **不要展示历史提交上下文**（如 `git log` 中的往期 commit），避免信息冗余
- **不需要罗列之前的 commit 记录**，用户只需要本次改动的提交信息
- **仅输出提交信息文本**，不自动执行 `git commit`，由用户自行决定是否提交
