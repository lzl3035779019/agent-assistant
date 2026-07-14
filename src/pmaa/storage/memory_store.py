import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pmaa.schemas.memory import MemoryCandidate, MemoryRecord


class SQLiteMemoryStore:
    def __init__(self, db_path: str | Path = "data/pmaa_memory.sqlite3") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def upsert(self, candidate: MemoryCandidate) -> MemoryRecord:
        existing = self._find_same(candidate.type, candidate.content)
        now = datetime.now(UTC).isoformat()
        if existing is not None:
            record = existing.model_copy(
                update={
                    "confidence": max(existing.confidence, candidate.confidence),
                    "updated_at": now,
                }
            )
        else:
            record = MemoryRecord(
                type=candidate.type,
                content=candidate.content,
                source=candidate.source,
                confidence=candidate.confidence,
                created_at=now,
                updated_at=now,
            )
        self._save(record)
        return record

    def retrieve(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        query_terms = self._terms(query)
        records = [record for record in self.list_all() if record.enabled]
        scored: list[tuple[int, MemoryRecord]] = []
        for record in records:
            text = f"{record.type} {record.content}".lower()
            score = sum(1 for term in query_terms if term and term in text)
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], -item[1].confidence, item[1].updated_at))
        selected = [record for _, record in scored[:limit]]
        for record in selected:
            self.mark_used(record.memory_id)
        return [self.get(record.memory_id) or record for record in selected]

    def list_all(self) -> list[MemoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT memory_id, type, content, source, confidence, created_at,
                       updated_at, last_used_at, usage_count, enabled
                FROM memories
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_type(self, memory_type: str) -> list[MemoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT memory_id, type, content, source, confidence, created_at,
                       updated_at, last_used_at, usage_count, enabled
                FROM memories
                WHERE type = ?
                ORDER BY updated_at DESC
                """,
                (memory_type,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_enabled(self, enabled: bool) -> list[MemoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT memory_id, type, content, source, confidence, created_at,
                       updated_at, last_used_at, usage_count, enabled
                FROM memories
                WHERE enabled = ?
                ORDER BY updated_at DESC
                """,
                (1 if enabled else 0,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT memory_id, type, content, source, confidence, created_at,
                       updated_at, last_used_at, usage_count, enabled
                FROM memories
                WHERE memory_id = ?
                """,
                (memory_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def delete(self, memory_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))

    def update(
        self,
        memory_id: str,
        *,
        memory_type: str,
        content: str,
        confidence: float,
    ) -> MemoryRecord:
        current = self.get(memory_id)
        if current is None:
            raise ValueError(f"Memory does not exist: {memory_id}")
        now = datetime.now(UTC).isoformat()
        record = current.model_copy(
            update={
                "type": memory_type,
                "content": content.strip(),
                "confidence": confidence,
                "updated_at": now,
            }
        )
        self._save(record)
        return record

    def set_enabled(self, memory_id: str, enabled: bool) -> MemoryRecord:
        current = self.get(memory_id)
        if current is None:
            raise ValueError(f"Memory does not exist: {memory_id}")
        record = current.model_copy(
            update={
                "enabled": enabled,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        self._save(record)
        return record

    def mark_used(self, memory_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memories
                SET last_used_at = ?, usage_count = usage_count + 1
                WHERE memory_id = ?
                """,
                (now, memory_id),
            )

    def _save(self, record: MemoryRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memories
                    (memory_id, type, content, source, confidence, created_at,
                     updated_at, last_used_at, usage_count, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.memory_id,
                    record.type,
                    record.content,
                    record.source,
                    record.confidence,
                    record.created_at,
                    record.updated_at,
                    record.last_used_at,
                    record.usage_count,
                    1 if record.enabled else 0,
                ),
            )

    def _find_same(self, memory_type: str, content: str) -> MemoryRecord | None:
        normalized = self._normalize(content)
        for record in self.list_all():
            if record.type == memory_type and self._normalize(record.content) == normalized:
                return record
        return None

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(memories)").fetchall()
            }
            if "enabled" not in columns:
                conn.execute(
                    "ALTER TABLE memories ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            type=row["type"],
            content=row["content"],
            source=row["source"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used_at=row["last_used_at"],
            usage_count=row["usage_count"],
            enabled=bool(row["enabled"]),
        )

    @staticmethod
    def _terms(text: str) -> set[str]:
        compact = text.lower().strip()
        terms = {term for term in compact.replace("，", " ").replace("。", " ").split() if term}
        if "回答" in compact or "风格" in compact or "简洁" in compact:
            terms.update({"回答", "风格", "简洁"})
        if "项目" in compact or "pmaa" in compact:
            terms.update({"项目", "pmaa"})
        return terms

    @staticmethod
    def _normalize(text: str) -> str:
        return "".join(text.lower().split())
