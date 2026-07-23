from fastapi.testclient import TestClient

from pmaa.main import app
from pmaa.schemas.notification import NotificationRecord
from pmaa.storage.monitor_store import SQLiteMonitorStore
from pmaa.storage.notification_store import SQLiteNotificationStore


def test_monitor_rule_crud_and_notification_api(monkeypatch, tmp_path) -> None:
    monitor_store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    notification_store = SQLiteNotificationStore(tmp_path / "notifications.sqlite3")
    monkeypatch.setattr("pmaa.api.routes.monitor_store", monitor_store)
    monkeypatch.setattr("pmaa.api.routes.notification_store", notification_store)
    client = TestClient(app)

    created = client.post(
        "/api/monitor/rules",
        json={
            "name": "Vercel jobs",
            "target_type": "jobs",
            "target": "Vercel",
            "query": "Vercel AI jobs",
            "interval_minutes": 60,
        },
    )

    assert created.status_code == 200
    rule_id = created.json()["rule_id"]
    assert client.get("/api/monitor/rules").json()[0]["rule_id"] == rule_id
    empty_result = client.get(f"/api/monitor/rules/{rule_id}/latest-result")
    assert empty_result.status_code == 200
    assert empty_result.json()["status"] == "not_run"
    assert empty_result.json()["items"] == []

    monitor_store.save_snapshot(
        rule_id,
        [
            {
                "title": "Example update",
                "url": "https://example.com/update",
                "snippet": "A monitored change.",
            }
        ],
    )
    latest_result = client.get(f"/api/monitor/rules/{rule_id}/latest-result")
    assert latest_result.status_code == 200
    assert latest_result.json()["status"] == "completed"
    assert latest_result.json()["item_count"] == 1
    assert latest_result.json()["items"][0]["title"] == "Example update"

    updated = client.patch(
        f"/api/monitor/rules/{rule_id}",
        json={"enabled": False},
    )
    assert updated.json()["enabled"] is False
    assert client.delete(f"/api/monitor/rules/{rule_id}").json()["deleted"] is True

    count = client.get("/api/notifications/unread-count")
    assert count.status_code == 200
    assert count.json() == {"count": 0}

    notification_store.save(NotificationRecord(kind="monitor", title="监控更新"))
    notification_store.save(NotificationRecord(kind="daily_brief", title="晨间简报"))
    assert client.get(
        "/api/notifications/unread-count", params={"kind": "monitor"}
    ).json() == {"count": 1}
    assert len(
        client.get("/api/notifications", params={"kind": "daily_brief"}).json()
    ) == 1
    assert client.post(
        "/api/notifications/mark-all-read", params={"kind": "monitor"}
    ).json() == {"updated": 1}
    assert notification_store.count_unread(kind="daily_brief") == 1


def test_monitor_api_rejects_paper_target() -> None:
    response = TestClient(app).post(
        "/api/monitor/rules",
        json={
            "name": "Papers",
            "target_type": "paper",
            "target": "Agents",
            "query": "latest agent papers",
        },
    )

    assert response.status_code == 422
