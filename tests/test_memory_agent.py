from pmaa.agents.memory import MemoryAgent
from pmaa.schemas.memory import MemoryCandidate
from pmaa.storage.memory_store import SQLiteMemoryStore


class StubMemoryLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete_text(self, messages):
        return ""

    def complete_json(self, messages):
        self.calls += 1
        return self.payload


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


def test_memory_validate_accepts_news_as_stable_preference(tmp_path):
    agent = MemoryAgent(SQLiteMemoryStore(tmp_path / "memory.sqlite3"))
    candidate = MemoryCandidate(
        type="preference",
        content="用户喜欢看新闻，尤其关注 AI 新闻。",
        source="user",
        confidence=0.9,
    )

    validation = agent.validate(candidate)

    assert validation.should_save is True
    assert validation.reason == "stable_memory"


def test_memory_consolidate_uses_llm_to_save_preference_from_task(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    llm = StubMemoryLLM(
        {
            "candidates": [
                {
                    "type": "preference",
                    "content": "用户喜欢看新闻，尤其关注 AI 新闻。",
                    "source": "user",
                    "confidence": 0.91,
                    "should_save": True,
                    "reason": "这是稳定兴趣偏好，不是一次性搜索任务。",
                },
                {
                    "type": "preference",
                    "content": "用户想查看今天最火的 AI 新闻。",
                    "source": "user",
                    "confidence": 0.8,
                    "should_save": False,
                    "reason": "这是当前任务请求，不应进入长期记忆。",
                },
            ]
        }
    )
    agent = MemoryAgent(store, llm_client=llm)

    candidates = agent.consolidate(
        "我喜欢看新闻，帮我找一下今天最火的与ai有关的新闻",
        "已为你找到几条 AI 新闻。",
        conversation_context="",
    )
    saved = agent.update(candidates)

    assert llm.calls == 1
    assert len(saved) == 1
    assert "喜欢看新闻" in saved[0].content
    assert "AI 新闻" in saved[0].content
    assert "今天最火" not in saved[0].content


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


def test_memory_extracts_preferences_from_mixed_request(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    agent = MemoryAgent(store)

    candidates = agent.extract(
        "我喜欢跑步打游戏，喜欢旅游，你可以给我推荐几个避暑的旅游胜地吗",
        "可以。",
    )
    saved = agent.update(candidates)

    assert len(saved) == 1
    assert saved[0].type == "preference"
    assert "跑步" in saved[0].content
    assert "游戏" in saved[0].content
    assert "旅游" in saved[0].content
    assert "推荐" not in saved[0].content


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
