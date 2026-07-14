from pmaa.storage.history_store import TaskHistoryRecord
from pmaa.ui.export import build_bulk_markdown_export, build_markdown_export


def test_build_markdown_export_contains_answer_sources_and_agent_summary():
    view = {
        "answer": "# 台风报告\n\n结论来自 [S1]。\n\n## 资料来源\n\n- [S1] [中央气象台](https://typhoon.nmc.cn/)",
        "sources": [
            {
                "title": "中央气象台",
                "url": "https://typhoon.nmc.cn/",
                "snippet": "台风路径信息",
            }
        ],
        "reflection": {
            "passed": True,
            "issues": [],
            "suggested_fix": "",
            "need_retry": False,
        },
        "events": [
            {"label": "Supervisor", "event_type": "completed", "output": {"should_plan": True}},
            {"label": "Search", "event_type": "completed", "output": {"source_count": 1}},
        ],
    }

    markdown = build_markdown_export("台风巴威到哪里了？", view)

    assert "# PMAA 任务报告" in markdown
    assert "台风巴威到哪里了？" in markdown
    assert "结论来自 [S1]" in markdown
    assert "- [S1] [中央气象台](https://typhoon.nmc.cn/)" in markdown
    assert "Supervisor - completed" in markdown
    assert "Search - completed" in markdown
    assert "Reflection：通过" in markdown


def test_build_markdown_export_adds_sources_when_answer_omits_source_section():
    view = {
        "answer": "# 回答\n\n这是回答。",
        "sources": [
            {
                "title": "LangGraph Docs",
                "url": "https://langchain-ai.github.io/langgraph/",
                "snippet": "StateGraph",
            }
        ],
        "reflection": {"passed": False, "issues": ["缺少引用"], "need_retry": True},
        "events": [],
    }

    markdown = build_markdown_export("LangGraph 是什么？", view)

    assert "## 资料来源" in markdown
    assert "[S1] [LangGraph Docs](https://langchain-ai.github.io/langgraph/)" in markdown
    assert "Reflection：未通过" in markdown
    assert "- 缺少引用" in markdown


def test_build_bulk_markdown_export_combines_selected_history_records():
    records = [
        TaskHistoryRecord(
            task_id="task-1",
            title="第一个任务",
            user_input="问题一",
            view={
                "answer": "# 回答一",
                "sources": [],
                "reflection": {"passed": True, "issues": []},
                "events": [],
            },
            created_at="2026-07-11T10:00:00+00:00",
        ),
        TaskHistoryRecord(
            task_id="task-2",
            title="第二个任务",
            user_input="问题二",
            view={
                "answer": "# 回答二",
                "sources": [],
                "reflection": {"passed": False, "issues": ["缺少来源"]},
                "events": [],
            },
            created_at="2026-07-11T11:00:00+00:00",
        ),
    ]

    markdown = build_bulk_markdown_export(records)

    assert "# PMAA 批量任务导出" in markdown
    assert "## 第一个任务" in markdown
    assert "## 第二个任务" in markdown
    assert "问题一" in markdown
    assert "问题二" in markdown
    assert "# 回答一" in markdown
    assert "# 回答二" in markdown
