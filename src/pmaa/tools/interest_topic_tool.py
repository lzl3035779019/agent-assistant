from __future__ import annotations

from typing import Any

from pmaa.storage.interest_topic_store import SQLiteInterestTopicStore


class InterestTopicTool:
    def __init__(self, store: SQLiteInterestTopicStore | None = None) -> None:
        self.store = store or SQLiteInterestTopicStore()

    def __call__(self, request: dict[str, Any] | None = None) -> dict[str, Any]:
        topics = self.store.list_topics(enabled_only=True)
        return {
            "status": "ok",
            "topics": [topic.model_dump(mode="json") for topic in topics],
            "topic_names": [topic.name for topic in topics],
        }
