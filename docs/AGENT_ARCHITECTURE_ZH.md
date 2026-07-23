# PMAA 多 Agent 架构图

本文档对应当前实现，用于展示 Supervisor、中央 Blackboard 与 5 个子 Agent 的职责边界和内部 LangGraph 工作流。

## 1. 总体架构

```mermaid
flowchart TB
    U[用户 / Scheduler] --> UI[Streamlit UI]
    U --> API[FastAPI API]
    UI --> API
    API --> S[Supervisor Agent]

    S <--> B[(Central Blackboard)]
    B --- C[AgentTask / AgentMessage<br/>AgentResult / AgentEvent]

    S --> WR[Web Research Agent]
    S --> MA[Memory Agent]
    S --> EA[Email Agent]
    S --> DA[Daily Brief Agent]
    S --> IM[Information Monitor Agent]

    WR --> SEARCH[Tavily MCP]
    MA --> MEMORY[(Memory Store)]
    EA --> MAIL[QQ Mail IMAP]
    DA --> CAL[Calendar / Interest Topics]
    IM --> GH[GitHub API / Web Research]

    S --> KB[GBrain Wiki MCP]
    S --> ACTION[Action Executor]
    ACTION --> CONFIRM{用户确认}
    CONFIRM -->|允许| SIDE[SMTP 等副作用操作]
    CONFIRM -->|拒绝| STOP[取消动作]
```

系统采用中心化通信：子 Agent 只接收 Supervisor 创建的 `AgentTask`，通过 `AgentMessage` 请求补充能力，并以 `AgentResult` 返回结构化结果。子 Agent 之间不直接调用。

## 2. Supervisor 调度架构

```mermaid
flowchart LR
    REQ[用户目标] --> ANALYZE[理解目标与上下文]
    ANALYZE --> PLAN[拆分任务并建立依赖]
    PLAN --> VALIDATE{确定性校验}
    VALIDATE -->|失败| CLARIFY[澄清或拒绝]
    VALIDATE -->|通过| READY[计算就绪任务]
    READY --> DISPATCH[按依赖层并发派发]
    DISPATCH --> COLLECT[收集结果与消息]
    COLLECT --> DECIDE{完成条件}
    DECIDE -->|补充能力| PLAN
    DECIDE -->|可重试| READY
    DECIDE -->|等待确认| CONFIRM[PendingAction]
    DECIDE -->|完成或部分完成| SYNTHESIZE[聚合证据与生成回答]
    SYNTHESIZE --> RESULT[最终结果]
```

Supervisor 负责全局目标、任务依赖、Agent 选择、并发、重试、权限校验和结果聚合；子 Agent 只维护自己的局部状态。

## 3. Agent 能力边界

| Agent | 独立目标 | 局部状态 | 可选工具/能力 | 结构化输出 |
|---|---|---|---|---|
| Web Research | 获取实时、可信、可引用的互联网证据 | 研究维度、查询、证据、覆盖度、迭代预算 | Tavily MCP | 研究结论、来源、缺口、冲突、置信度 |
| Memory | 检索并维护值得长期保存的用户信息 | 模式、相关记忆、候选记忆、验证与更新决策 | Memory Store | 最小相关记忆或写入结果 |
| Email | 理解邮件、分类、摘要、起草和生成发送计划 | 邮件请求、线程、风险、草稿、待确认动作 | QQ Mail IMAP、邮件草稿工具 | 分类、摘要、草稿、风险、PendingAction |
| Daily Brief | 生成个性化当日综合简报 | 邮件、新闻、日程、记忆、栏目、质量状态 | 经 Supervisor 请求其他能力 | 简报、缺失来源、质量检查结果 |
| Information Monitor | 持续跟踪指定目标并识别重要变化 | 规则、当前证据、历史快照、变化、提醒 | GitHub API、经 Supervisor 请求 Web Research | 变化、基线、快照、提醒、置信度 |

## 4. Web Research Agent

```mermaid
flowchart LR
    START([开始]) --> A[分析研究目标]
    A --> Q[拆分维度并生成查询]
    Q --> S[线程池并发搜索]
    S --> E[清洗去重与证据评估]
    E --> ENOUGH{覆盖度与证据充分?}
    ENOUGH -->|否，预算未耗尽| GAP[识别缺口并生成补充查询]
    GAP --> S
    ENOUGH -->|是或达到预算| F[形成结构化研究结果]
    F --> END([AgentResult])
```

该 Agent 拥有独立系统提示词、研究状态和搜索预算。它不是单次搜索工具封装，而是可以根据证据缺口自主决定是否继续检索。

## 5. Memory Agent

```mermaid
flowchart TB
    START([开始]) --> ROUTE{选择模式}

    ROUTE -->|retrieve| NEED[分析当前任务所需记忆]
    NEED --> RETRIEVE[检索并按相关度排序]
    RETRIEVE --> MIN[返回最小相关记忆集合]

    ROUTE -->|consolidate| EXTRACT[从会话提取候选记忆]
    EXTRACT --> VALIDATE[价值、隐私与安全验证]
    VALIDATE --> COMPARE[与已有记忆比较]
    COMPARE --> DECISION{更新决策}
    DECISION --> ADD[ADD / UPDATE / MERGE]
    DECISION --> IGNORE[IGNORE / CONFLICT]
    ADD --> STORE[(Memory Store)]

    MIN --> END([AgentResult])
    STORE --> END
    IGNORE --> END
```

密码、Token、一次性参数和普通闲聊由确定性规则阻止写入；LLM 负责语义提取和价值判断，但不能绕过安全校验。

## 6. Email Agent

```mermaid
flowchart LR
    START([开始]) --> U[理解邮件任务]
    U --> AUTH{工具与动作授权}
    AUTH -->|不允许| FAIL[返回拒绝原因]
    AUTH -->|允许| EXEC[读取邮件 / 生成草稿]
    EXEC --> INSPECT[隔离外部内容并检查结果]
    INSPECT -->|读取类任务| ANALYZE[摘要、分类与优先级判断]
    INSPECT -->|发送准备| CHECK[校验地址、主题、正文和风险]
    ANALYZE --> RESULT[AgentResult]
    CHECK --> PENDING[生成不可变 PendingAction]
    PENDING --> SUP[返回 Supervisor]
    SUP --> CONFIRM{用户确认}
    CONFIRM -->|允许| SMTP[Action Executor 调用 SMTP]
    CONFIRM -->|拒绝| CANCEL[取消，不产生副作用]
```

Email Agent 不直接发送邮件。所有真实发送都由确定性的 Action Executor 执行，并使用用户确认过的不可变参数。

## 7. Daily Brief Agent

```mermaid
flowchart TB
    START([手动或定时触发]) --> COLLECT[检查依赖数据]
    COLLECT --> READY{依赖是否齐全?}
    READY -->|否| REQUEST[向 Supervisor 请求能力]
    REQUEST --> PARALLEL{依赖层并发调度}
    PARALLEL --> EMAIL[Email Agent]
    PARALLEL --> WEB[Web Research Agent]
    PARALLEL --> MEMORY[Memory Agent]
    PARALLEL --> CAL[Calendar / Topics Tool]
    EMAIL --> BB[(Blackboard)]
    WEB --> BB
    MEMORY --> BB
    CAL --> BB
    BB --> RESUME[Supervisor 恢复 Daily Brief Agent]
    READY -->|是| NORMALIZE[标准化与去重]
    RESUME --> NORMALIZE
    NORMALIZE --> PRIORITIZE[按紧急性、相关性和行动价值排序]
    PRIORITIZE --> COMPOSE[生成简报栏目]
    COMPOSE --> QUALITY{质量检查}
    QUALITY -->|不通过且可修订| REVISE[单次修订]
    REVISE --> QUALITY
    QUALITY -->|通过或达到上限| FINAL[保存简报并创建未读通知]
```

这里体现了跨 Agent 协作：Daily Brief Agent 只提出依赖请求，Supervisor 负责并发调度和结果回传。

## 8. Information Monitor Agent

```mermaid
flowchart LR
    START([手动或定时触发]) --> ACTION{规则管理或运行监控?}
    ACTION -->|规则管理| MANAGE[新增 / 修改 / 启停 / 删除]
    ACTION -->|运行监控| LOAD[加载到期规则]
    LOAD --> SOURCE{选择数据源}
    SOURCE --> GH[GitHub API]
    SOURCE --> WEB[经 Supervisor 委派 Web Research]
    GH --> COLLECT[标准化证据]
    WEB --> COLLECT
    COLLECT --> SNAPSHOT[读取历史快照]
    SNAPSHOT --> COMPARE[比较新增、更新与指标变化]
    COMPARE --> ANALYZE[去重、相关性与重要性判断]
    ANALYZE --> SAVE[保存新快照]
    SAVE --> ALERT{存在重要变化?}
    ALERT -->|是| NOTIFY[创建未读提醒]
    ALERT -->|否| QUIET[记录本轮状态]
```

首次运行只建立基线；抓取失败时保留旧快照，不能把“本次未抓到”误判为“内容已删除”。

## 9. 中心化通信示例

```mermaid
sequenceDiagram
    participant U as User
    participant S as Supervisor
    participant B as Blackboard
    participant D as Daily Brief Agent
    participant E as Email Agent
    participant W as Web Research Agent
    participant M as Memory Agent

    U->>S: 生成今日简报
    S->>D: AgentTask(daily_brief)
    D-->>S: delegation_request(email, news, memory)
    par 独立依赖并发执行
        S->>E: AgentTask(check_unread)
        S->>W: AgentTask(research_topics)
        S->>M: AgentTask(retrieve_preferences)
    end
    E-->>B: AgentResult
    W-->>B: AgentResult + Evidence
    M-->>B: AgentResult
    S->>D: 恢复任务并注入依赖结果
    D-->>S: DailyBriefResult
    S-->>U: 聚合后的今日简报
```

## 10. 组件边界

- **Agent**：具备独立目标、提示词、局部状态、推理步骤、工具权限和结果协议。
- **Tool / MCP**：执行确定性能力，本身不承担自主目标，例如 Tavily、GBrain、IMAP 和 GitHub API。
- **Supervisor**：创建任务、协调依赖、并发派发、处理委派请求并聚合结果。
- **Blackboard**：保存任务、消息、结果、证据和事件，不替代 Agent 推理。
- **Action Executor**：执行发送邮件等副作用动作，必须经过权限校验和用户确认。

更完整的字段定义、状态结构和验收标准见 [多 Agent 重构开发规格](MULTI_AGENT_DEVELOPMENT_SPEC_ZH.md)。
