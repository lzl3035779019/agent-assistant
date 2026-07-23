from pmaa.ui.chat_render import (
    build_policy_card_markdown,
    build_thought_text,
    normalize_markdown_content,
    render_assistant_message,
)


def test_build_policy_card_markdown_summarizes_policy_decision():
    markdown = build_policy_card_markdown(
        {
            "events": [
                {
                    "agent": "supervisor",
                    "label": "Supervisor",
                    "event_type": "completed",
                    "output": {
                        "intent": "personal_fact_statement",
                        "task_kind": "conversation",
                        "execution_mode": "direct_answer",
                        "need_memory": True,
                        "need_tools": False,
                        "required_tool": "none",
                        "should_plan": False,
                        "requires_confirmation": False,
                        "risk_level": "low",
                        "confidence": 0.94,
                        "reason": "由 Memory Agent 判断是否保存。",
                    },
                }
            ]
        }
    )

    assert "策略决策" in markdown
    assert "personal_fact_statement" in markdown
    assert "Memory 参与" in markdown
    assert "low" in markdown


def test_build_thought_text_formats_policy_event_without_json_blob():
    text = build_thought_text(
        {
            "events": [
                {
                    "agent": "supervisor",
                    "label": "Supervisor",
                    "event_type": "completed",
                    "output": {
                        "intent": "model_identity",
                        "task_kind": "self_status",
                        "execution_mode": "direct_answer",
                        "need_memory": False,
                        "need_tools": False,
                        "required_tool": "none",
                        "should_plan": False,
                        "requires_confirmation": False,
                        "risk_level": "low",
                        "confidence": 0.99,
                        "reason": "用户询问系统自身模型信息。",
                    },
                }
            ]
        }
    )

    assert "策略决策" in text
    assert "intent: model_identity" in text
    assert '{"intent"' not in text


def test_build_supervisor_card_for_multi_agent_decision():
    view = {
        "events": [
            {
                "agent": "supervisor",
                "label": "Supervisor",
                "event_type": "decision_completed",
                "output": {
                    "intent": "parallel_research",
                    "mode": "delegate",
                    "tasks": [
                        {"assigned_to": "web_research"},
                        {"assigned_to": "memory"},
                    ],
                    "direct_tool": "none",
                    "requires_confirmation": False,
                    "confidence": 0.95,
                    "reason": "需要联网证据与用户偏好。",
                },
            }
        ]
    }

    markdown = build_policy_card_markdown(view)
    thought = build_thought_text(view)

    assert "Supervisor 决策" in markdown
    assert "web_research、memory" in markdown
    assert "mode: delegate" in thought
    assert "assigned_agents: ['web_research', 'memory']" in thought


def test_render_assistant_message_places_thought_before_answer_inside_box():
    html = render_assistant_message(
        "# 标题\n\n- 项目",
        view={
            "events": [
                {
                    "label": "Supervisor",
                    "event_type": "completed",
                    "output": {"intent": "direct_answer"},
                }
            ]
        },
    )

    assert '<div class="answer-box">' in html
    assert '<details class="thought-details" open>' in html
    assert "<h1>标题</h1>" in html
    assert html.index("thought-details") < html.index("answer-content")


def test_normalize_markdown_content_strips_legacy_html_wrapper():
    content = """
    <div class="answer-box">
      <details class="thought-details"><summary>思考过程</summary><pre>trace</pre></details>
      <div class="answer-content">你好，我是 PMAA。</div>
    </div>
    """

    normalized = normalize_markdown_content(content)

    assert "<div" not in normalized
    assert "trace" not in normalized
    assert "你好，我是 PMAA。" in normalized
