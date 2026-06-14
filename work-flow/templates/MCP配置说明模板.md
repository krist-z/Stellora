# 工具服务器 / MCP 配置说明模板

本文档用于记录当前环境或项目需要哪些工具服务器、插件、CLI、MCP server 或外部系统连接，以及它们的作用、权限边界和验证方式。

不要在本文档中写真实 token、密码、cookie、私钥、session、客户数据或不可公开的服务地址。

## 1. 工具服务器是什么

工具服务器是 AI 连接外部能力的接口层。它可能是 MCP server，也可能是 IDE 插件、CLI、浏览器自动化、数据库连接、知识库连接、项目管理系统连接或云服务连接。

它负责提供“AI 能调用什么工具”，但不定义“项目应该怎么做”。

项目工作流仍由：

```text
Agent 入口文档
project_rules.md
README.md
docs/
scripts/
```

决定。

## 2. 工具服务器与 skill / playbook 的区别

| 项目 | 工具服务器 / MCP | skill / playbook |
|---|---|---|
| 本质 | 工具接口 | 任务流程说明 |
| 解决问题 | AI 能访问什么能力 | AI 什么时候、如何使用能力 |
| 配置位置 | `<AI_HOME>/config`、IDE 设置、插件设置、环境变量等 | `<AI_HOME>/skills/<skill-name>` 或团队知识库 |
| 是否包含项目命令 | 不建议 | 全局 skill 不建议，项目 skill 可例外 |
| 是否包含 secret | 不写入文档，必要时走环境变量或密钥管理 | 不应包含 secret |

## 3. 当前工具清单

按实际环境填写：

| Tool | 作用 | 权限等级 | 允许操作 | 禁止操作 | 凭据来源 | 验证方式 |
|---|---|---|---|---|---|---|
| `<filesystem-tool>` | 读写允许目录内的文件 | `<read/write>` | `<allowed>` | `<forbidden>` | 无或系统权限 | 读一个无敏文件 |
| `<command-tool>` | 运行本机命令 | `<execute>` | `<allowed>` | 删除、发布、高权限操作 | 系统权限 | 运行只读命令 |
| `<browser-tool>` | 浏览器自动化和截图 | `<network/ui>` | 打开页面、截图、表单测试 | 未授权登录或提交 | 无或测试账号 | 打开测试页 |
| `<docs-tool>` | 查询文档或知识库 | `<read>` | 搜索、读取 | 写入或删除 | API token 或无 | 只读查询 |
| `<database-tool>` | 查询或修改数据库 | `<read/write>` | 按授权执行 | 未备份写入、删除、迁移 | 受控凭据 | 只读查询 |
| `<project-tool>` | 项目管理系统 | `<read/write>` | 读 issue、创建草稿 | 未授权关闭/删除/批量修改 | API token | 读一个测试项目 |

## 4. 权限等级

建议使用以下等级：

| 等级 | 含义 | 默认规则 |
|---|---|---|
| T0 | 无外部访问 | 可直接使用 |
| T1 | 只读文件或只读文档 | 可使用，注意隐私 |
| T2 | 本机命令或生成临时产物 | 检查命令和工作目录 |
| T3 | 写文件、写外部系统、数据库写入 | 需要明确授权和回滚 |
| T4 | 发布、删除、迁移、生产、权限变更 | 必须人工确认和审计 |

## 5. 配置示意

以下是示意，不要复制真实 secret。

```toml
[tools.filesystem]
command = "<command>"
args = ["<allowed-project-root>", "<allowed-output-root>"]

[tools.docs]
command = "<command>"
args = ["<docs-server-package>"]

[tools.external-service]
command = "<command>"
args = ["<external-service-package>"]

[tools.external-service.env]
API_TOKEN = "<read-from-env-or-secret-manager>"
```

也可以用 JSON / YAML / IDE 设置表达：

```yaml
tools:
  filesystem:
    allowed_roots:
      - <project-root>
      - <output-root>
  external_service:
    credential_source: environment
    default_mode: read_only
```

## 6. 安全边界

必须遵守：

- 不把真实 token 写入本文档。
- 不把真实 token 写入 Agent 入口文档、skill、README 或 docs。
- 有写权限的工具只开放必要目录。
- 有外部系统写权限的工具默认只读使用，除非用户明确要求写入。
- 命令执行工具必须遵守项目规则和用户授权。
- 项目专属命令写入 scripts 和 Agent 入口文档，不写进工具配置。
- 工具日志必须脱敏。
- 定期复核工具权限和不用的凭据。

## 7. 新增工具的流程

1. 明确用途：它解决什么反复出现的问题？
2. 明确权限：只读、读写、本机命令、网络、外部系统写入？
3. 明确风险等级：T0-T4。
4. 明确凭据来源：环境变量、密钥管理器、测试账号或无凭据。
5. 配置工具。
6. 用只读或低风险命令验证。
7. 如果影响项目工作流，更新项目 Agent 入口文档或 docs。
8. 如果需要专门使用流程，创建或更新 skill / playbook。

## 8. 验证记录

```text
Date:
Tool:
Permission Level:
Test:
Result:
Notes:
Owner:
Next Review:
```

## 9. 常见误区

- 把工具配置当项目规则。
- 为一次性任务开长期高权限工具。
- 在文档里写真实 token。
- 给文件工具开放过宽目录。
- 命令工具执行破坏性命令前不检查项目规则。
- 新增外部服务工具后不记录用途和边界。
- 外部系统写操作没有审计记录。
- 生产和测试凭据混用。
