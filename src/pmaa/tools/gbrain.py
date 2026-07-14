import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from pmaa.schemas.task import Source
from pmaa.tools.mcp_client import MCPClient, MCPServerConfig


_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class _MarkdownSection:
    """A source-faithful evidence unit delimited by a Markdown heading."""

    title: str
    level: int
    content: str
    normalized_content: str


class GBrainKnowledgeTool:
    def __init__(
        self,
        client: MCPClient,
        search_tool_name: str = "wiki_search",
        max_results: int = 5,
    ) -> None:
        self._client = client
        self._search_tool_name = search_tool_name
        self._max_results = max_results
        # Native GBrain chunks for Markdown currently do not carry their
        # heading/parent path.  Keep this lightweight index in the PMAA
        # process, keyed by immutable source slug, rather than guessing from
        # neighbouring chunk indexes on every query.
        self._section_cache: dict[str, list[_MarkdownSection]] = {}

    def __call__(self, query: str) -> list[Source] | dict[str, Any]:
        arguments = {
            "query": query,
            "limit": self._max_results,
        }
        # `query` is GBrain's native retrieval pipeline.  Its expansion stage
        # uses the configured GBrain expansion model to create alternative
        # phrasings, retrieves each one through hybrid search, and fuses the
        # evidence before reranking.  This is deliberately enabled so the
        # knowledge-base path benefits from GBrain rather than acting like a
        # single-vector RAG lookup.
        if self._search_tool_name == "query":
            arguments.update(
                {
                    "expand": True,
                    "detail": "high",
                    "autocut": False,
                }
            )
        result = self._client.call_tool(self._search_tool_name, arguments)
        sources = parse_gbrain_sources(result)
        # Expansion is a recall enhancer, not a reason to hide a known-good
        # native search result.  GBrain itself degrades an expansion-provider
        # failure to the original query, but an expanded candidate set can
        # still occasionally be empty.  Only in that empty-result case, retry
        # the exact same original question through GBrain's hybrid pipeline
        # without expansion.  Normal successful queries remain one call.
        if not sources and self._search_tool_name == "query":
            fallback_arguments = {**arguments, "expand": False}
            result = self._client.call_tool(self._search_tool_name, fallback_arguments)
            sources = parse_gbrain_sources(result)
        if sources:
            return self._attach_structured_section_context(sources, query)
        payload = _extract_payload(result)
        retrieval = payload.get("retrieval", {}) if isinstance(payload, dict) else {}
        diagnostic = retrieval.get("diagnostic", {}) if isinstance(retrieval, dict) else {}
        return {
            "sources": [],
            "retrieval_diagnostic": diagnostic or {
                "status": "no_gbrain_match",
                "message": "GBrain 本次原生检索未返回相关来源或知识页。",
                "search_tool": self._search_tool_name,
            },
        }

    def _attach_structured_section_context(self, sources: list[Source], query: str) -> list[Source]:
        """Replace a matched raw chunk with its complete Markdown section.

        This is intentionally *not* a ``chunk_index + N`` expansion.  A hit is
        mapped back to the source's heading hierarchy, then the exact section
        delimited by that heading is supplied as one evidence unit.  Therefore
        an enumeration is complete while the next, unrelated heading is not
        added merely because it happened to be in the following chunk.
        """
        enriched: list[Source] = []
        for source in sources:
            source_slug = source.page_slug or source.source_slug
            if not source_slug.startswith("sources/"):
                enriched.append(source)
                continue
            try:
                section = self._find_matching_section(source_slug, source.snippet, query)
                if section is not None:
                    enriched.append(
                        source.model_copy(
                            update={
                                "snippet": (
                                    f"【结构化原文小节：{section.title}】\n\n"
                                    f"{section.content}\n\n"
                                    "（证据按原始 Markdown 标题小节完整聚合；"
                                    "未使用固定数量的相邻分块。）"
                                )
                            }
                        )
                    )
                    continue
            except Exception:
                # Section reconstruction is additive.  A source read failure
                # must not hide an otherwise valid native retrieval result.
                pass
            enriched.append(source)
        return enriched

    def _find_matching_section(
        self,
        source_slug: str,
        matched_chunk: str,
        query: str,
    ) -> _MarkdownSection | None:
        sections = self._sections_for_source(source_slug)
        if not sections:
            return None
        return _match_section(sections, matched_chunk, query)

    def _sections_for_source(self, source_slug: str) -> list[_MarkdownSection]:
        cached = self._section_cache.get(source_slug)
        if cached is not None:
            return cached
        payload = _extract_payload(self._client.call_tool("get_page", {"slug": source_slug}))
        if not isinstance(payload, dict):
            return []
        content = str(
            payload.get("compiled_truth")
            or payload.get("content")
            or payload.get("markdown")
            or payload.get("text")
            or ""
        )
        sections = _split_markdown_sections(_unwrap_source_text(content))
        self._section_cache[source_slug] = sections
        return sections


class GBrainGetPageTool:
    def __init__(
        self,
        client: MCPClient,
        get_page_tool_name: str = "wiki_get_page",
    ) -> None:
        self._client = client
        self._get_page_tool_name = get_page_tool_name

    def __call__(self, slug: str) -> list[Source]:
        clean_slug = extract_wiki_slug(slug)
        result = self._client.call_tool(
            self._get_page_tool_name,
            {"slug": clean_slug},
        )
        return parse_gbrain_page(result, clean_slug)


def parse_gbrain_sources(result: Any) -> list[Source]:
    payload = _extract_payload(result)
    items = _extract_items(payload)
    return [_source_from_item(item, index) for index, item in enumerate(items, start=1)]


def parse_gbrain_page(result: Any, requested_slug: str) -> list[Source]:
    payload = _extract_payload(result)
    if isinstance(payload, dict) and "result" in payload:
        payload = _loads_if_json(payload["result"])
    if not isinstance(payload, dict):
        return [
            Source(
                title=requested_slug,
                url=f"gbrain://page/{requested_slug}",
                snippet=str(payload),
            )
        ]
    slug = str(payload.get("slug") or payload.get("id") or requested_slug)
    title = str(payload.get("title") or payload.get("name") or slug)
    content = str(
        payload.get("content")
        or payload.get("markdown")
        or payload.get("text")
        or json.dumps(payload, ensure_ascii=False)
    )
    updated_at = payload.get("updated_at") or payload.get("updatedAt")
    if updated_at:
        content = f"{content}\n\nUpdated at: {updated_at}"
    return [
        Source(
            title=title,
            url=f"gbrain://page/{slug}",
            snippet=content,
        )
    ]


def extract_wiki_slug(value: str) -> str:
    text = value.strip()
    for prefix in ("gbrain://page/", "page:"):
        if text.startswith(prefix):
            return text.removeprefix(prefix).strip()
    for token in text.replace("，", " ").replace("。", " ").split():
        if token.startswith("wiki/"):
            return token.strip()
    return text


def _unwrap_source_text(content: str) -> str:
    """Remove GBrain's display wrapper while retaining the captured Markdown."""
    details = re.search(r"<details[^>]*>(.*?)</details>", content, re.DOTALL | re.IGNORECASE)
    text = details.group(1) if details else content
    text = re.sub(r"<summary[^>]*>.*?</summary>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _split_markdown_sections(content: str) -> list[_MarkdownSection]:
    headings = list(_MARKDOWN_HEADING.finditer(content))
    sections: list[_MarkdownSection] = []
    for index, heading in enumerate(headings):
        level = len(heading.group(1))
        end = len(content)
        for following in headings[index + 1 :]:
            if len(following.group(1)) <= level:
                end = following.start()
                break
        section_content = content[heading.start() : end].strip()
        if not section_content:
            continue
        title = re.sub(r"\s+", " ", heading.group(2)).strip().rstrip("#").strip()
        normalized = _normalize_for_section_match(section_content)
        if title and normalized:
            sections.append(
                _MarkdownSection(
                    title=title,
                    level=level,
                    content=section_content,
                    normalized_content=normalized,
                )
            )
    return sections


def _match_section(
    sections: list[_MarkdownSection],
    matched_chunk: str,
    query: str,
) -> _MarkdownSection | None:
    """Locate the heading section that contains a native GBrain hit.

    Prefer a heading explicitly present in the chunk and most similar to the
    user's question.  This distinguishes a parent question such as “Agent 的
    工作模式” from an individual child item such as “ReActAgent”.  If the
    heading lies outside the chunk, use several sizeable text anchors rather
    than a chunk-index adjacency guess.
    """
    normalized_chunk = _normalize_for_section_match(matched_chunk)
    normalized_query = _normalize_for_section_match(query)
    if not normalized_chunk:
        return None

    heading_hits = [
        section
        for section in sections
        if len(_normalize_for_section_match(section.title)) >= 4
        and _normalize_for_section_match(section.title) in normalized_chunk
    ]
    if heading_hits:
        return max(
            heading_hits,
            key=lambda section: (
                SequenceMatcher(
                    None,
                    normalized_query,
                    _normalize_for_section_match(section.title),
                ).ratio(),
                section.level,
                len(section.title),
            ),
        )

    anchors = _section_anchors(normalized_chunk)
    candidates: list[tuple[int, float, int, _MarkdownSection]] = []
    for section in sections:
        matched_length = max(
            (len(anchor) for anchor in anchors if anchor in section.normalized_content),
            default=0,
        )
        if matched_length:
            query_similarity = SequenceMatcher(
                None,
                normalized_query,
                _normalize_for_section_match(section.title),
            ).ratio()
            candidates.append((matched_length, query_similarity, section.level, section))
    if not candidates:
        return None
    # A substantial source-text anchor is required; short common phrases must
    # never cause an unrelated neighbouring section to be pulled in.
    best_length, _, _, best_section = max(candidates, key=lambda candidate: candidate[:3])
    return best_section if best_length >= 48 else None


def _section_anchors(text: str) -> list[str]:
    if len(text) < 48:
        return [text] if text else []
    width = min(160, len(text))
    starts = {0, max(0, len(text) // 2 - width // 2), max(0, len(text) - width)}
    return [text[start : start + width] for start in sorted(starts) if len(text[start : start + width]) >= 48]


def _normalize_for_section_match(text: str) -> str:
    # Keep Chinese and ASCII word characters; drop Markdown punctuation,
    # escaping and whitespace so captured source text and chunk text compare
    # stably even when GBrain has normalised formatting.
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE).lower()


def _extract_payload(result: Any) -> Any:
    structured_content = getattr(result, "structuredContent", None)
    if structured_content:
        return _loads_if_json(structured_content)

    content = getattr(result, "content", [])
    if content:
        return _loads_if_json(getattr(content[0], "text", ""))

    return _loads_if_json(result)


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "items", "pages", "chunks", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        if "result" in payload:
            return _extract_items(_loads_if_json(payload["result"]))
    if payload:
        return [payload]
    return []


def _source_from_item(item: Any, index: int) -> Source:
    if not isinstance(item, dict):
        text = str(item)
        return Source(
            title=f"GBrain result {index}",
            url=f"gbrain://result/{index}",
            snippet=text,
        )

    title = str(
        item.get("title")
        or item.get("page_title")
        or item.get("name")
        or item.get("path")
        or f"GBrain result {index}"
    )
    url = str(
        item.get("url")
        or item.get("uri")
        or item.get("source")
        or item.get("id")
        or (f"gbrain://page/{item.get('slug')}" if item.get("slug") else "")
        or f"gbrain://result/{index}"
    )
    snippet = str(
        item.get("snippet")
        or item.get("chunk_text")
        or item.get("content")
        or item.get("text")
        or item.get("markdown")
        or json.dumps(item, ensure_ascii=False)
    )
    score = item.get("score") or item.get("relevance")
    if score is not None:
        snippet = f"{snippet}\n\n相关度：{score}"
    return Source(
        title=title,
        url=url,
        snippet=snippet,
        page_slug=str(item.get("page_slug") or item.get("slug") or ""),
        document_title=str(item.get("source_document_title") or item.get("document_title") or ""),
        document_filename=str(item.get("source_document_filename") or item.get("document_filename") or ""),
        document_path=str(item.get("source_document_path") or item.get("document_path") or ""),
        source_slug=str(item.get("source_slug") or ""),
        import_id=str(item.get("import_id") or ""),
        chunk_id=_optional_int(item.get("chunk_id")),
        chunk_index=_optional_int(item.get("chunk_index")),
        score=_optional_float(score),
    )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _loads_if_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def create_gbrain_stdio_config(
    command: str = "wsl.exe",
    args: list[str] | None = None,
) -> MCPServerConfig:
    return MCPServerConfig(
        transport="stdio",
        command=command,
        args=args
        or [
            "-d",
            "Ubuntu",
            "--",
            "bash",
            "/home/lzl/.local/bin/gbrain-native-mcp",
        ],
    )
