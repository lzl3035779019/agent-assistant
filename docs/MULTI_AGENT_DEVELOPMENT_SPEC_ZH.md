# PMAA 多 Agent 重构开发规格

> 文档状态：第一版设计基线  
> 开发分支：`codex/multi-agent-refactor`  
> 目标项目：`agent-assistant-multi-agent`  
> 更新日期：2026-07-23

## 1. 文档目的

本文档定义 PMAA 从 Agent 工作流升级为 Supervisor 层级式多 Agent 系统的第一版开发规格，包括：

- 系统边界与角色划分；
- Supervisor 与五个子 Agent 的职责；
- 中心化通信协议；
- 每个子 Agent 的内部工作流、局部状态和工具权限；
- 并行、依赖、重试、人工确认和降级规则；
- 持久化、可观测性、安全和测试要求；
- 从原项目渐进迁移的开发顺序。

本文档是实现和验收基线。若后续修改 Agent 职责、通信协议或状态字段，应先更新本文档，再修改代码。

## 2. 第一版范围

第一版采用 Supervisor 层级架构，并确定五个子 Agent：

```text
Supervisor Agent
├─ Web Research Agent
├─ Memory Agent
├─ Email Agent
├─ Daily Brief Agent
└─ Information Monitor Agent
```

第一版明确不包含：

- 独立 Policy Agent；
- Knowledge Agent；
- Synthesis Agent；
- Critic Agent；
- Agent 之间的点对点通信；
- agent-browser 的改造或接入；
- Monitor Agent 的论文监控；
- Email Agent 内部并行分析多封邮件。

现有 GBrain Wiki 继续作为知识库工具和知识管理工作流存在，不计为子 Agent。现有 Writer 和 Reflection 可作为 Supervisor 内部的答案合成与质量检查节点保留，不计为子 Agent。

## 3. 核心架构

```text
User
  ↓
Streamlit / FastAPI
  ↓
Supervisor Agent
  ├─ 分析目标
  ├─ 生成任务与依赖
  ├─ 确定性校验
  ├─ 调度子 Agent
  ├─ 收集结果
  ├─ 补充、重试或等待确认
  └─ 合成最终回答
       │
       ├─ Web Research Agent
       ├─ Memory Agent
       ├─ Email Agent
       ├─ Daily Brief Agent
       └─ Information Monitor Agent
                ↓
        Tools / MCP / Services
```

通信采用严格中心化模式：

```text
Supervisor → AgentTask → Child Agent
Child Agent → AgentResult / AgentMessage → Supervisor
```

子 Agent 不得直接调用其他子 Agent。子 Agent需要其他能力时，必须向 Supervisor 发送 `delegation_request`。

## 4. 角色与边界

### 4.1 Supervisor Agent

Supervisor 是唯一全局调度者，负责：

- 理解用户目标；
- 判断直接回答或委派子 Agent；
- 拆分任务并建立依赖关系；
- 从 Agent Registry 选择子 Agent；
- 控制串行、并行、超时和重试；
- 校验 Agent、工具、风险与权限；
- 收集并检查 `AgentResult`；
- 处理 `delegation_request`、`retry_request` 和 `clarification_request`；
- 使用内部合成节点生成最终回答；
- 将副作用操作交给 Action Executor；
- 判断任务完成、部分完成或失败。

取消 Policy Agent 后，意图、风险、工具需求和确认需求由 Supervisor 的分析阶段产生，但必须经过确定性代码校验，不能完全信任 LLM 输出。

Supervisor 内部流程：

```text
analyze_request
  ↓
build_execution_plan
  ↓
validate_plan
  ↓
dispatch_tasks
  ↓
collect_results
  ↓
evaluate_completion
  ├─ retry / delegate
  ├─ wait_confirmation
  ├─ partial
  └─ synthesize_answer
```

### 4.2 子 Agent

每个子 Agent 必须具备：

- 独立且稳定的业务目标；
- 独立系统提示词；
- 独立局部状态；
- 明确的工具白名单；
- 接收统一 `AgentTask`；
- 返回统一 `AgentResult`；
- 可以向 Supervisor 发送结构化请求；
- 有自己的停止、重试和降级条件；
- 不直接修改其他 Agent 的状态。

### 4.3 非 Agent 组件

以下组件不是 Agent：

- Tavily MCP；
- GBrain MCP；
- IMAP、SMTP；
- GitHub API、RSS/Atom Connector；
- Calendar Tool；
- Skills Registry；
- Scheduler；
- Notification Service；
- Action Executor；
- 数据库、缓存和文件系统。

## 5. 中心化通信协议

### 5.1 AgentTask

```python
class AgentTask(BaseModel):
    task_id: str
    parent_task_id: str | None = None
    trace_id: str

    assigned_to: str
    objective: str
    context: dict
    constraints: list[str]
    allowed_tools: list[str]
    expected_output: str
    depends_on: list[str]

    priority: int = 5
    timeout_seconds: int = 60
    retry_count: int = 0
    max_retries: int = 2
```

约束：

- `assigned_to` 必须存在于 Agent Registry；
- `allowed_tools` 必须是目标 Agent 白名单的子集；
- `context` 只包含执行任务所需的最小上下文；
- 不向子 Agent 暴露完整长期记忆、邮箱授权码或其他密钥；
- `expected_output` 必须说明结果 Schema 和验收条件。

### 5.2 AgentMessage

```python
class AgentMessage(BaseModel):
    message_id: str
    trace_id: str
    task_id: str

    sender: str
    receiver: str
    message_type: str
    payload: dict
    created_at: datetime
```

第一版消息类型：

```text
task_progress
delegation_request
retry_request
clarification_request
evidence
conflict
error
```

规则：

- `receiver` 第一版只能是 `supervisor`；
- Supervisor 是唯一能够创建新 `AgentTask` 的角色；
- 消息保存结构化摘要，不保存模型原始思维链；
- `delegation_request` 只是请求，Supervisor 可以接受或拒绝。

### 5.3 AgentResult

```python
class AgentResult(BaseModel):
    task_id: str
    agent_id: str
    status: str

    summary: str
    data: dict
    evidence: list[dict]
    confidence: float

    gaps: list[str]
    errors: list[str]
    retryable: bool = False
    metrics: dict = {}
```

状态值：

```text
pending
running
waiting_dependency
waiting_confirmation
completed
partial
failed
cancelled
```

### 5.4 PendingAction 与 ActionResult

```python
class PendingAction(BaseModel):
    action_id: str
    trace_id: str
    action_type: str
    permission_level: str
    immutable_payload: dict
    idempotency_key: str
    requires_confirmation: bool


class ActionResult(BaseModel):
    action_id: str
    status: str
    summary: str
    external_reference: str | None = None
    error: str | None = None
```

涉及发送、删除、修改和外部写入的动作只能由 Action Executor 执行。用户确认后必须执行已经确认的不可变参数，不能让 LLM 再次生成正文或目标地址。

## 6. 全局状态与 Blackboard

```python
class MultiAgentState(TypedDict):
    trace_id: str
    user_request: str
    conversation_id: str

    tasks: dict[str, AgentTask]
    messages: Annotated[list[AgentMessage], operator.add]
    results: Annotated[list[AgentResult], operator.add]
    evidence: Annotated[list[dict], operator.add]

    supervisor_decision: dict | None
    pending_action: PendingAction | None
    final_answer: str | None
    status: str
```

Blackboard 由 Supervisor 管理：

- 子 Agent只获得任务上下文快照；
- 子 Agent 不读取其他 Agent 的局部状态；
- 子 Agent 返回结果后，由运行时追加到 Blackboard；
- 并行分支只能追加带 reducer 的字段，不能覆盖同一普通字段；
- Supervisor 可以将某个结果的必要部分放入后续任务的 `context`。

## 7. Agent Registry

```python
class AgentSpec(BaseModel):
    agent_id: str
    name: str
    description: str
    supported_tasks: list[str]
    allowed_tools: list[str]
    supports_parallel_dispatch: bool
    default_timeout_seconds: int
    max_retries: int
    input_schema: str
    output_schema: str
    enabled: bool = True
```

Supervisor 只能调度 Registry 中已启用的 Agent。LLM 产生的 Agent 名称、工具名称和参数必须经过 Registry 校验。

## 8. Web Research Agent

### 8.1 目标

从互联网获取实时、可信、可引用的信息，形成覆盖研究目标的证据集。

### 8.2 调用场景

- 用户明确要求联网查询；
- 查询包含实时新闻、价格、天气、招聘或近期变化；
- Supervisor 需要外部资料完成研究任务；
- 其他子 Agent通过 Supervisor 请求外部证据。

### 8.3 工具权限

第一版只允许：

- Tavily MCP 搜索。

第一版不使用 agent-browser。

### 8.4 内部工作流

```text
分析目标
  ↓
拆分研究维度
  ↓
生成查询
  ↓
并行搜索不同维度
  ↓
清洗、去重和证据评分
  ↓
检查覆盖度
  ├─ 不充分：针对缺口生成补充查询
  └─ 充分：形成研究结果
```

并行仅用于互相独立的搜索维度。每轮并发数、总查询数和最大迭代次数必须受预算控制。

### 8.5 局部状态

```python
class WebResearchState(TypedDict):
    task: AgentTask
    research_aspects: list[str]
    queries: list[dict]
    evidence: list[dict]
    coverage: dict[str, float]
    missing_aspects: list[str]
    iteration: int
    max_iterations: int
    search_budget: int
    status: str
```

### 8.6 证据检查

- 相关性；
- 权威性；
- 时效性；
- 来源独立性；
- URL 可追溯性；
- 研究维度覆盖度；
- 来源之间是否冲突。

停止条件：

- 关键维度达到覆盖阈值，且关键结论有足够独立来源；或
- 达到最大迭代次数、超时或搜索预算。

### 8.7 输出要求

`AgentResult.data` 至少包含：

```text
findings
evidence
missing_aspects
conflicts
```

每条 Evidence 至少包含标题、URL、摘要、来源类型、发布日期和相关度。无法确认发布日期时必须明确标记。

## 9. Memory Agent

### 9.1 目标

在任务开始前提供相关长期记忆，并在任务完成后提取、验证和维护值得保存的用户信息。

Memory Agent 有两个模式：

```text
retrieve
consolidate
```

### 9.2 retrieve 工作流

```text
接收 AgentTask
  ↓
判断当前任务需要哪些记忆
  ↓
生成检索条件
  ↓
检索用户资料、偏好、约束、目标和项目
  ↓
相关度、时效性和置信度排序
  ↓
处理冲突与过期内容
  ↓
返回 MemoryContext
```

只返回与当前任务有关的最小记忆集合，不向其他 Agent 暴露全部长期记忆。

### 9.3 consolidate 工作流

```text
接收本轮对话和执行结果
  ↓
extract：提取候选记忆
  ↓
validate：判断是否值得保存
  ↓
检索已有相关记忆
  ↓
compare：比较新旧记忆
  ├─ ADD
  ├─ UPDATE
  ├─ MERGE
  ├─ IGNORE
  ├─ CONFLICT
  └─ DELETE
  ↓
隐私与权限校验
  ↓
Memory Store 执行写入
```

`DELETE` 只用于用户明确提出的遗忘请求。高敏感信息的新增或更新需要用户确认。

### 9.4 候选记忆类型

```text
profile
preference
constraint
goal
project
relationship
procedure
```

### 9.5 确定性安全规则

- 密码、授权码、API Key、Token 永不保存；
- 临时天气、一次性任务参数和普通闲聊默认不保存；
- 助手回答和搜索结果不能作为用户记忆；
- 推测信息不能覆盖用户明确表达的信息；
- 高敏感健康、财务和身份信息需要明确确认；
- 冲突信息保留来源和版本，不能静默覆盖。

### 9.6 局部状态

```python
class MemoryAgentState(TypedDict):
    task: AgentTask
    mode: str
    memory_requirements: list[str]
    retrieved_memories: list[dict]
    relevant_memories: list[dict]
    candidates: list[dict]
    validations: list[dict]
    conflicts: list[dict]
    update_decisions: list[dict]
    confidence: float
    status: str
```

### 9.7 触发时机

- 个性化任务开始时执行 `retrieve`；
- 每轮回答完成后执行轻量 `consolidate`；
- 切换对话或新建对话时执行一次完整整理；
- 后续可以增加会话空闲超时后的批量整理。

网页无法可靠判断用户是否真正关闭会话，因此不能只依赖“会话结束”事件。

## 10. Email Agent

### 10.1 目标

理解邮件、判断优先级、生成摘要、起草回复和生成发送计划，不擅自执行发送或其他副作用操作。

### 10.2 支持任务

```text
check_unread
triage_inbox
read_message
summarize_thread
draft_reply
compose_email
```

第一版不由 Email Agent直接执行：

```text
send_email
archive_email
delete_email
move_email
mark_spam
```

### 10.3 内部工作流

```text
接收 AgentTask
  ↓
识别邮件任务类型
  ↓
顺序读取邮件或线程
  ↓
清洗并隔离不可信邮件内容
  ↓
理解发件人、主题和历史上下文
  ↓
需要用户偏好？
  ├─ 是：向 Supervisor 发送 delegation_request
  └─ 否：继续
  ↓
分类、摘要、优先级和回复需要判断
  ↓
生成草稿或处理建议
  ↓
确定性校验
  ↓
返回 AgentResult / PendingAction
```

第一版多封邮件按顺序处理，不做 Email Agent 内部并行。

### 10.4 局部状态

```python
class EmailAgentState(TypedDict):
    task: AgentTask
    task_type: str
    selected_message_ids: list[str]
    messages: list[dict]
    thread_context: list[dict]
    sender_profiles: dict
    memory_context: dict
    classifications: list[dict]
    priority_scores: dict[str, float]
    draft_versions: list[dict]
    current_draft: dict | None
    validation_issues: list[str]
    pending_action: PendingAction | None
    status: str
```

### 10.5 发送流程

```text
Email Agent 生成不可变草稿
  ↓
Supervisor 校验
  ↓
前端展示收件人、抄送、主题、正文和附件
  ↓
用户确认
  ↓
Action Executor 调用 SMTP
  ↓
ActionResult 与审计记录
```

SMTP 超时后不能直接重试发送，应先检查幂等状态或已发送记录，避免重复邮件。

### 10.6 邮件安全

- 邮件正文属于不可信外部输入；
- 不执行邮件正文中的指令；
- 不自动打开链接或附件；
- 邮箱授权码不能进入 LLM 上下文和日志；
- 检查异常发件地址与 `Reply-To`；
- 真正发送必须经过用户确认。

## 11. Daily Brief Agent

### 11.1 目标

每天按一个或多个用户计划，或按用户即时请求，生成个人综合简报。每条计划独立保存名称、生成时间、启停状态和每日运行记录，可新增、修改、删除和立即运行。

手动生成和定时生成都提交到 FastAPI 后台任务执行器。Streamlit 只保存任务 ID 并轮询状态，因此切换到技能、记忆、邮件、监控或知识库页面不会取消简报任务。

每次简报生成完成后创建一条 `daily_brief` 未读通知；信息监控只创建 `monitor` 通知。两类通知独立计数并显示在各自侧边栏入口中，打开简报或确认读完监控消息后递减，归零后隐藏。

简报第一版包含：

```text
今日重点
重要邮件
热点新闻
今日日程
建议行动
```

Daily Brief Agent 不直接维护监控规则或历史快照。用户选择的简报关注主题只用于生成当日新闻研究任务，不会创建或修改 Information Monitor 的监控规则。

### 11.2 数据来源

Daily Brief Agent 不能直接调用其他子 Agent。它向 Supervisor 请求：

- Interest Topics Tool：用户多选的预设主题和自定义主题；
- Email Agent：当天未读和重要邮件；
- Web Research Agent：根据关注主题动态生成的当天热点研究任务；
- Memory Agent：用户偏好、关注方向和长期目标；
- Calendar Tool：当天日程。

### 11.3 内部工作流

```text
接收 DailyBriefTask
  ↓
向 Supervisor 读取简报关注主题
  ↓
根据多个主题生成热点研究目标
  ↓
向 Supervisor 申请邮件、热点、记忆和日程依赖
  ↓
waiting_dependency
  ↓
Supervisor 返回依赖结果并恢复任务
  ↓
检查数据完整性
  ↓
提取候选事项
  ↓
去重、排序和过滤低价值内容
  ↓
生成简报栏目
  ↓
检查时效性与来源
  ↓
返回 DailyBriefResult
```

### 11.4 局部状态

```python
class DailyBriefState(TypedDict):
    task: AgentTask
    brief_date: str
    timezone: str
    brief_config: dict
    interest_topics: list[dict]
    required_inputs: list[dict]
    dependency_results: dict[str, AgentResult]
    memory_context: dict
    email_items: list[dict]
    research_items: list[dict]
    calendar_items: list[dict]
    candidates: list[dict]
    selected_items: list[dict]
    sections: list[dict]
    missing_sources: list[str]
    draft: str
    confidence: float
    status: str
```

### 11.5 排序原则

第一版采用确定性评分与 LLM 语义判断结合：

```text
紧急程度       30%
与用户目标相关 25%
可行动性       20%
信息新颖性     15%
证据可信度     10%
```

部分数据源失败时返回 `partial`，不能让整个简报失败。简报只能读取和建议，不能自动发送邮件、修改日程或写入其他系统。

### 11.6 触发方式

- 用户在对话中请求生成；
- 用户在主动助手页面手动生成；
- Scheduler 在配置时间产生 `daily_brief_requested` 事件。

Agent 本身不负责定时。

## 12. Information Monitor Agent

### 12.1 目标

长期追踪用户明确指定的公司、招聘、新闻、GitHub 项目和技术博客，识别重要变化并生成提醒。

第一版监控范围：

- 指定公司动态；
- 指定公司招聘；
- 指定公司的相关新闻；
- 指定 GitHub 仓库；
- 指定技术博客；
- 指定产品或技术关键词。

第一版不监控论文。

### 12.2 与 Daily Brief 的边界

| 对比项 | Monitor Agent | Daily Brief Agent |
|---|---|---|
| 目标 | 追踪指定目标变化 | 生成当天综合摘要 |
| 触发 | 每条规则独立定时 | 每天固定时间或手动 |
| 是否需要用户配置目标 | 是 | 使用简报设置 |
| 是否保存历史快照 | 是 | 只保存简报记录 |
| 是否比较前后变化 | 是 | 默认不比较 |
| 是否处理邮件 | 否 | 是 |
| 是否处理日程 | 否 | 是 |
| 是否产生即时提醒 | 是 | 默认集中推送 |

两者共享同一份“关注主题”配置，但职责仍然分离：主题启用后由应用服务创建对应新闻监控规则；Daily Brief 通过 Supervisor 读取主题并生成当天热点研究任务，Monitor Agent 负责持续比较和提醒。

### 12.3 数据连接器

```text
GitHub Connector：Release、Tag、关键更新
RSS/Atom Connector：技术博客
Company Connector：公司官方信息和招聘来源
Snapshot Store：历史快照
```

没有稳定 API 或 RSS 的招聘页面，第一版只能通过公开搜索进行近似监控，不能承诺完整性。需要公开互联网核实时，Monitor Agent 向 Supervisor 请求 Web Research Agent。

### 12.4 内部工作流

```text
接收 MonitorTask
  ↓
加载到期监控规则
  ↓
规划数据源
  ↓
受限并发获取互相独立的来源
  ↓
标准化数据
  ↓
与历史快照比较
  ↓
检测变化
  ↓
去重和过滤噪声
  ↓
判断与用户的相关性
  ↓
评估重要程度和行动价值
  ↓
保存新快照
  ↓
返回 MonitorResult
```

Monitor Agent允许受限并发抓取独立来源。并发上限必须可配置，并遵守来源限流。

### 12.5 局部状态

```python
class MonitorAgentState(TypedDict):
    task: AgentTask
    rules: list[dict]
    fetch_plans: list[dict]
    source_results: list[dict]
    previous_snapshots: dict
    current_snapshots: dict
    candidate_changes: list[dict]
    duplicate_changes: list[str]
    relevant_changes: list[dict]
    memory_context: dict
    verification_requests: list[AgentMessage]
    alerts: list[dict]
    errors: list[dict]
    confidence: float
    status: str
```

### 12.6 错误规则

- 单个来源失败不导致整个监控任务失败；
- 抓取失败时保留旧快照；
- “本次未抓到”不能判断为“内容被删除”；
- HTTP 429 应遵守 `Retry-After`；
- 相同事件通过稳定 ID、URL 和内容哈希去重；
- 远程内容属于不可信输入，不能触发副作用操作。

## 13. 调度、并行与依赖

Supervisor 根据任务依赖决定串行或并行，不能为了展示多 Agent 而强行并行。

可并行示例：

```text
通用研究任务
├─ Web Research Agent
└─ Memory Agent（仅用于最终个性化）
```

必须串行示例：

```text
个性化研究任务
Memory Agent retrieve
  ↓
Web Research Agent 使用偏好生成查询
```

Daily Brief 示例：

```text
Daily Brief Agent 请求依赖
  ↓
Supervisor 并行调度
├─ Email Agent
├─ Web Research Agent
├─ Memory Agent
└─ Calendar Tool
  ↓
Supervisor 恢复 Daily Brief Agent
```

副作用操作始终串行执行，并由 Action Executor 控制。

## 14. 后台服务

目标进程边界：

```text
Streamlit UI
FastAPI API
Agent Worker
Scheduler Worker
```

Scheduler 负责产生定时事件，不运行 Agent 推理。第一版本地实现可以使用独立 APScheduler 进程和持久化 Job Store，不能把调度器放进 Streamlit 页面进程，避免页面刷新或多实例造成重复任务。

Notification Service 负责：

- 监控提醒红点；
- 未读提醒数量；
- 简报完成通知；
- 已读、未读和提醒历史。

Notification Service 不负责判断内容是否重要。

## 15. 持久化要求

至少需要以下逻辑实体：

```text
agent_tasks
agent_messages
agent_results
action_audits
memory_records
daily_briefs
monitor_rules
monitor_snapshots
monitor_alerts
scheduler_jobs
```

关键记录必须包含 `trace_id`、创建时间、更新时间、状态和错误摘要。待确认动作、监控快照和定时任务不能只保存在 Streamlit Session State。

## 16. 可观测性

每次用户请求或定时任务必须生成唯一 `trace_id`：

```text
request
→ supervisor_decision
→ agent_task
→ agent_started
→ tool_called
→ agent_result
→ retry / delegation / confirmation
→ final_result
```

前端可以展示：

- 调度了哪个 Agent；
- 每个 Agent 的目标；
- 使用的工具；
- 状态、耗时和重试次数；
- 证据数量和来源；
- 失败和降级原因。

前端不得展示模型原始思维链，只展示结构化执行事件和决策摘要。

## 17. 安全要求

- API Key、邮箱授权码和 Token 不进入 LLM 上下文；
- 每个 Agent 使用最小工具权限；
- 所有 LLM 生成的 Agent 名、工具名和参数都要校验；
- 外部网页、邮件、RSS 和 GitHub 内容均视为不可信输入；
- 发送邮件、删除记录、修改知识库等操作必须人工确认；
- PendingAction 使用不可变参数和幂等键；
- 日志不得记录完整密钥和敏感邮件正文；
- Memory 保存敏感信息前进行隐私校验；
- 定时任务必须限制执行次数、并发、成本和超时。

## 18. 兼容原项目

以下现有能力保留：

- Streamlit UI；
- FastAPI；
- LangGraph StateGraph；
- Tavily MCP；
- GBrain MCP；
- Skills 管理；
- QQ 邮件工具；
- Memory 存储；
- 对话历史；
- 用户确认卡片；
- Checkpoint、日志和导出能力。

迁移采用适配器方式：旧节点可以暂时包装为 `LegacyAgentAdapter` 或普通工具节点，逐个替换，不能一次性重写全部功能。

## 19. 测试与验收

### 19.1 协议测试

- AgentTask Schema 校验；
- 未注册 Agent 被拒绝；
- 越权工具被拒绝；
- AgentResult Schema 校验；
- 消息只能发给 Supervisor；
- 并行结果能够通过 reducer 合并。

### 19.2 Supervisor 测试

- 简单闲聊直接回答；
- 实时资料任务只调度 Web Research；
- 个性化任务调度 Memory；
- 邮件任务调度 Email；
- 每日简报按依赖调度多个 Agent；
- 监控定时事件只调度 Monitor；
- 子 Agent 请求补充任务时由 Supervisor 重新调度；
- 超时、失败、部分完成和取消路径正确。

### 19.3 子 Agent 测试

- 每个 Agent 的局部 State 不泄漏到全局；
- 每个 Agent 只能访问允许工具；
- Web Research 能补充检索并遵守预算；
- Memory 能区分保存、忽略、更新和冲突；
- Email 不能绕过确认直接发送；
- Daily Brief 能在部分数据源失败时降级；
- Monitor 不会因抓取失败误报删除。

### 19.4 多 Agent 验收标准

系统满足以下条件后，才对外称为多 Agent 系统：

- Supervisor 动态产生结构化 AgentTask；
- 五个子 Agent 有独立 Prompt、局部 State 和工具权限；
- 子 Agent 作为独立 LangGraph 子图运行；
- 子 Agent 返回统一 AgentResult；
- 存在真实的依赖等待、并行分发和失败重试；
- 子 Agent 能通过 Supervisor 请求其他 Agent 能力；
- 全部执行轨迹可追踪；
- 敏感动作经过确定性校验、用户确认和审计。

## 20. 实施顺序

### 阶段一：运行时与协议

1. 定义 AgentTask、AgentMessage、AgentResult；
2. 定义 AgentSpec 和 Agent Registry；
3. 定义 MultiAgentState 和 reducer；
4. 实现 Agent Runtime、Dispatcher 和 Result Collector；
5. 为协议和并行状态编写测试。

### 阶段二：Supervisor

1. 删除新架构对 Policy Agent 的依赖；
2. 将意图和任务判断并入 Supervisor；
3. 增加确定性计划校验；
4. 实现动态委派、依赖等待、重试和终止判断；
5. 保留旧工作流兼容入口。

### 阶段三：核心子 Agent

1. Web Research Agent；
2. Memory Agent；
3. Email Agent；
4. Daily Brief Agent；
5. Information Monitor Agent。

每完成一个 Agent，都应先完成单元测试和 Supervisor 集成测试，再迁移下一个。

### 阶段四：后台能力

1. Calendar Tool；
2. GitHub Connector；
3. RSS/Atom Connector；
4. Monitor Snapshot Store；
5. Scheduler Worker；
6. Notification Service。

### 阶段五：UI 与验收

1. 展示 Supervisor 和子 Agent执行事件；
2. 增加 Daily Brief 页面；
3. 增加监控规则与提醒中心；
4. 增加任务失败、部分完成和重试状态；
5. 跑完整测试集和多 Agent 场景测试。

## 21. 当前冻结决策

以下决策在第一版实现期间保持不变：

1. 使用 Supervisor 层级架构；
2. 不设置独立 Policy Agent；
3. 采用严格中心化通信；
4. 子 Agent 之间不直接调用；
5. 第一版只有五个子 Agent；
6. GBrain 作为知识工具，不设置 Knowledge Agent；
7. 暂不处理 agent-browser；
8. Email Agent 内部串行处理邮件；
9. Monitor Agent 不监控论文；
10. Monitor 与 Daily Brief 默认互不依赖；
11. 副作用操作统一由 Action Executor 执行；
12. 原项目保持不变，所有重构在新 worktree 和新分支进行。

## 22. 本地开发环境

新项目复用原项目虚拟环境：

```text
E:\langgraph_projects\agent-assistant\.venv
```

由于原虚拟环境包含指向旧项目的 editable 安装，运行新项目时必须优先设置：

```powershell
$env:PYTHONPATH='E:\langgraph_projects\agent-assistant-multi-agent\src'
```

然后使用新项目中的 `.venv` 目录链接运行测试或服务：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

不得在共享虚拟环境中重新执行会改变 editable 安装目标的 `pip install -e` 或 `uv sync`，否则可能影响原项目运行。

## 23. 当前实现状态

截至第七轮开发，已完成：

- `AgentTask`、`AgentMessage`、`AgentResult`、工具请求和确认动作协议；
- Agent Registry、工具白名单与重试上限校验；
- 中央 Blackboard，强制子 Agent 消息只能发给 Supervisor；
- 支持独立任务并发、挂起和恢复的中央 Runtime；
- 不依赖 Policy Agent 的 `HierarchicalSupervisor`；
- Agent 名称、工具权限、任务数量、循环依赖和副作用确认的确定性校验；
- 五个子 Agent 的独立注册、提示词和执行边界；
- Web Research Agent 的独立 LangGraph 子图，包括目标分析、查询生成、并行搜索、证据检查、补充检索和结构化输出；
- Memory Agent 独立 LangGraph 子图，包含检索以及提取、验证、更新两条流程；
- Email Agent 独立 LangGraph 子图，包含请求理解、权限校验、读取/起草、
  内容分析、发送计划验证和用户确认；
- Daily Brief Agent 独立 LangGraph 子图，包含中央依赖申请、输入标准化、
  信息排序、简报生成、质量检查和单次修订；
- Information Monitor Agent 独立 LangGraph 子图，包含规则管理、并行证据申请、
  历史快照比较、变化分析、快照保存和提醒输出；
- Monitor SQLite 规则库和快照库，首次运行建立基线，后续识别新增链接与同链接内容更新；
- Notification SQLite 仓库，支持未读计数、已读状态、批量已读和规则关联；
- Scheduler Worker，支持到期规则判断、后台轮询、手动触发、单规则故障隔离和运行状态；
- 定时监控以 Supervisor 系统任务进入中央 Runtime，不绕过 Blackboard 直接调用子 Agent；
- FastAPI 监控规则、调度状态和通知中心接口；
- Streamlit 信息监控页，支持规则创建、启停、删除、立即检查和通知管理；
- GitHub 只读 Connector，支持热门 AI 仓库发现、指定仓库快照、最新 Release、
  Star/Fork/Issue 等公开指标采集；
- Monitor Agent 对 GitHub 规则优先请求 `github.read`，由 Supervisor 执行工具并通过
  Blackboard 回传；非 GitHub 规则继续委派 Web Research Agent；
- GitHub 变化采用确定性降噪：新 Release 立即报告，Star 增长达到 20 或基线的 1%
  才报告，普通推送时间变化只更新快照；
- Supervisor 多 Agent Orchestrator，支持按依赖分批并发派发任务；
- Supervisor 自动消费 `delegation_request`、创建依赖任务并恢复挂起 Agent；
- 会话完成后的 Memory Agent 自动收敛；
- FastAPI `/api/multi-agent/run` 与 `/api/multi-agent/stream` 接口；
- Streamlit 聊天页接入新流式接口并展示 Supervisor 和子 Agent 轨迹；
- GBrain 继续作为 Supervisor 管理的知识工具，不计为子 Agent；
- Blackboard 的 Supervisor 工具产物通道；
- Supervisor 管理的只读 Calendar Tool 抽象，支持禁用态和本地 ICS 数据源；
- Daily Brief 通过中央 Blackboard 消费日历工具结果，不直接调用工具；
- 简报关注主题仓库，内置 AI 与大模型、Agent 与 MCP、开源 AI 项目等预设，支持多选和自定义；
- 简报关注主题通过 `interest_topics.read` 由 Supervisor 回传给 Daily Brief，与 Information Monitor 规则独立管理；
- Streamlit 分离“每日简报”和“信息监控”页面，简报聚合邮件、主题新闻、日程和长期记忆，监控只负责持续跟踪明确目标；
- SQLite 后台任务仓库与 FastAPI 线程池执行器，聊天和简报提交后立即返回任务 ID，支持跨页面轮询、进度恢复和失败状态记录；
- Daily Brief 多计划定时配置，支持同日多个生成时间、计划 CRUD、逐计划立即生成和逐计划每日去重；
- Daily Brief 与 Information Monitor 独立未读计数、侧边栏徽标和已读生命周期；
- 新架构专项测试及原项目完整回归测试。

尚未完成：

- Google Calendar OAuth 连接器；
- Monitor 的 RSS/Atom 专用 Connector；
- 多 Agent 任务依赖图和并发时间线可视化。

Calendar Tool 第一版环境变量：

```text
CALENDAR_PROVIDER=disabled|ics
CALENDAR_ICS_PATH=C:\path\to\calendar.ics
CALENDAR_TIMEZONE=Asia/Shanghai
AUTOMATION_SCHEDULER_ENABLED=false
AUTOMATION_POLL_SECONDS=60
DAILY_BRIEF_SCHEDULE_ENABLED=false
DAILY_BRIEF_SCHEDULE_TIME=08:00
GITHUB_TOKEN=
GITHUB_API_BASE_URL=https://api.github.com
GITHUB_MONITOR_MAX_RESULTS=10
```

后台调度默认关闭，避免开发环境启动后未经用户确认就持续消耗模型和搜索额度。
开启后，Worker 按规则的 `interval_minutes` 判断是否到期。首次检查只保存基线，后续
发现新增链接或同链接内容变化时才写入通知中心；单条规则失败只产生告警通知，不会终止
整个调度线程。

生产环境接入 Google Calendar 时，应新增 OAuth Connector，并保持 `calendar.read`
这一 Supervisor 工具协议不变，避免 Daily Brief 与具体日历供应商耦合。
