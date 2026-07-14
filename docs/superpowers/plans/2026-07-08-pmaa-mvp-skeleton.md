# PMAA MVP 项目骨架实施计划

> **给执行 Agent 的要求：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐步执行。步骤使用复选框语法，方便追踪进度。

**目标：** 搭建 PMAA v1 的可运行项目骨架，包括 5 个 Agent、工作流边界、FastAPI 入口、测试和中文 README。

**架构：** 项目采用 Python 后端，按 `schemas / agents / tools / workflow / api / storage` 分层。v1 使用 LangGraph StateGraph 实现多 Agent 闭环，为后续接入 Knowledge Agent、Memory Agent、RAG、MCP 留出边界。

**技术栈：** Python、FastAPI、Pydantic、pytest、LangGraph。

---

## 1. 文件规划

- 创建：`pyproject.toml`  
  定义项目元信息、依赖、pytest 配置。

- 创建：`.env.example`  
  说明运行环境变量。

- 创建：`README.md`  
  中文说明项目定位、架构、启动方式和演示命令。

- 创建：`src/pmaa/__init__.py`  
  Python 包标记文件。

- 创建：`src/pmaa/config.py`  
  加载运行配置。

- 创建：`src/pmaa/schemas/task.py`  
  定义任务、执行计划、Agent 事件、来源、反思结果、最终结果等数据结构。

- 创建：`src/pmaa/tools/registry.py`  
  实现 Tool Registry。

- 创建：`src/pmaa/tools/search_tool.py`  
  实现 v1 的 Mock Search Tool。

- 创建：`src/pmaa/agents/supervisor.py`  
  实现 Supervisor Agent。

- 创建：`src/pmaa/agents/planner.py`  
  实现 Planner Agent。

- 创建：`src/pmaa/agents/search.py`  
  实现 Search Agent。

- 创建：`src/pmaa/agents/writer.py`  
  实现 Writer Agent。

- 创建：`src/pmaa/agents/reflection.py`  
  实现 Reflection Agent。

- 创建：`src/pmaa/workflow/state.py`  
  定义工作流状态。

- 创建：`src/pmaa/workflow/graph.py`  
  实现 v1 固定执行顺序：Supervisor -> Planner -> Search -> Writer -> Reflection -> Finalize。

- 创建：`src/pmaa/storage/task_store.py`  
  实现 v1 内存任务存储。

- 创建：`src/pmaa/api/routes.py`  
  实现任务 API。

- 创建：`src/pmaa/main.py`  
  创建 FastAPI 应用。

- 创建：`tests/test_planner.py`  
  测试 Planner 是否输出结构化执行计划。

- 创建：`tests/test_tool_registry.py`  
  测试工具注册与调用。

- 创建：`tests/test_workflow.py`  
  测试完整工作流是否返回结果和执行事件。

- 创建：`tests/test_api.py`  
  测试任务创建 API。

---

## 2. 任务一：项目元信息与中文 README

**文件：**
- 创建：`pyproject.toml`
- 创建：`.env.example`
- 创建：`README.md`

- [ ] **步骤 1：创建项目配置**

创建 `pyproject.toml`：

```toml
[project]
name = "pmaa"
version = "0.1.0"
description = "Personal Multi-Agent Assistant MVP"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.7.0",
    "python-dotenv>=1.0.1"
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "httpx>=0.27.0"
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **步骤 2：创建环境变量示例**

创建 `.env.example`：

```env
APP_NAME=PMAA
APP_ENV=local
LLM_PROVIDER=mock
SEARCH_PROVIDER=mock
MAX_REFLECTION_RETRIES=1
```

- [ ] **步骤 3：创建中文 README**

创建 `README.md`：

```markdown
# Personal Multi-Agent Assistant (PMAA)

PMAA 是一个个人多 Agent 智能助手项目，采用 Supervisor、Planner、Search、Writer、Reflection 五个核心 Agent 构建。

v1 的目标不是做普通聊天机器人，而是完成一条清晰的复杂任务处理链路：规划、搜索、生成、检查、返回结果。

## MVP Agent

- Supervisor Agent：任务入口、流程调度、最终汇总
- Planner Agent：生成结构化执行计划
- Search Agent：获取外部信息
- Writer Agent：生成结构化回答
- Reflection Agent：检查回答质量

## MVP 工作流

```text
User
-> Supervisor
-> Planner
-> Search
-> Writer
-> Reflection
-> Final Response
```

## 快速启动

```bash
uv venv
uv pip install -e ".[dev]"
uv run pytest -v
uv run uvicorn pmaa.main:app --reload
```

## 演示请求

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/tasks `
  -ContentType "application/json" `
  -Body '{"user_input":"帮我研究 LangGraph 的核心概念，并生成学习路线"}'
```

## 后续路线

- v1：搜索增强的多 Agent 工作流
- v2：增加 Knowledge Agent 和 RAG
- v3：增加 Memory Agent 和 MCP Tool Adapter
- v4：完善 Web UI 和任务管理
```

- [ ] **步骤 4：验证文件存在**

运行：

```powershell
Get-Item pyproject.toml, .env.example, README.md
```

预期：三个文件都能被列出。

---

## 3. 任务二：核心数据结构与 Planner

**文件：**
- 创建：`src/pmaa/__init__.py`
- 创建：`src/pmaa/schemas/task.py`
- 创建：`src/pmaa/agents/planner.py`
- 创建：`tests/test_planner.py`

- [ ] **步骤 1：先写失败测试**

创建 `tests/test_planner.py`：

```python
from pmaa.agents.planner import PlannerAgent


def test_planner_generates_structured_execution_plan():
    planner = PlannerAgent()

    plan = planner.plan("帮我研究 LangGraph 的核心概念，并生成学习路线")

    assert plan.goal
    assert len(plan.steps) >= 2
    assert plan.steps[0].agent == "search"
    assert plan.steps[-1].agent == "writer"
```

- [ ] **步骤 2：运行测试，确认失败**

运行：

```powershell
pytest tests/test_planner.py -v
```

预期：失败，原因是 `pmaa.agents.planner` 尚不存在。

- [ ] **步骤 3：创建包和数据结构**

创建 `src/pmaa/__init__.py`：

```python
"""Personal Multi-Agent Assistant package."""
```

创建 `src/pmaa/schemas/task.py`：

```python
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PlanStep(BaseModel):
    step_id: str
    description: str
    agent: str
    expected_output: str


class ExecutionPlan(BaseModel):
    goal: str
    steps: list[PlanStep]
    required_agents: list[str] = Field(default_factory=list)
    expected_output: str = ""
    risk_points: list[str] = Field(default_factory=list)


class Source(BaseModel):
    title: str
    url: str
    snippet: str


class ReflectionResult(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    suggested_fix: str = ""
    need_retry: bool = False


class FinalResult(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    reflection: ReflectionResult


class AgentEvent(BaseModel):
    task_id: str
    agent: str
    event_type: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    user_input: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    result: FinalResult | None = None
```

- [ ] **步骤 4：实现 Planner**

创建 `src/pmaa/agents/planner.py`：

```python
from pmaa.schemas.task import ExecutionPlan, PlanStep


class PlannerAgent:
    name = "planner"

    def plan(self, user_input: str) -> ExecutionPlan:
        return ExecutionPlan(
            goal=user_input,
            steps=[
                PlanStep(
                    step_id="search-1",
                    description=f"Search background information for: {user_input}",
                    agent="search",
                    expected_output="Relevant sources with titles, URLs, and snippets.",
                ),
                PlanStep(
                    step_id="write-1",
                    description="Create a structured answer from the gathered sources.",
                    agent="writer",
                    expected_output="Markdown answer with clear sections.",
                ),
            ],
            required_agents=["search", "writer", "reflection"],
            expected_output="A structured, source-aware answer.",
            risk_points=["Search results may be incomplete or outdated."],
        )
```

- [ ] **步骤 5：运行测试，确认通过**

运行：

```powershell
pytest tests/test_planner.py -v
```

预期：通过。

---

## 4. 任务三：Tool Registry 与 Search Tool

**文件：**
- 创建：`src/pmaa/tools/registry.py`
- 创建：`src/pmaa/tools/search_tool.py`
- 创建：`tests/test_tool_registry.py`

- [ ] **步骤 1：先写失败测试**

创建 `tests/test_tool_registry.py`：

```python
import pytest

from pmaa.tools.registry import ToolRegistry


def test_registry_returns_registered_tool_result():
    registry = ToolRegistry()
    registry.register("echo", lambda query: f"echo:{query}")

    assert registry.call("echo", "LangGraph") == "echo:LangGraph"


def test_registry_rejects_missing_tool():
    registry = ToolRegistry()

    with pytest.raises(KeyError):
        registry.call("missing", "query")
```

- [ ] **步骤 2：运行测试，确认失败**

运行：

```powershell
pytest tests/test_tool_registry.py -v
```

预期：失败，原因是 `pmaa.tools.registry` 尚不存在。

- [ ] **步骤 3：实现 Tool Registry**

创建 `src/pmaa/tools/registry.py`：

```python
from collections.abc import Callable
from typing import Any


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, tool: Callable[..., Any]) -> None:
        self._tools[name] = tool

    def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if name not in self._tools:
            raise KeyError(f"Tool is not registered: {name}")
        return self._tools[name](*args, **kwargs)
```

- [ ] **步骤 4：实现 Mock Search Tool**

创建 `src/pmaa/tools/search_tool.py`：

```python
from pmaa.schemas.task import Source


def mock_search(query: str) -> list[Source]:
    return [
        Source(
            title=f"Overview for {query}",
            url="https://example.com/overview",
            snippet=f"High-level background information about {query}.",
        ),
        Source(
            title=f"Practical guide for {query}",
            url="https://example.com/guide",
            snippet=f"Implementation-oriented notes about {query}.",
        ),
    ]
```

- [ ] **步骤 5：运行测试，确认通过**

运行：

```powershell
pytest tests/test_tool_registry.py -v
```

预期：通过。

---

## 5. 任务四：Agent 与工作流

**文件：**
- 创建：`src/pmaa/agents/supervisor.py`
- 创建：`src/pmaa/agents/search.py`
- 创建：`src/pmaa/agents/writer.py`
- 创建：`src/pmaa/agents/reflection.py`
- 创建：`src/pmaa/workflow/state.py`
- 创建：`src/pmaa/workflow/graph.py`
- 创建：`tests/test_workflow.py`

- [ ] **步骤 1：先写失败测试**

创建 `tests/test_workflow.py`：

```python
from pmaa.workflow.graph import run_workflow


def test_workflow_returns_answer_sources_and_events():
    result = run_workflow("帮我研究 LangGraph 的核心概念，并生成学习路线")

    assert result.final_result is not None
    assert "LangGraph" in result.final_result.answer
    assert result.final_result.sources
    assert result.final_result.reflection.passed is True
    assert [event.agent for event in result.events] == [
        "supervisor",
        "planner",
        "search",
        "writer",
        "reflection",
        "supervisor",
    ]
```

- [ ] **步骤 2：运行测试，确认失败**

运行：

```powershell
pytest tests/test_workflow.py -v
```

预期：失败，原因是 `pmaa.workflow.graph` 尚不存在。

- [ ] **步骤 3：实现 Supervisor Agent**

创建 `src/pmaa/agents/supervisor.py`：

```python
from pmaa.schemas.task import FinalResult


class SupervisorAgent:
    name = "supervisor"

    def should_plan(self, user_input: str) -> bool:
        return len(user_input.strip()) > 8

    def finalize(self, result: FinalResult) -> FinalResult:
        return result
```

- [ ] **步骤 4：实现 Search Agent**

创建 `src/pmaa/agents/search.py`：

```python
from pmaa.schemas.task import ExecutionPlan, Source
from pmaa.tools.registry import ToolRegistry


class SearchAgent:
    name = "search"

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def search(self, plan: ExecutionPlan) -> list[Source]:
        query = plan.goal
        return self._registry.call("search", query)
```

- [ ] **步骤 5：实现 Writer Agent**

创建 `src/pmaa/agents/writer.py`：

```python
from pmaa.schemas.task import ExecutionPlan, Source


class WriterAgent:
    name = "writer"

    def write(self, plan: ExecutionPlan, sources: list[Source]) -> str:
        source_lines = "\n".join(
            f"- [{source.title}]({source.url}): {source.snippet}"
            for source in sources
        )
        return (
            f"# {plan.goal}\n\n"
            "## Summary\n\n"
            f"This report summarizes the key points for: {plan.goal}\n\n"
            "## Suggested Learning Path\n\n"
            "1. Understand the core concepts.\n"
            "2. Read implementation examples.\n"
            "3. Build a small workflow demo.\n"
            "4. Review limitations and retry strategy.\n\n"
            "## Sources\n\n"
            f"{source_lines}"
        )
```

- [ ] **步骤 6：实现 Reflection Agent**

创建 `src/pmaa/agents/reflection.py`：

```python
from pmaa.schemas.task import ReflectionResult, Source


class ReflectionAgent:
    name = "reflection"

    def reflect(self, user_input: str, answer: str, sources: list[Source]) -> ReflectionResult:
        issues: list[str] = []
        if not answer.strip():
            issues.append("Answer is empty.")
        if not sources:
            issues.append("No sources were used.")
        if user_input.strip() and user_input.strip()[:8] not in answer:
            issues.append("Answer may not be specific enough to the user request.")

        return ReflectionResult(
            passed=not issues,
            issues=issues,
            suggested_fix="Add missing sources or rewrite the answer with more task-specific details." if issues else "",
            need_retry=bool(issues),
        )
```

- [ ] **步骤 7：实现工作流状态**

创建 `src/pmaa/workflow/state.py`：

```python
from pydantic import BaseModel, Field

from pmaa.schemas.task import AgentEvent, ExecutionPlan, FinalResult, Source


class WorkflowResult(BaseModel):
    user_input: str
    plan: ExecutionPlan | None = None
    sources: list[Source] = Field(default_factory=list)
    draft_answer: str = ""
    final_result: FinalResult | None = None
    events: list[AgentEvent] = Field(default_factory=list)
```

- [ ] **步骤 8：实现工作流执行器**

创建 `src/pmaa/workflow/graph.py`：

```python
from uuid import uuid4

from pmaa.agents.planner import PlannerAgent
from pmaa.agents.reflection import ReflectionAgent
from pmaa.agents.search import SearchAgent
from pmaa.agents.supervisor import SupervisorAgent
from pmaa.agents.writer import WriterAgent
from pmaa.schemas.task import AgentEvent, FinalResult
from pmaa.tools.registry import ToolRegistry
from pmaa.tools.search_tool import mock_search
from pmaa.workflow.state import WorkflowResult


def _event(task_id: str, agent: str, event_type: str, output: dict) -> AgentEvent:
    return AgentEvent(task_id=task_id, agent=agent, event_type=event_type, output=output)


def run_workflow(user_input: str) -> WorkflowResult:
    task_id = str(uuid4())
    result = WorkflowResult(user_input=user_input)

    registry = ToolRegistry()
    registry.register("search", mock_search)

    supervisor = SupervisorAgent()
    planner = PlannerAgent()
    searcher = SearchAgent(registry)
    writer = WriterAgent()
    reflector = ReflectionAgent()

    result.events.append(_event(task_id, supervisor.name, "completed", {"should_plan": supervisor.should_plan(user_input)}))

    result.plan = planner.plan(user_input)
    result.events.append(_event(task_id, planner.name, "completed", result.plan.model_dump()))

    result.sources = searcher.search(result.plan)
    result.events.append(_event(task_id, searcher.name, "completed", {"source_count": len(result.sources)}))

    result.draft_answer = writer.write(result.plan, result.sources)
    result.events.append(_event(task_id, writer.name, "completed", {"answer_length": len(result.draft_answer)}))

    reflection = reflector.reflect(user_input, result.draft_answer, result.sources)
    result.events.append(_event(task_id, reflector.name, "completed", reflection.model_dump()))

    result.final_result = supervisor.finalize(
        FinalResult(answer=result.draft_answer, sources=result.sources, reflection=reflection)
    )
    result.events.append(_event(task_id, supervisor.name, "completed", {"status": "finalized"}))

    return result
```

- [ ] **步骤 9：运行测试，确认通过**

运行：

```powershell
pytest tests/test_workflow.py -v
```

预期：通过。

---

## 6. 任务五：FastAPI 入口与任务存储

**文件：**
- 创建：`src/pmaa/config.py`
- 创建：`src/pmaa/storage/task_store.py`
- 创建：`src/pmaa/api/routes.py`
- 创建：`src/pmaa/main.py`
- 创建：`tests/test_api.py`

- [ ] **步骤 1：先写失败测试**

创建 `tests/test_api.py`：

```python
from fastapi.testclient import TestClient

from pmaa.main import app


def test_create_task_returns_completed_workflow_result():
    client = TestClient(app)

    response = client.post(
        "/api/tasks",
        json={"user_input": "帮我研究 LangGraph 的核心概念，并生成学习路线"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["result"]["answer"]
    assert body["result"]["reflection"]["passed"] is True
```

- [ ] **步骤 2：运行测试，确认失败**

运行：

```powershell
pytest tests/test_api.py -v
```

预期：失败，原因是 `pmaa.main` 尚不存在。

- [ ] **步骤 3：实现配置模块**

创建 `src/pmaa/config.py`：

```python
from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "PMAA"
    app_env: str = "local"
    llm_provider: str = "mock"
    search_provider: str = "mock"
    max_reflection_retries: int = 1


settings = Settings()
```

- [ ] **步骤 4：实现任务存储**

创建 `src/pmaa/storage/task_store.py`：

```python
from pmaa.schemas.task import Task


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def save(self, task: Task) -> Task:
        self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)


task_store = TaskStore()
```

- [ ] **步骤 5：实现 API 路由**

创建 `src/pmaa/api/routes.py`：

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pmaa.schemas.task import Task, TaskStatus
from pmaa.storage.task_store import task_store
from pmaa.workflow.graph import run_workflow


router = APIRouter(prefix="/api")


class CreateTaskRequest(BaseModel):
    user_input: str


@router.post("/tasks", response_model=Task)
def create_task(request: CreateTaskRequest) -> Task:
    task = Task(user_input=request.user_input, status=TaskStatus.RUNNING)
    workflow_result = run_workflow(request.user_input)
    task.result = workflow_result.final_result
    task.status = TaskStatus.COMPLETED
    return task_store.save(task)


@router.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: str) -> Task:
    task = task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
```

- [ ] **步骤 6：实现 FastAPI 应用**

创建 `src/pmaa/main.py`：

```python
from fastapi import FastAPI

from pmaa.api.routes import router
from pmaa.config import settings


app = FastAPI(title=settings.app_name)
app.include_router(router)
```

- [ ] **步骤 7：运行测试，确认通过**

运行：

```powershell
pytest tests/test_api.py -v
```

预期：通过。

---

## 7. 任务六：完整验证

**文件：**
- 验证前面所有任务创建的文件。

- [ ] **步骤 1：运行全部测试**

运行：

```powershell
pytest -v
```

预期：全部测试通过。

- [ ] **步骤 2：启动 API 服务**

运行：

```powershell
uv run uvicorn pmaa.main:app --reload
```

预期：

```text
Uvicorn running on http://127.0.0.1:8000
```

- [ ] **步骤 3：调用演示接口**

另开终端运行：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/tasks `
  -ContentType "application/json" `
  -Body '{"user_input":"帮我研究 LangGraph 的核心概念，并生成学习路线"}'
```

预期：

- `status` 为 `completed`
- `result.answer` 非空
- `result.sources` 至少有一条
- `result.reflection.passed` 为 `true`

- [ ] **步骤 4：检查 v1 范围一致性**

运行：

```powershell
Select-String -Path README.md, docs\requirements.md -Pattern "Knowledge Agent","RAG","Memory Agent"
```

预期：这些内容只出现在后续路线或非 v1 范围中，不作为 v1 必做功能。

---

## 8. 自查结论

需求覆盖：

- 5 个 Agent MVP：任务二、任务四覆盖。
- Tool Registry：任务三覆盖。
- FastAPI API：任务五覆盖。
- 工作流状态和事件追踪：任务四覆盖。
- 中文 README 和启动说明：任务一覆盖。
- 测试：任务二到任务六覆盖。

范围控制：

- Knowledge Agent、RAG、Memory Agent、MCP 不进入 v1 代码，只作为路线图能力保留。
- v1 已使用 LangGraph StateGraph 编排核心工作流，后续可继续增加条件分支、checkpoint 和 retry。

文档要求：

- 项目说明文档使用中文。
- 代码标识符保持英文，便于工程维护。
