# 修改日志

本项目按日期记录重要功能、修复、架构调整和版本标签。每次合并功能分支前，应更新本文件。

## Unreleased

### Added
- 新增 Policy Agent 第一版，负责意图、执行模式、工具需求、Memory 参与、确认需求和风险等级判断。
- 在 Streamlit 思考过程区域新增 Policy 策略卡片，清晰展示意图、执行模式、工具需求、确认需求和风险等级。

### Changed
- Supervisor 改为消费 Policy Agent 的策略决策，专注调度、执行顺序和结果汇总。
- 记忆类请求不再由策略层判定“写入记忆”，而是标记 `need_memory`，由 Memory Agent 负责 extract、validate、update。
- Agent 执行过程展示不再把 Supervisor 策略事件渲染成整块 JSON，而是格式化为可读字段。

## 2026-07-14

### Added
- 接入 GBrain Wiki 高层 MCP 工具契约：`wiki_import_preview`、`wiki_import_commit`、`wiki_import_status`、`wiki_search`、`wiki_get_page`、`wiki_visualize`。
- 新增 LLM Wiki 知识库页面，用于上传文件、展示 GBrain 返回的导入预览、确认提交和关系图。
- 新增 Wiki 图谱渲染与关系详情查看。
- 新增 Memory Agent 第一版长期记忆流程：retrieve、extract、validate、update。
- 新增 Skill 管理基础能力：导入、启用、运行环境检查和工具绑定。

### Changed
- Knowledge Agent 默认使用高层 Wiki 工具 `wiki_search` / `wiki_get_page`，不再直接依赖底层 GBrain `search` / `get_page`。
- PMAA 的 Wiki 模块职责收缩：只负责文件落 Inbox、调用高层 GBrain Wiki MCP、展示预览和确认结果。
- Streamlit UI 调整为对话、技能、记忆、LLM Wiki 多页面结构。

### Fixed
- 修复 Streamlit 热重载导致的配置字段导入错误。
- 修复对话历史、最近对话、输入框清空和流式展示相关问题。
- 修复资料来源链接展示问题。

### Version
- 当前稳定版本建议标记为 `v0.1.0-mvp`。
