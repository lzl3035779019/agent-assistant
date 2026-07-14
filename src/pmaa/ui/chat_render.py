import json
import re
from html import escape, unescape
from typing import Any


def build_thought_text(view: dict[str, Any] | None) -> str:
    if view is None:
        return "等待运行工作流。"
    lines: list[str] = []
    for index, event in enumerate(view.get("events", []), start=1):
        payload = json.dumps(event.get("output", {}), ensure_ascii=False)
        lines.append(
            f"[{index}] {event.get('label', event.get('agent', 'Agent'))} - "
            f"{event.get('event_type', 'completed')} {payload}"
        )
    return "\n".join(lines) or "暂无执行过程。"


def render_user_message(content: str) -> str:
    return f"""
    <div class="user-row">
      <div class="avatar user">U</div>
      <div class="question-card">{escape(content)}</div>
    </div>
    """


def render_assistant_message(
    content: str,
    view: dict[str, Any] | None = None,
    message_type: str = "normal",
) -> str:
    if message_type == "error":
        body = f'<div class="error-box">任务执行失败：{escape(content)}</div>'
    else:
        thought = ""
        if view is not None:
            thought = f"""
            <details class="thought-details" open>
              <summary>思考过程 / Agent 执行过程</summary>
              <pre>{escape(build_thought_text(view))}</pre>
            </details>
            """
        body = f"""
        <div class="answer-box">
          {thought}
          <div class="answer-content">{markdown_to_html(content)}</div>
        </div>
        """

    return f"""
    <div class="assistant-row">
      <div class="avatar assistant">A</div>
      {body}
    </div>
    """


def normalize_markdown_content(content: str) -> str:
    if "<div" not in content and "<details" not in content:
        return content
    text = re.sub(r"<details\b.*?</details>", "", content, flags=re.DOTALL)
    text = re.sub(r"<pre\b.*?</pre>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def markdown_to_html(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    html: list[str] = []
    in_list = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if in_list:
                html.append("</ul>")
                in_list = False
            continue

        if line.startswith("### "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h3>{_inline_markdown(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h2>{_inline_markdown(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h1>{_inline_markdown(line[2:])}</h1>")
        elif line.startswith(("- ", "* ")):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline_markdown(line[2:])}</li>")
        else:
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<p>{_inline_markdown(line)}</p>")

    if in_list:
        html.append("</ul>")
    return "\n".join(html)


def _inline_markdown(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        escaped,
    )
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped
