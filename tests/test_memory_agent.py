from pmaa.agents.memory import MemoryAgent
from pmaa.schemas.memory import MemoryCandidate
from pmaa.storage.memory_store import SQLiteMemoryStore


def test_memory_validate_accepts_stable_preference(tmp_path):
    agent = MemoryAgent(SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    candidate = MemoryCandidate(
        type="preference",
        content="用户希望回答更简洁。",
        source="user",
        confidence=0.9,
    )

    validation = agent.validate(candidate)

    assert validation.should_save is True
    assert validation.reason == "stable_memory"


def test_memory_validate_rejects_transient_or_sensitive_content(tmp_path):
    agent = MemoryAgent(SQLiteMemoryStore(tmp_path / "memory.sqlite3"))

    transient = agent.validate(
        MemoryCandidate(
            type="profile",
            content="今天北京天气怎么样",
            source="user",
            confidence=0.9,
        )
    )
    sensitive = agent.validate(
        MemoryCandidate(
            type="profile",
            content="我的 API key 是 sk-test",
            source="user",
            confidence=0.9,
        )
    )

    assert transient.should_save is False
    assert transient.reason == "transient_or_realtime"
    assert sensitive.should_save is False
    assert sensitive.reason == "sensitive_content"


def test_memory_extract_validate_update_and_retrieve(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    agent = MemoryAgent(store)

    candidates = agent.extract("我希望你以后回答简洁一点", "好的")
    saved = agent.update(candidates)
    retrieved = agent.retrieve("回答风格")

    assert len(saved) == 1
    assert saved[0].type == "preference"
    assert "简洁" in saved[0].content
    assert retrieved
    assert retrieved[0].usage_count == 1


def test_memory_update_ignores_non_worth_saving_query(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    agent = MemoryAgent(store)

    candidates = agent.extract("给我讲一个笑话", "这是一个笑话。")
    saved = agent.update(candidates)

    assert saved == []
    assert store.list_all() == []


def test_memory_store_lists_by_type_and_deletes(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    preference = store.upsert(
        MemoryCandidate(
            type="preference",
            content="用户希望回答更简洁。",
            source="user",
            confidence=0.9,
        )
    )
    store.upsert(
        MemoryCandidate(
            type="project",
            content="项目事实：PMAA 使用 LangGraph。",
            source="user",
            confidence=0.8,
        )
    )

    preferences = store.list_by_type("preference")
    store.delete(preference.memory_id)

    assert [memory.memory_id for memory in preferences] == [preference.memory_id]
    assert store.get(preference.memory_id) is None
    assert len(store.list_all()) == 1


def test_memory_store_updates_content_type_and_confidence(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    memory = store.upsert(
        MemoryCandidate(
            type="preference",
            content="用户希望回答更简洁。",
            source="user",
            confidence=0.7,
        )
    )

    updated = store.update(
        memory.memory_id,
        memory_type="instruction",
        content="长期指令：回答保持简洁。",
        confidence=0.95,
    )

    assert updated.memory_id == memory.memory_id
    assert updated.type == "instruction"
    assert updated.content == "长期指令：回答保持简洁。"
    assert updated.confidence == 0.95
    assert updated.created_at == memory.created_at
    assert updated.updated_at >= memory.updated_at


def test_disabled_memory_is_visible_but_not_retrieved(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    memory = store.upsert(
        MemoryCandidate(
            type="preference",
            content="用户希望回答更简洁。",
            source="user",
            confidence=0.9,
        )
    )

    disabled = store.set_enabled(memory.memory_id, False)
    retrieved_disabled = store.retrieve("回答风格")

    assert disabled.enabled is False
    assert store.list_all()[0].enabled is False
    assert store.list_by_enabled(False)[0].memory_id == memory.memory_id
    assert retrieved_disabled == []

    enabled = store.set_enabled(memory.memory_id, True)
    retrieved_enabled = store.retrieve("回答风格")

    assert enabled.enabled is True
    assert retrieved_enabled
