import re
from urllib.parse import urlparse

from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.schemas.task import ReflectionResult, Source


def _is_placeholder_source(source: Source) -> bool:
    host = urlparse(source.url).netloc.lower()
    title = source.title.lower()
    snippet = source.snippet.lower()
    return (
        host in {"example.com", "www.example.com"}
        or "placeholder" in title
        or snippet.strip() in {"fake", "mock", "placeholder"}
    )


def _has_source_citation(answer: str, sources: list[Source]) -> bool:
    if re.search(r"\[S\d+\]", answer):
        return True
    return any(source.url in answer for source in sources)


def _answer_mentions_request(user_input: str, answer: str) -> bool:
    stop_words = {"帮我", "请问", "查询", "研究", "怎么", "如何", "哪里", "一下"}
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", user_input)
    meaningful_tokens = [token for token in tokens if token not in stop_words]
    return not meaningful_tokens or any(token in answer for token in meaningful_tokens)


def _grounding_issues(user_input: str, answer: str, sources: list[Source]) -> list[str]:
    issues: list[str] = []
    if not answer.strip():
        issues.append("Answer is empty.")
    if not sources:
        issues.append("No sources were used.")
    if any(_is_placeholder_source(source) for source in sources):
        issues.append("发现占位资料来源 placeholder/example.com，不能作为真实联网依据。")
    if sources and not _has_source_citation(answer, sources):
        issues.append("回答缺少资料来源引用 citation，例如 [S1] 或真实 URL。")
    if user_input.strip() and not _answer_mentions_request(user_input, answer):
        issues.append("Answer may not be specific enough to the user request.")
    return issues


def _merge_issues(*issue_groups: list[str]) -> list[str]:
    merged: list[str] = []
    for issues in issue_groups:
        for issue in issues:
            if issue not in merged:
                merged.append(issue)
    return merged


class ReflectionAgent:
    name = "reflection"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client

    def reflect(
        self,
        user_input: str,
        answer: str,
        sources: list[Source],
        conversation_context: str = "",
    ) -> ReflectionResult:
        hard_issues = _grounding_issues(user_input, answer, sources)

        if self._llm_client is not None:
            source_text = "\n".join(
                f"[S{index}] {source.title} ({source.url}): {source.snippet}"
                for index, source in enumerate(sources, start=1)
            )
            try:
                payload = self._llm_client.complete_json(
                    [
                        LLMMessage(
                            role="system",
                            content=(
                                "你是 PMAA 的 Reflection Agent。"
                                "检查回答是否满足用户任务、是否引用真实资料来源、是否有明显遗漏。"
                                "如果来源是 example.com/placeholder，必须判定不通过。"
                                "只输出 JSON：passed(boolean), issues(list), "
                                "suggested_fix(string), need_retry(boolean)。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=(
                                f"历史对话上下文：\n{conversation_context.strip()}\n\n"
                                if conversation_context.strip()
                                else ""
                            )
                            + (
                                f"用户任务：{user_input}\n\n"
                                f"回答：\n{answer}\n\n"
                                f"资料来源：\n{source_text}"
                            ),
                        ),
                    ]
                )
                llm_result = ReflectionResult.model_validate(payload)
                issues = _merge_issues(hard_issues, llm_result.issues)
                return ReflectionResult(
                    passed=not issues and llm_result.passed,
                    issues=issues,
                    suggested_fix=(
                        "使用真实来源重写回答，并为关键结论添加 [S1] 这类来源引用。"
                        if issues
                        else llm_result.suggested_fix
                    ),
                    need_retry=bool(issues) or llm_result.need_retry,
                )
            except (LLMClientError, ValueError):
                pass

        return ReflectionResult(
            passed=not hard_issues,
            issues=hard_issues,
            suggested_fix=(
                "使用真实来源重写回答，并为关键结论添加 [S1] 这类来源引用。"
                if hard_issues
                else ""
            ),
            need_retry=bool(hard_issues),
        )
