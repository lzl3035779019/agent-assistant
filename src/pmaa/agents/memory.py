import re
from typing import Any

from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.schemas.memory import MemoryCandidate, MemoryRecord, MemoryValidation
from pmaa.storage.memory_store import SQLiteMemoryStore


class MemoryAgent:
    name = "memory"

    def __init__(
        self,
        store: SQLiteMemoryStore | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._store = store or SQLiteMemoryStore()
        self._llm_client = llm_client

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

    def consolidate(
        self,
        user_input: str,
        assistant_answer: str = "",
        conversation_context: str = "",
    ) -> list[MemoryCandidate]:
        if self._llm_client is None:
            return self.extract(user_input, assistant_answer)
        llm_candidates = self._consolidate_by_llm(
            user_input,
            assistant_answer,
            conversation_context,
        )
        if llm_candidates is None:
            return self.extract(user_input, assistant_answer)
        return llm_candidates

    def validate(self, candidate: MemoryCandidate) -> MemoryValidation:
        content = candidate.content.strip()
        lowered = content.lower()
        if candidate.confidence < 0.65:
            return MemoryValidation(should_save=False, reason="low_confidence")
        if len(content) < 6:
            return MemoryValidation(should_save=False, reason="too_short")
        if self._contains_sensitive_content(lowered):
            return MemoryValidation(should_save=False, reason="sensitive_content")
        if self._contains_transient_content(lowered, candidate.type):
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

    def _consolidate_by_llm(
        self,
        user_input: str,
        assistant_answer: str,
        conversation_context: str,
    ) -> list[MemoryCandidate] | None:
        try:
            payload = self._llm_client.complete_json(
                [
                    LLMMessage(
                        role="system",
                        content=(
                            "You are the Memory Agent for a personal multi-agent assistant. "
                            "After each assistant response, review the current turn and decide "
                            "which user-provided facts are worth saving as long-term memory. "
                            "Only save stable user facts, preferences, long-term instructions, "
                            "or project facts explicitly stated by the user. Do not save the "
                            "current task request, search results, news/weather/current facts, "
                            "assistant guesses, secrets, API keys, passwords, or sensitive IDs. "
                            "Return JSON only: {\"candidates\":[{\"type\":\"profile|preference|project|instruction\","
                            "\"content\":\"...\",\"source\":\"user\",\"confidence\":0.0,"
                            "\"should_save\":true,\"reason\":\"...\"}]}"
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            f"Conversation context:\n{conversation_context.strip() or 'None'}\n\n"
                            f"User input:\n{user_input.strip()}\n\n"
                            f"Assistant answer:\n{assistant_answer.strip() or 'None'}"
                        ),
                    ),
                ]
            )
        except (LLMClientError, ValueError, TypeError):
            return None
        return self._candidates_from_llm_payload(payload)

    @staticmethod
    def _candidates_from_llm_payload(payload: dict[str, Any]) -> list[MemoryCandidate]:
        raw_candidates = payload.get("candidates", [])
        if not isinstance(raw_candidates, list):
            return []
        candidates: list[MemoryCandidate] = []
        for raw_candidate in raw_candidates:
            if not isinstance(raw_candidate, dict):
                continue
            if raw_candidate.get("should_save") is False:
                continue
            try:
                candidates.append(
                    MemoryCandidate(
                        type=raw_candidate.get("type", "preference"),
                        content=str(raw_candidate.get("content", "")).strip(),
                        source=str(raw_candidate.get("source", "user") or "user"),
                        confidence=float(raw_candidate.get("confidence", 0.0)),
                    )
                )
            except (TypeError, ValueError):
                continue
        return candidates

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
    def _contains_transient_content(lowered_content: str, memory_type: str = "") -> bool:
        hard_transient_keywords = [
            "浠婂ぉ",
            "鐜板湪",
            "褰撳墠",
            "瀹炴椂",
            "今天",
            "现在",
            "当前",
            "实时",
            "台风",
            "today",
            "current",
        ]
        if any(keyword in lowered_content for keyword in hard_transient_keywords):
            return True
        soft_transient_keywords = [
            "鏈€鏂?",
            "澶╂皵",
            "鏂伴椈",
            "鑲′环",
            "鍙伴",
            "最新",
            "天气",
            "新闻",
            "股价",
            "latest",
            "weather",
            "news",
        ]
        stable_preference_markers = [
            "用户喜欢",
            "用户偏好",
            "用户关注",
            "我喜欢",
            "喜欢",
            "偏好",
            "关注",
        ]
        if memory_type == "preference" and any(
            marker in lowered_content for marker in stable_preference_markers
        ):
            return False
        return any(keyword in lowered_content for keyword in soft_transient_keywords)

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
