# Personal Multi-Agent Assistant (PMAA)

PMAA 是一个基于 Supervisor + LangGraph + Multi-Agent 架构的个人智能助手 MVP。当前版本聚焦一条可演示的复杂任务链路：任务路由、规划、联网搜索、内容生成、反思检查和结果展示。

## 当前 Agent

- Supervisor Agent：任务入口、流程调度、最终汇总
- Planner Agent：生成结构化执行计划
- Search Agent：通过 Tool Registry 调用搜索工具
- Writer Agent：生成结构化中文回答
- Reflection Agent：检查回答质量和风险点

## 工作流

```text
User
-> Supervisor
-> Planner
-> Search
-> Writer
-> Reflection
-> Final Response
```

工作流由 `langgraph.graph.StateGraph` 编排执行。

## Tavily MCP 搜索

当前真实联网搜索走本地 MCP Server：

```text
Search Agent
-> Tool Registry
-> MCP stdio client
-> mcp_servers/tavily_search_server.py
-> Tavily Search API
```

`.env` 示例：

```env
SEARCH_PROVIDER=tavily_mcp
TAVILY_API_KEY=你的 Tavily API Key
TAVILY_BASE_URL=https://api.tavily.com/search
TAVILY_MAX_RESULTS=5
```

单独启动 MCP Server：

```powershell
uv run python -m mcp_servers.tavily_search_server
```

Streamlit 页面运行任务时会使用配置中的 Tavily MCP 搜索。

## LLM 配置

默认使用 DeepSeek OpenAI-Compatible 接口：

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

如果 `.env` 同时存在阿里云百炼和 DeepSeek Key，`deepseek-v4-flash` 会按 `LLM_PROVIDER=deepseek` 使用 DeepSeek Key。

## 快速启动

推荐使用 uv：

```powershell
uv venv
uv pip install -e ".[dev]"
uv run --no-sync pytest -v
uv run --no-sync streamlit run src/pmaa/ui/streamlit_app.py
```

如果当前终端找不到 `uv`，可以使用完整路径：

```powershell
C:\Users\lzl\AppData\Roaming\Python\Python313\Scripts\uv.exe run --no-sync pytest -v
C:\Users\lzl\AppData\Roaming\Python\Python313\Scripts\uv.exe run --no-sync streamlit run src/pmaa/ui/streamlit_app.py
```

开发时不要直接使用 `uv run pytest` 跑测试。普通 `uv run` 会先尝试同步依赖，Windows 下如果 Streamlit 正在运行，可能锁住 `.venv` 中的 `websockets` 文件，导致测试启动失败。依赖变更时再执行：

```powershell
uv pip install -e ".[dev]"
```

默认访问：

```text
http://localhost:8501
```

## API 服务

```powershell
uv run uvicorn pmaa.main:app --reload --host 127.0.0.1 --port 8001
```

API 文档：

```text
http://127.0.0.1:8001/docs
```

## 后续路线

- v1：完善 Tavily MCP 搜索、LLM 生成、Streamlit 可视化
- v2：增加 Knowledge Agent 和 RAG
- v3：增加 Memory Agent
- v4：增加更多 MCP 工具，如浏览器、文件、日历
