# <ProjectName> AI Agent Guide

本文档是当前项目的 AI Agent 入口文档。它定义 AI 在本项目中应该先读什么、能改什么、如何验证、如何同步文档和证据。

文件名可以使用 `AGENTS.md`、`AI_GUIDE.md`、`ASSISTANT.md`、`.ai/guide.md` 或团队约定名称。

## Priority

使用以下优先级：

1. 用户最新请求。
2. 本项目 Agent 入口文档。
3. 本项目 `project_rules.md`、`README.md`、`CONTRIBUTING.md`、`docs/`、runbook、验收结果。
4. 全局 skill、playbook、workflow card 或工具说明。
5. 全局个人偏好。

如果项目规则与全局能力包冲突，以本项目规则为准。

## Project Map

按实际项目替换：

- `<source-dir>/`：主要源码或主要产物。
- `<tests-dir>/`：自动化测试。
- `<scripts-dir>/`：构建、运行、测试、验收、同步检查脚本。
- `<docs-dir>/`：设计、需求、验收、证据、运行手册。
- `<config-dir>/`：配置模板和示例。
- `<artifact-dir>/`：生成物、日志、验收产物，默认不提交。

## Safety Boundaries

不得提交、公开或写入长期文档：

- 真实 token、API key、密码、私钥、session、cookie。
- 真实服务器、账号、客户、用户、群组、订单、财务或身份信息。
- 本地数据库、日志、缓存、运行时状态。
- 构建产物、验收临时产物。
- 本机专属路径和个人配置。
- 受隐私、合规、合同或授权限制的数据。

如果项目存在公开导出、发布或客户交付流程，在这里写清 include/exclude 列表和敏感信息扫描命令。

## Task Levels

| Level | Name | Use When | Minimum Closeout |
|---|---|---|---|
| L1 | Quick | 小文案、注释、低风险说明、轻微配置提示 | 读直接相关文件，做最小改动，静态/可读性检查或说明不适用 |
| L2 | Standard | 普通 bug fix、局部功能、脚本、测试、小重构 | 读相关规则和设计，运行 targeted test，同步必要文档 |
| L3 | Full Closure | 跨模块、用户主流程、协议、持久化、数据处理、外部服务、明确要求闭环 | 真实路径或可信验收通过，证据更新，工作流同步检查通过，残余风险明确 |
| L4 | Release/Risk | 发布、迁移、删除、安全、权限、生产、不可逆操作、敏感数据 | L3 完成，并补回滚、监控、发布后验证、审计记录和人工确认 |

实际影响高于用户表述时，按更高等级执行并说明原因。

## Risk Levels

| Risk | Examples | Rule |
|---|---|---|
| R0 | 只读分析、解释、草稿 | 可直接执行 |
| R1 | 小范围文件编辑、无外部副作用 | 可执行，收尾说明 |
| R2 | 运行测试、生成临时产物、安装普通开发依赖 | 检查项目规则，必要时提示 |
| R3 | 修改配置、数据库写入、外部 API 调用、批量操作 | 需要明确授权和回滚/备份 |
| R4 | 删除、迁移、发布、生产、权限、推送、敏感数据 | 必须人工确认，记录审计和回滚方案 |

## Roles

非平凡任务按以下逻辑角色完成；小任务可由一个 AI 实例完成全部角色。

- PM：定义目标、范围、任务等级、验收标准和风险。
- Explorer：只读探索规则、文档、源码、脚本、测试和证据。
- Builder：按项目边界做最小实现。
- Tester：运行能证明本次改动的最小验证。
- Reporter：同步长期文档和证据，给出最终说明。

只有用户明确要求并行代理或委派时，才启动多代理。

## Standard Workflow

1. PM intake：确认目标、影响范围、任务等级、风险等级、验收标准。
2. Explorer pass：读取本文件、项目规则、相关 docs、源码、脚本和证据。
3. Plan：高风险任务先输出计划并等待确认；低风险任务可直接执行。
4. Builder implementation：做最小 coherent change，保留无关工作区变化。
5. Tester verification：运行最小证明命令，必要时升级到真实路径验收。
6. Reporter closeout：更新必要文档或证据，说明验证、未验证项、残余风险和下一步。

## Verification Matrix

按项目替换命令：

```text
# 构建或生成
<build-command>

# 单元/集成测试
<test-command>

# 运行或状态检查
<start-or-status-command>

# 专项验证
<validate-command>

# 文档/工作流同步
<workflow-check-command>

# 安全扫描
<secret-scan-command>
```

构建通过不等于用户路径通过。涉及 UI、网络、持久化、权限、外部系统、生产、数据迁移或真实用户流程时，必须运行真实路径或可信验收。

## Documentation Rules

- 长期结论写入 `docs/`、runbook、证据文档或本文件，不只留在聊天里。
- 新增脚本必须同步 README、环境说明或文档索引。
- 新增重要文档必须同步文档索引。
- 新证据覆盖旧结论时，重写对应证据章节，让文档表达最新可证明状态。
- 全局 skill / playbook 保持通用，项目专属命令和路径写入项目文档。

## File-Writing Rules

- 使用项目现有风格和 helper。
- 做最小必要改动。
- 不做无关重构。
- 不回滚用户、团队成员或其他工具的无关改动。
- 不写真实密钥、日志、数据库、本机路径或个人数据。
- 新增生成物目录前确认忽略规则。
- 批量操作前先 dry-run 或列出影响范围。

## Tool And Permission Rules

- 文件工具只访问必要目录。
- 命令工具只运行必要命令。
- 外部系统默认只读。
- 写入、删除、发布、迁移、推送和权限变更必须明确授权。
- 不在文档或聊天中泄露凭据。
- 工具失败时保留诊断，但要脱敏。

## Git Or Publishing Rules

按实际项目替换：

- 只有用户明确要求提交时才 commit。
- 提交前运行 `<status-command>`。
- 只暂存本次任务相关文件。
- 提交信息使用 `<language/style>`。
- 只有用户明确要求且项目规则允许时才 push。
- 发布或公开导出前运行 secret scan 和边界检查。

## Handoff Template

工作需要下次继续时使用：

```text
Goal:
Current State:
Important Files:
Decisions:
Validation:
Risks:
Rollback:
Next Step:
```

## Common Pitfalls

- 不要只跑构建就宣称真实路径通过。
- 不要让全局 skill 覆盖项目规则。
- 不要把新证据和旧相反结论混在同一结果文档里。
- 不要提交密钥、日志、数据库、缓存、构建产物或个人数据。
- 不要回滚无关工作区变化。
- 不要在没有备份和确认的情况下迁移、删除或发布。
