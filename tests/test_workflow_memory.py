from pmaa.agents.memory import MemoryAgent
from pmaa.storage.memory_store import SQLiteMemoryStore
from pmaa.workflow.graph import run_workflow


def test_workflow_memory_agent_retrieves_and_updates_long_term_memory(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    memory_agent = MemoryAgent(store)

    first = run_workflow(
        "我希望你以后回答简洁一点",
        memory_agent=memory_agent,
        enable_memory=True,
    )

    assert first.final_result is not None
    assert store.list_all()
    assert [event.agent for event in first.events].count("memory") == 2
    assert first.events[0].agent == "memory"
    assert first.events[-1].agent == "memory"
    assert first.events[-1].output["saved_count"] == 1

    second = run_workflow(
        "回答风格是什么",
        memory_agent=memory_agent,
        enable_memory=True,
    )

    assert second.events[0].agent == "memory"
    assert second.events[0].output["retrieved_count"] == 1
    assert "长期记忆" in second.conversation_context


def test_memory_write_request_does_not_call_search_tool(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    memory_agent = MemoryAgent(store)

    result = run_workflow(
        "我叫小林，写到记忆里去",
        memory_agent=memory_agent,
        enable_memory=True,
    )

    assert result.final_result is not None
    assert result.plan is None
    assert result.sources == []
    assert "tool" not in [event.agent for event in result.events]
    assert result.events[1].output["intent"] == "personal_fact_statement"
    assert result.events[1].output["need_memory"] is True
    assert result.events[1].output["execution_mode"] == "direct_answer"
    assert result.events[-1].agent == "memory"
    assert result.events[-1].output["saved_count"] == 1
    assert store.list_all()[0].type == "profile"
    assert "小林" in store.list_all()[0].content
