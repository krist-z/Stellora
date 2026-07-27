<div align="center">
天上白玉京，十二楼五城。
</div>    
<div align="center">    
仙人抚我顶，结发受长生。
</div>    
<div align="center">
误逐世间乐，颇穷理乱情。
</div>    
<div align="center">
九十六圣君，浮云挂空名。
</div>
<div align="center">    
天地赌一掷，未能忘战争。
</div>
<div align="center">    
试涉霸王略，将期轩冕荣。
</div>

  吾等本为古法编程传承人，奈何如今ai乱世，群魔当道，程序员行业乌烟瘴气，裁员风波频起，人人自危；故吾等一线开发潜心修炼三千载，苦学vibe coding，悟出此焚决，包含完整工作流搭建、敏捷开发闭环、自建SKILL技能分享、MCP服务分享等内容，现在此仓库做出分享。吾等的初心是希望各路同行，人人有工作，人人有功练。望各路同行踊跃加入，分享个人心得，你们的每一句分享，都是大家共同进步的一份助力！

  本仓库处于新建的阶段，目前只是雏形，仅仅包含了部分内容，后续会继续填充，欢迎各路豪杰pr，也希望各位使用者多提issue，你的反馈就是我们进步的最大动力！

## 已包含的 Codex 技能

- `coding-standards`：C++ / Qt 编码规范与风格约束。
- `git-commit-convention`：统一 Git 提交信息格式。
- `initialize-project-workflow`：以默认 dry-run、计划哈希、原子事务和回滚保护，为新项目或既有项目建立自包含的 `work-flow/` 控制面。

## 项目工作流初始化

先查看初始化计划，不写入项目：

```powershell
python skills/initialize-project-workflow/scripts/workflow_cli.py init `
  --root <ProjectRoot> `
  --mode new `
  --dry-run `
  --json
```

既有项目将 `--mode new` 改为 `--mode adopt`。确认 dry-run 输出后，使用输出中的精确 `plan_hash` 执行：

```powershell
python skills/initialize-project-workflow/scripts/workflow_cli.py init `
  --root <ProjectRoot> `
  --mode new `
  --apply `
  --plan-hash <sha256> `
  --json
```

初始化不会自动信任非 Git 项目。确需在非 Git 项目中运行 Codex worker 时，应先由用户对当前工作区执行本机 trust 授权。项目日常的离线验证、状态和路由功能使用项目内自包含 runtime，不依赖本仓库的绝对路径。

## 模型内容路由

工作流在 GPT-5.6 系列中按内容选择模型：计划和风险使用 Sol，代码、测试与代码审查使用 Terra，正式文档、结果报告和轻量探索使用 Luna。Sol、Terra、Luna 是内容路由档位，不是调用失败后的自动降级链；认证、账号、provider、配额、限流、网络、权限、schema 或测试失败不会授权静默跨档位替换。

## 开源许可

本项目采用 [MIT License](LICENSE)。
