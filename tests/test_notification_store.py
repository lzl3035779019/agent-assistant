from pmaa.schemas.notification import NotificationRecord
from pmaa.storage.notification_store import SQLiteNotificationStore


def test_notification_store_tracks_unread_state(tmp_path) -> None:
    store = SQLiteNotificationStore(tmp_path / "notifications.sqlite3")
    first = store.save(
        NotificationRecord(
            kind="monitor",
            title="Vercel 有更新",
            content="新增一个岗位",
            source_agent="information_monitor",
        )
    )
    second = store.save(
        NotificationRecord(kind="system", title="任务失败", severity="warning")
    )

    assert store.count_unread() == 2
    assert store.count_unread(kind="monitor") == 1
    assert store.count_unread(kind="daily_brief") == 0
    assert [item.notification_id for item in store.list_notifications()] == [
        second.notification_id,
        first.notification_id,
    ]
    assert store.mark_read(first.notification_id) is True
    assert store.count_unread() == 1
    assert store.list_notifications(unread_only=True)[0].notification_id == second.notification_id
    assert store.mark_all_read() == 1
    assert store.count_unread() == 0
    assert store.delete(first.notification_id) is True


def test_notification_store_filters_and_marks_one_kind(tmp_path) -> None:
    store = SQLiteNotificationStore(tmp_path / "notifications.sqlite3")
    store.save(NotificationRecord(kind="monitor", title="监控更新"))
    brief = store.save(NotificationRecord(kind="daily_brief", title="晨间简报"))

    assert [item.notification_id for item in store.list_notifications(kind="daily_brief")] == [
        brief.notification_id
    ]
    assert store.mark_all_read(kind="daily_brief") == 1
    assert store.count_unread(kind="daily_brief") == 0
    assert store.count_unread(kind="monitor") == 1
