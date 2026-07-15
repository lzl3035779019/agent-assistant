import re

from pmaa.schemas.memory import MemoryCandidate, MemoryRecord, MemoryValidation
from pmaa.storage.memory_store import SQLiteMemoryStore


class MemoryAgent:
    name = "memory"

    def __init__(self, store: SQLiteMemoryStore | None = None) -> None:
        self._store = store or SQLiteMemoryStore()

    def retrieve(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        if not query.strip():
            return []
        return self._store.retrieve(query, limit=limit)

    def extract(self, user_input: str, assistant_answer: str = "") -> list[MemoryCandidate]:
        text = user_input.strip()
        if not text:
            return []

        candidates: list[MemoryCandidate] = []
        normalized = text.lower()

        name_match = re.search(r"(?:我叫|我的名字是|我是)\s*([\u4e00-\u9fa5A-Za-z0-9_\-]{2,24})", text)
        if name_match and not self._looks_like_request(normalized):
            candidates.append(
                MemoryCandidate(
                    type="profile",
                    content=f"用户自我信息：{name_match.group(1)}",
                    source="user",
                    confidence=0.78,
                )
            )

        preference_text = self._extract_preference_text(text)
        if preference_text:
            candidates.append(
                MemoryCandidate(
                    type="preference",
                    content=self._preference_content(preference_text),
                    source="user",
                    confidence=0.86,
                )
            )

        if any(keyword in text for keyword in ["记住", "以后都", "不要再", "不要单独", "必须"]):
            candidates.append(
                MemoryCandidate(
                    type="instruction",
                    content=f"长期指令：{text}",
                    source="user",
                    confidence=0.82,
                )
            )

        if any(keyword in normalized for keyword in ["pmaa", "这个项目", "项目定位", "架构", "langgraph"]):
            if any(keyword in text for keyword in ["使用", "基于", "是", "定位", "架构"]):
                candidates.append(
                    MemoryCandidate(
                        type="project",
                        content=f"项目事实：{text}",
                        source="user",
                        confidence=0.74,
                    )
                )

        return candidates

    def validate(self, candidate: MemoryCandidate) -> MemoryValidation:
        content = candidate.content.strip()
        lowered = content.lower()
        if candidate.confidence < 0.65:
            return MemoryValidation(should_save=False, reason="low_confidence")
        if len(content) < 6:
            return MemoryValidation(should_save=False, reason="too_short")
        if self._contains_sensitive_content(lowered):
            return MemoryValidation(should_save=False, reason="sensitive_content")
        if self._contains_transient_content(lowered):
            return MemoryValidation(should_save=False, reason="transient_or_realtime")
        if self._looks_like_request(lowered):
            return MemoryValidation(should_save=False, reason="task_request")
        return MemoryValidation(should_save=True, reason="stable_memory")

    def update(self, candidates: list[MemoryCandidate]) -> list[MemoryRecord]:
        saved: list[MemoryRecord] = []
        for candidate in candidates:
            validation = self.validate(candidate)
            if validation.should_save:
                saved.append(self._store.upsert(candidate))
        return saved

    @staticmethod
    def format_memories(memories: list[MemoryRecord]) -> str:
        if not memories:
            return ""
        lines = ["长期记忆："]
        lines.extend(f"- [{memory.type}] {memory.content}" for memory in memories)
        return "\n".join(lines)

    @staticmethod
    def _preference_content(text: str) -> str:
        if "简洁" in text:
            return "用户希望回答更简洁。"
        if "详细" in text:
            return "用户希望回答更详细。"
        return f"用户偏好：{text}"

    @staticmethod
    def _extract_preference_text(text: str) -> str:
        preference_markers = ["我喜欢", "我偏好", "我希望", "以后回答", "回答简洁", "回答详细"]
        if not any(marker in text for marker in preference_markers):
            return ""
        stop_markers = [
            "你可以",
            "可以给我",
            "帮我",
            "给我",
            "请问",
            "推荐",
            "搜索",
            "查询",
            "吗",
            "？",
            "?",
        ]
        end = len(text)
        for marker in stop_markers:
            index = text.find(marker)
            if index > 0:
                end = min(end, index)
        preference = text[:end].strip(" ，,。；;")
        return preference

    @staticmethod
    def _contains_sensitive_content(lowered_content: str) -> bool:
        sensitive_keywords = [
            "api key",
            "apikey",
            "secret",
            "token",
            "password",
            "密码",
            "身份证",
            "银行卡",
            "私钥",
            "sk-",
        ]
        return any(keyword in lowered_content for keyword in sensitive_keywords)

    @staticmethod
    def _contains_transient_content(lowered_content: str) -> bool:
        transient_keywords = [
            "今天",
            "现在",
            "当前",
            "实时",
            "最新",
            "天气",
            "新闻",
            "股价",
            "台风",
            "today",
            "current",
            "latest",
            "weather",
            "news",
        ]
        return any(keyword in lowered_content for keyword in transient_keywords)

    @staticmethod
    def _looks_like_request(lowered_content: str) -> bool:
        request_keywords = [
            "怎么样",
            "是什么",
            "帮我",
            "给我",
            "讲一个",
            "查询",
            "搜索",
            "?",
            "？",
            "how ",
            "what ",
            "search",
            "find",
        ]
        return any(keyword in lowered_content for keyword in request_keywords)
