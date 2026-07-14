# PMAA 版本控制与回滚指南

本文档用于支持多个 AI 或多人并行开发 PMAA 项目，目标是避免互相覆盖代码，并在出错时可定位、可回退、可恢复。

## 1. 分支模型

稳定主线只放可运行版本：

```text
main
├─ feature/wiki-module
├─ feature/policy-agent
├─ feature/evaluator-agent
└─ feature/ui-polish
```

约定：

- `main`：稳定分支，只合并测试通过的功能。
- `feature/wiki-module`：LLM Wiki / GBrain MCP 相关开发。
- `feature/policy-agent`：Policy Agent / 意图识别 / 风险策略开发。
- `feature/evaluator-agent`：评测 Agent / 质量评分 / 回归测试开发。
- `feature/ui-polish`：页面样式与交互优化。

## 2. 文件所有权

两个 AI 可以并行，但不能同时拥有同一个核心文件的修改权。

| 区域 | 主要负责人 | 说明 |
|---|---|---|
| `src/pmaa/wiki/*` | Wiki 功能开发者 | GBrain Wiki 高层 MCP 适配 |
| `src/pmaa/agents/policy.py` | Policy Agent 开发者 | 意图、风险、确认策略 |
| `src/pmaa/workflow/*` | 需要协调 | LangGraph 流程，冲突风险高 |
| `src/pmaa/ui/streamlit_app.py` | 需要协调 | 页面入口集中，冲突风险高 |
| `src/pmaa/config.py` | 需要协调 | 配置字段变更需同步 `.env.example` |
| `.env` | 不提交 | 本地密钥和运行配置 |
| `.env.example` | 可提交 | 只放空值和示例 |

## 3. 开发流程

创建功能分支：

```bash
git checkout main
git checkout -b feature/policy-agent
```

开发过程中小步提交：

```bash
git add .
git commit -m "feat: add policy agent schema"
```

合并前检查：

```bash
uv run pytest -q
git status
git diff main...HEAD
```

合并回主线：

```bash
git checkout main
git merge feature/policy-agent
uv run pytest -q
```

## 4. 回滚策略

优先使用 `git revert`，不要随意使用 `git reset --hard`。

回滚某个提交：

```bash
git revert <commit_id>
```

回到某个稳定标签查看代码：

```bash
git checkout v0.1.0-mvp
```

从稳定标签创建修复分支：

```bash
git checkout -b hotfix/from-v0.1.0 v0.1.0-mvp
```

## 5. 版本标签

每个稳定版本都应打标签：

```bash
git tag v0.1.0-mvp
```

查看标签：

```bash
git tag
```

查看某个标签的提交：

```bash
git show v0.1.0-mvp
```

## 6. 修改日志

每次合并功能分支前更新 `CHANGELOG.md`：

```markdown
## 2026-07-14
### Added
- 新增 Policy Agent。

### Changed
- Supervisor 不再承担意图识别。

### Fixed
- 修复某个路由错误。
```

## 7. 多 AI 协作规则

- 每个 AI 只在自己的功能分支工作。
- 开始工作前先说明本次会修改哪些文件。
- 不修改 `.env`，除非用户明确要求。
- 不直接改另一个 AI 正在负责的文件。
- 如果必须改公共文件，先提交当前分支，再由用户决定合并顺序。
- 合并前必须跑测试。
- 出错时先 `git status` 和 `git diff`，再决定 revert 或继续修复。

## 8. 建议提交信息

```text
feat: add policy agent schema
fix: handle missing gbrain high level tools
docs: add version control guide
test: cover wiki mcp preview flow
refactor: split policy routing from supervisor
```
