# Personal Multi-Agent Assistant (PMAA)

PMAA 是一个本地优先的个人多智能体助手实验项目，基于 LangGraph 编排多个 Agent，用于任务路由、联网检索、本地知识库问答、长期记忆、Skill 调用、邮件处理和 Streamlit 可视化交互。

当前项目重点不是做一个通用聊天壳，而是验证一套可观察、可扩展、可接入本地工具和个人知识库的 Agent 工作流。

## 核心能力

- 多 Agent 工作流：Supervisor、Policy、Planner、Search、Knowledge、Tool、Writer、Reflection、Memory、Email 等角色协作。
- LLM Wiki 知识库：上传 PDF / DOCX / MD / TXT，交给 GBrain 原生索引，并在 PMAA 中展示知识库全景图。
- 语义知识建模：读取 GBrain 原生分块，抽取概念、方法、项目等知识页，并写回 GBrain。
- 知识库生命周期：支持删除来源页，并清理由该来源生成的 PMAA 语义知识页。
- 可交互知识图谱：支持缩放、滚轮缩放、拖动画布，点击节点或连线查看详情。
- Skill 管理：支持本地 Skill 导入、启用、运行环境检查和工具绑定。
- 长期记忆：从对话中提取稳定偏好、事实和长期指令，用于后续任务上下文。
- 邮件工具：支持 QQ 邮箱 IMAP / SMTP 的读取和发送能力。
- Streamlit UI：提供对话、技能、记忆、LLM Wiki 等页面。

## 架构概览

```text
User
  -> Streamlit / API
  -> Supervisor / Policy
  -> Planner 或 Direct Tool
  -> Search / Knowledge / Skill / Email
  -> Writer
  -> Reflection
  -> Final Response
```

知识库相关链路：

```text
Upload file
  -> GBrain Inbox
  -> gbrain-wiki-mcp
  -> GBrain native index
  -> PMAA Wiki graph / semantic modelling
```

## 快速启动

推荐使用 `uv`：

```powershell
uv venv
uv pip install -e ".[dev]"
uv run --no-sync streamlit run src/pmaa/ui/streamlit_app.py
```

如果当前环境使用 Conda，也可以：

```powershell
conda run -n chain python -m pytest -q
conda run -n chain python -m streamlit run src/pmaa/ui/streamlit_app.py
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

## 环境变量

复制 `.env.example` 为 `.env`，再按需填写：

```env
APP_NAME=PMAA
APP_ENV=local

LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

SEARCH_PROVIDER=tavily_mcp
TAVILY_API_KEY=
TAVILY_BASE_URL=https://api.tavily.com/search
TAVILY_MAX_RESULTS=5

GBRAIN_MCP_ENABLED=false
GBRAIN_MCP_TRANSPORT=stdio
GBRAIN_MCP_COMMAND=wsl.exe
GBRAIN_INBOX_DIR=C:\Users\lzl\GbrainInbox

QQ_EMAIL_ADDRESS=
QQ_EMAIL_AUTH_CODE=
```

说明：

- `LLM_PROVIDER=deepseek` 时使用 DeepSeek OpenAI-compatible 接口。
- `SEARCH_PROVIDER=tavily_mcp` 时通过 Tavily MCP 做联网搜索。
- `GBRAIN_MCP_ENABLED=true` 后会启用本地 GBrain MCP 知识库检索。
- QQ 邮箱需要授权码，不是登录密码。

## 测试

```powershell
uv run --no-sync pytest -q
```

或：

```powershell
conda run -n chain python -m pytest -q
```

当前本地验证结果：

```text
199 passed
```

## 目录结构

```text
src/pmaa/agents      Agent 实现
src/pmaa/workflow    LangGraph 工作流
src/pmaa/tools       工具封装与注册
src/pmaa/wiki        GBrain Wiki 导入、建模、删除
src/pmaa/skills      Skill 注册、运行时与绑定
src/pmaa/ui          Streamlit 界面
tests                自动化测试
```

## 当前状态

这是一个本地个人助手 MVP，已经具备端到端演示能力。仍需继续完善：

- 更稳定的 GBrain 级联删除 / 版本管理机制
- 更完善的 Skill 权限与审计
- 更多真实工具接入
- 更系统的部署和配置文档
