# Personal Multi-Agent Assistant (PMAA) 需求文档

版本：v1.0  
阶段：MVP  
项目目录：`E:\langgraph_projects\agent-assistant`

---

## 1. 项目定位

Personal Multi-Agent Assistant（PMAA）是一个面向个人知识工作场景的多 Agent 智能助手系统。

系统基于 **Supervisor + LangGraph + Multi-Agent** 架构构建，目标不是做普通 ChatBot，而是帮助用户完成复杂任务。

PMAA v1 聚焦于：

- 理解用户复杂请求
- 拆解任务执行步骤
- 调用搜索工具获取外部信息
- 生成结构化结果
- 对结果进行反思检查
- 展示可追踪的 Agent 执行过程

一句话定位：

> PMAA 是一个能把复杂问题拆解、搜索资料、生成报告并自我检查的个人多 Agent 助手。

---

## 2. 项目目标

### 2.1 核心目标

PMAA v1 要实现一条完整的多 Agent 任务执行闭环：

```text
用户输入复杂任务
↓
Supervisor 判断任务类型
↓
Planner 拆解任务
↓
Search Agent 获取外部资料
↓
Writer Agent 生成结果
↓
Reflection Agent 检查质量
↓
Supervisor 汇总返回
```

### 2.2 展示重点

本项目应重点体现以下工程能力：

- Multi-Agent 角色拆分
- LangGraph 状态流编排
- LLM 任务规划
- 工具调用抽象
- 流程状态可追踪
- 结果反思与质量控制
- 后续扩展 RAG、Memory、MCP 的架构空间

---

## 3. 非目标范围

以下能力不进入 v1 MVP：

- Knowledge Agent
- 本地知识库 RAG
- 文档上传与解析
- 向量数据库
- 长期记忆 Memory Agent
- Coding Agent
- Calendar / Email / Schedule Agent
- 完整 MCP 工具生态
- 多用户权限系统
- 企业级部署集群

注意：这些不是废弃能力，而是 v2/v3 扩展方向。v1 先保证核心链路跑通。

---

## 4. 目标用户

### 4.1 主要用户

- 需要快速研究问题的个人用户
- 需要生成学习计划、技术调研、方案分析的人
- 希望通过该项目展示 LLM Agent 工程能力的开发者

### 4.2 典型使用场景

1. 技术主题研究  
   示例：帮我研究 LangGraph 在多 Agent 系统中的作用。

2. 学习计划生成  
   示例：帮我制定一个两周学习 LLM Agent 开发的计划。

3. 方案分析  
   示例：对比 LangGraph、AutoGen 和 CrewAI 的优缺点。

4. 决策辅助  
   示例：我应该先学 RAG 还是 Agent？请给出理由和计划。

---

## 5. MVP Agent 设计

PMAA v1 保留 5 个 Agent。

### 5.1 Supervisor Agent

职责：

- 接收用户请求
- 判断任务复杂度
- 决定是否进入多 Agent 工作流
- 调用 Planner
- 汇总最终输出
- 保持回复风格统一

不负责：

- 直接搜索
- 直接写报告
- 直接做反思检查

### 5.2 Planner Agent

职责：

- 将复杂任务拆解为多个子任务
- 生成结构化 Execution Plan
- 明确每一步需要调用的 Agent
- 输出可被 LangGraph 执行的计划结构

示例输出字段：

- `goal`
- `steps`
- `required_agents`
- `expected_output`
- `risk_points`

### 5.3 Search Agent

职责：

- 根据 Planner 的子任务生成搜索查询
- 调用搜索工具或搜索接口
- 返回结构化搜索结果
- 保留来源信息

不负责：

- 写总结
- 判断最终答案
- 生成报告

### 5.4 Writer Agent

职责：

- 根据 Planner、Search Agent 的结果生成结构化内容
- 输出报告、计划、对比表或建议
- 保持内容清晰、分层、可读

输出形式：

- Markdown 报告
- 分步骤计划
- 表格对比
- 总结建议

### 5.5 Reflection Agent

职责：

- 检查最终结果是否回答用户问题
- 检查是否存在明显遗漏
- 检查搜索来源是否被合理使用
- 判断是否需要补充搜索或重写

输出：

- `pass`: 是否通过
- `issues`: 存在的问题
- `suggested_fix`: 修正建议
- `need_retry`: 是否需要重试

---

## 6. 系统模块

### 6.1 Web UI / Desktop UI

v1 可以先实现简单 Web UI，也可以先提供 CLI。

推荐顺序：

1. 先实现 CLI 或简单 API 调试入口
2. 再实现 Web UI

UI 应展示：

- 用户输入
- 最终回答
- Agent 执行步骤
- 每个 Agent 的状态
- Reflection 检查结果

### 6.2 FastAPI API

职责：

- 提供统一 HTTP 入口
- 接收用户任务
- 返回流式或非流式结果
- 暴露任务执行状态查询接口

核心接口建议：

- `POST /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/events`

### 6.3 LangGraph Workflow

职责：

- 编排 Agent 执行顺序
- 保存任务状态
- 支持条件分支
- 支持 Reflection 后的重试

v1 工作流：

```text
supervisor
↓
planner
↓
search
↓
writer
↓
reflection
↓
finalize
```

Reflection 分支：

```text
reflection.pass = true  -> finalize
reflection.pass = false -> retry search or writer
```

### 6.4 Tool Registry

职责：

- 统一注册工具
- 屏蔽底层工具实现
- 为 Agent 提供稳定调用接口

v1 工具：

- Search Tool
- Time Tool
- Mock Tool

v2 扩展：

- Browser Tool
- Filesystem Tool
- Python Tool
- MCP Tool Adapter

---

## 7. 数据结构

### 7.1 Task

```json
{
  "task_id": "string",
  "user_input": "string",
  "status": "pending | running | completed | failed",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

### 7.2 Execution Plan

```json
{
  "goal": "string",
  "steps": [
    {
      "step_id": "string",
      "description": "string",
      "agent": "string",
      "expected_output": "string"
    }
  ]
}
```

### 7.3 Agent Event

```json
{
  "task_id": "string",
  "agent": "string",
  "event_type": "started | completed | failed",
  "input": {},
  "output": {},
  "timestamp": "datetime"
}
```

### 7.4 Final Result

```json
{
  "answer": "string",
  "sources": [],
  "reflection": {
    "pass": true,
    "issues": [],
    "need_retry": false
  }
}
```

---

## 8. 验收标准

### 8.1 功能验收

v1 必须完成：

- 用户可以提交一个复杂任务
- Supervisor 能启动多 Agent 流程
- Planner 能生成结构化执行计划
- Search Agent 能返回搜索结果或模拟搜索结果
- Writer Agent 能生成结构化回答
- Reflection Agent 能检查回答质量
- 系统能返回最终结果
- 系统能记录每个 Agent 的执行状态

### 8.2 示例任务验收

至少支持以下测试任务：

1. 帮我研究 LangGraph 的核心概念，并生成学习路线。
2. 对比 LangGraph、CrewAI、AutoGen 的适用场景。
3. 帮我制定一个 7 天 LLM Agent 学习计划。
4. 分析多 Agent 系统中 Planner 和 Supervisor 的区别。

### 8.3 工程验收

- 项目结构清晰
- Agent 职责独立
- Workflow 状态可追踪
- 工具调用通过 Tool Registry
- 关键模块有单元测试
- README 能说明如何启动和演示

---

## 9. 技术栈建议

### 9.1 后端

- Python
- uv
- FastAPI
- LangGraph
- LangChain Core
- Pydantic

### 9.2 LLM

优先支持可配置模型提供商：

- OpenAI-compatible API
- DeepSeek
- Qwen
- Gemini

具体模型通过环境变量配置，不写死在代码中。

### 9.3 存储

v1：

- SQLite 或本地 JSON 文件

v2：

- PostgreSQL
- Redis
- pgvector / Milvus
- Object Storage

### 9.4 前端

v1 可选：

- 简单 HTML 页面
- 或 React / Next.js

如果目标是尽快跑通 MVP，建议先做 FastAPI + 简单 Web UI。

---

## 10. 推荐项目结构

```text
agent-assistant/
├── docs/
│   └── requirements.md
├── src/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   └── routes.py
│   ├── agents/
│   │   ├── supervisor.py
│   │   ├── planner.py
│   │   ├── search.py
│   │   ├── writer.py
│   │   └── reflection.py
│   ├── workflow/
│   │   ├── graph.py
│   │   └── state.py
│   ├── tools/
│   │   ├── registry.py
│   │   └── search_tool.py
│   ├── schemas/
│   │   ├── task.py
│   │   └── agent.py
│   └── storage/
│       └── task_store.py
├── tests/
├── .env.example
├── .gitignore
├── README.md
├── uv.lock
└── pyproject.toml
```

---

## 11. 后续路线

### v1：搜索增强多 Agent 助手

- 5 个 Agent
- LangGraph 工作流
- Search Tool
- Reflection Retry
- Agent 执行日志

### v2：知识库增强

- 增加 Knowledge Agent
- 支持文档上传
- 支持 RAG
- 支持引用来源
- 接入向量数据库

### v3：长期记忆与 MCP

- 增加 Memory Agent
- 支持长期用户偏好
- 接入 MCP Tool Adapter
- 支持更多外部工具

### v4：产品化

- Web UI 完善
- 多任务管理
- 用户认证
- 权限控制
- 部署文档

---

## 12. 风险与约束

### 12.1 主要风险

- Agent 过多导致系统复杂度失控
- Planner 输出不稳定
- Search 结果质量影响最终回答
- Reflection 可能只做表面检查
- 工具调用失败后缺少恢复机制

### 12.2 控制策略

- v1 严格限制为 5 个 Agent
- 所有 Agent 输出使用 Pydantic 结构化约束
- Workflow 状态统一由 LangGraph 管理
- Reflection 设置最大重试次数
- Tool Registry 统一处理错误和超时

---

## 13. 简历表述建议

可写为：

> 设计并实现 Personal Multi-Agent Assistant，一个基于 LangGraph 的个人多 Agent 助手系统。系统采用 Supervisor + Planner + Specialist Agents 架构，将复杂用户任务拆解为可执行工作流，并通过搜索增强、工具注册、结果反思和状态追踪机制生成结构化任务结果。

可强调技术点：

- 基于 LangGraph 构建状态驱动的 Agent Workflow
- 设计 Supervisor / Planner / Search / Writer / Reflection 多 Agent 协作机制
- 实现 Tool Registry 统一管理工具调用
- 支持 Agent 执行链路记录与结果质量检查
- 为后续 RAG、Memory、MCP 扩展预留模块边界

---

## 14. 当前结论

PMAA v1 不追求大而全。

首版目标是做出一个清晰、稳定、可演示、可扩展的多 Agent 任务闭环。

只要这条链路跑通，本项目就已经具备写入简历和继续扩展的价值。
