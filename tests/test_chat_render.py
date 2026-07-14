from pmaa.ui.chat_render import normalize_markdown_content, render_assistant_message


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
