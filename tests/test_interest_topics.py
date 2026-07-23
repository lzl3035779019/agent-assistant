from fastapi.testclient import TestClient

from pmaa.main import app
from pmaa.runtime_services import (
    legacy_interest_topic_rule_id,
    remove_legacy_interest_topic_monitor_rules,
)
from pmaa.schemas.monitor import MonitorRule
from pmaa.storage.interest_topic_store import SQLiteInterestTopicStore
from pmaa.storage.monitor_store import SQLiteMonitorStore


def test_interest_topic_store_seeds_presets_and_supports_multiple_selection(tmp_path) -> None:
    store = SQLiteInterestTopicStore(tmp_path / "topics.sqlite3")

    topics = store.list_topics()
    assert len(topics) == 6
    assert all(topic.is_preset for topic in topics)
    assert not any(topic.enabled for topic in topics)

    custom = store.save_topic(
        topics[0].model_copy(
            update={
                "topic_id": "custom-multimodal",
                "name": "多模态模型",
                "query": "今天多模态模型的重要进展",
                "is_preset": False,
            }
        )
    )
    selected = store.set_enabled_topics([topics[0].topic_id, custom.topic_id])

    assert {topic.topic_id for topic in selected if topic.enabled} == {
        topics[0].topic_id,
        custom.topic_id,
    }


def test_legacy_topic_monitor_cleanup_preserves_manual_rules(tmp_path) -> None:
    topic_store = SQLiteInterestTopicStore(tmp_path / "topics.sqlite3")
    monitor_store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    topic = topic_store.list_topics()[0]
    legacy_rule = monitor_store.save_rule(
        MonitorRule(
            rule_id=legacy_interest_topic_rule_id(topic.topic_id),
            name=f"主题：{topic.name}",
            target_type="news",
            target=topic.name,
            query=topic.query,
        )
    )
    manual_rule = monitor_store.save_rule(
        MonitorRule(
            name="手动 AI 新闻监控",
            target_type="news",
            target="AI 新闻",
            query="AI 新闻的重要变化",
        )
    )

    deleted = remove_legacy_interest_topic_monitor_rules(
        topic_store=topic_store,
        rule_store=monitor_store,
    )

    assert deleted == [legacy_rule.rule_id]
    assert monitor_store.get_rule(legacy_rule.rule_id) is None
    assert monitor_store.get_rule(manual_rule.rule_id) is not None


def test_interest_topic_api_manages_brief_topics_without_monitor_side_effects(
    monkeypatch,
    tmp_path,
) -> None:
    topic_store = SQLiteInterestTopicStore(tmp_path / "topics.sqlite3")
    monitor_store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    monkeypatch.setattr("pmaa.api.routes.interest_topic_store", topic_store)
    monkeypatch.setattr("pmaa.api.routes.monitor_store", monitor_store)
    client = TestClient(app)

    presets = client.get("/api/interest-topics").json()
    created = client.post(
        "/api/interest-topics",
        json={
            "name": "多模态模型",
            "query": "今天多模态模型的重要发布和开源进展",
        },
    )
    assert created.status_code == 200
    custom = created.json()

    selected_ids = [presets[0]["topic_id"], custom["topic_id"]]
    selection = client.put(
        "/api/interest-topics/selection",
        json={"topic_ids": selected_ids},
    )
    assert selection.status_code == 200
    assert {
        topic["topic_id"] for topic in selection.json() if topic["enabled"]
    } == set(selected_ids)
    assert monitor_store.list_rules() == []

    deleted = client.delete(f"/api/interest-topics/{custom['topic_id']}")
    assert deleted.status_code == 200
    assert monitor_store.list_rules() == []


def test_interest_topic_api_does_not_delete_presets(monkeypatch, tmp_path) -> None:
    topic_store = SQLiteInterestTopicStore(tmp_path / "topics.sqlite3")
    monkeypatch.setattr("pmaa.api.routes.interest_topic_store", topic_store)
    preset = topic_store.list_topics()[0]

    response = TestClient(app).delete(f"/api/interest-topics/{preset.topic_id}")

    assert response.status_code == 400


def test_interest_topic_monitor_run_endpoint_is_removed() -> None:
    response = TestClient(app).post("/api/interest-topics/run-once")

    assert response.status_code == 405
