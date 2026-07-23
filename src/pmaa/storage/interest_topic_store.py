from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pmaa.schemas.interest_topic import InterestTopic


PRESET_INTEREST_TOPICS = (
    InterestTopic(
        topic_id="preset-ai-llm",
        name="AI 与大模型",
        query="今天 AI 与大模型领域的重要发布、产品更新、行业动态和官方消息",
        is_preset=True,
    ),
    InterestTopic(
        topic_id="preset-agent-mcp",
        name="Agent 与 MCP",
        query="今天 AI Agent、多智能体系统、MCP 和智能工具调用领域的重要动态",
        is_preset=True,
    ),
    InterestTopic(
        topic_id="preset-open-source-ai",
        name="开源 AI 项目",
        query="今天值得关注的开源 AI 项目、GitHub 发布、版本更新和社区趋势",
        is_preset=True,
    ),
    InterestTopic(
        topic_id="preset-tech-internet",
        name="科技与互联网",
        query="今天科技与互联网行业的重要公司动态、产品发布和政策变化",
        is_preset=True,
    ),
    InterestTopic(
        topic_id="preset-jobs-career",
        name="求职与招聘",
        query="今天 AI 与软件工程领域的招聘趋势、岗位机会和求职信息",
        is_preset=True,
    ),
    InterestTopic(
        topic_id="preset-product-startup",
        name="产品与创业",
        query="今天 AI 产品、创业公司、融资和商业化方向的重要动态",
        is_preset=True,
    ),
)


class SQLiteInterestTopicStore:
    def __init__(self, db_path: str | Path = "data/pmaa_monitor.sqlite3") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._seed_presets()

    def list_topics(self, *, enabled_only: bool = False) -> list[InterestTopic]:
        query = "SELECT * FROM interest_topics"
        parameters: tuple[object, ...] = ()
        if enabled_only:
            query += " WHERE enabled = ?"
            parameters = (1,)
        query += " ORDER BY is_preset DESC, created_at ASC, name ASC"
        with self._connect() as conn:
            rows = conn.execute(query, parameters).fetchall()
        return [self._row_to_topic(row) for row in rows]

    def get_topic(self, topic_id: str) -> InterestTopic | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM interest_topics WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()
        return self._row_to_topic(row) if row else None

    def save_topic(self, topic: InterestTopic) -> InterestTopic:
        now = datetime.now(UTC).isoformat()
        existing = self.get_topic(topic.topic_id)
        saved = topic.model_copy(
            update={
                "created_at": existing.created_at if existing else topic.created_at,
                "updated_at": now,
            }
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO interest_topics
                    (topic_id, name, query, enabled, is_preset, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    saved.topic_id,
                    saved.name,
                    saved.query,
                    1 if saved.enabled else 0,
                    1 if saved.is_preset else 0,
                    saved.created_at,
                    saved.updated_at,
                ),
            )
        return saved

    def set_enabled_topics(self, topic_ids: list[str]) -> list[InterestTopic]:
        selected = set(topic_ids)
        known = {topic.topic_id for topic in self.list_topics()}
        unknown = sorted(selected - known)
        if unknown:
            raise ValueError(f"Unknown interest topics: {', '.join(unknown)}")
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE interest_topics SET enabled = 0, updated_at = ?",
                (now,),
            )
            if selected:
                placeholders = ",".join("?" for _ in selected)
                conn.execute(
                    f"UPDATE interest_topics SET enabled = 1, updated_at = ? "
                    f"WHERE topic_id IN ({placeholders})",
                    (now, *sorted(selected)),
                )
        return self.list_topics()

    def delete_topic(self, topic_id: str) -> bool:
        topic = self.get_topic(topic_id)
        if topic is None:
            return False
        if topic.is_preset:
            raise ValueError("Preset interest topics cannot be deleted.")
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM interest_topics WHERE topic_id = ?",
                (topic_id,),
            )
        return cursor.rowcount > 0

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interest_topics (
                    topic_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    query TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    is_preset INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _seed_presets(self) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO interest_topics
                    (topic_id, name, query, enabled, is_preset, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        topic.topic_id,
                        topic.name,
                        topic.query,
                        1 if topic.enabled else 0,
                        1,
                        topic.created_at,
                        topic.updated_at,
                    )
                    for topic in PRESET_INTEREST_TOPICS
                ],
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_topic(row: sqlite3.Row) -> InterestTopic:
        return InterestTopic(
            topic_id=row["topic_id"],
            name=row["name"],
            query=row["query"],
            enabled=bool(row["enabled"]),
            is_preset=bool(row["is_preset"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
