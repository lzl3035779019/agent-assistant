from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.schemas.task import ExecutionPlan, Source


def format_numbered_sources(sources: list[Source]) -> str:
    return "\n".join(
        f"[S{index}] {source.title}\nURL: {source.url}\n摘要: {source.snippet}"
        for index, source in enumerate(sources, start=1)
    )


class WriterAgent:
    name = "writer"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client

    def write(
        self,
        plan: ExecutionPlan,
        sources: list[Source],
        conversation_context: str = "",
    ) -> str:
        if self._llm_client is not None:
            try:
                context_text = (
                    f"历史对话上下文：\n{conversation_context.strip()}\n\n"
                    if conversation_context.strip()
                    else ""
                )
                return self._llm_client.complete_text(
                    [
                        LLMMessage(
                            role="system",
                            content=(
                                "你是 PMAA 的 Writer Agent。"
                                "只能基于给定资料来源回答，不能编造实时信息。"
                                "每个关键结论都要引用来源编号，例如 [S1]。"
                                "如果资料不足，要明确说明不确定。"
                                "对于‘有哪些/列举/模式/步骤/组成’这类枚举问题，必须综合全部资料来源："
                                "完整保留资料中明确给出的清单，不能因为某个来源只列举示例就写成‘只有这些’或‘仅展示这些’。"
                                "若资料同时给出不同粒度的分类（例如执行模式与设计范式），要分层说明它们的关系，"
                                "分别列全，而不是互相替代。"
                                "标注为‘结构化原文小节’的资料是按原始 Markdown 标题边界聚合的完整证据，"
                                "必须完整整合其中明确列出的条目；不要把小节外的内容混入，也不能只回答开头的前几项。"
                                "输出中文 Markdown。"
                                "末尾必须保留“资料来源”列表，只列链接，不展开摘要。"
                                "格式为：- [S1] [标题](URL)。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=(
                                f"{context_text}"
                                f"执行计划：\n{plan.model_dump_json(indent=2)}\n\n"
                                f"资料来源：\n{format_numbered_sources(sources)}"
                            ),
                        ),
                    ]
                )
            except LLMClientError:
                pass

        source_lines = "\n".join(
            f"- [S{index}] [{source.title}]({source.url})"
            for index, source in enumerate(sources, start=1)
        )
        return (
            f"# {plan.goal}\n\n"
            "## 摘要\n\n"
            "以下内容基于当前检索到的资料来源整理。"
            "关键结论请以来源编号核对，例如 [S1]。\n\n"
            "## 可执行建议\n\n"
            "1. 优先阅读来源中的官方或一手资料。\n"
            "2. 对实时性要求高的问题，继续核对来源更新时间。\n"
            "3. 如果来源数量不足，不要把结论当成最终事实。\n\n"
            "## 资料来源\n\n"
            f"{source_lines}"
        )

    @staticmethod
    def write_retrieval_diagnostic(diagnostic: dict) -> str:
        message = str(diagnostic.get("message") or "未检索到可引用的知识库页面。")
        lines = [
            "## 未检索到可引用的知识库证据",
            "",
            message,
        ]
        documents = diagnostic.get("documents")
        if isinstance(documents, list) and documents:
            lines.extend(["", "### 覆盖检查"])
            for document in documents:
                if not isinstance(document, dict):
                    continue
                filename = str(document.get("filename") or document.get("title") or "导入文档")
                terms = "、".join(str(term) for term in document.get("matched_terms", []) if term)
                lines.append(f"- `{filename}`：原始提取文本中发现关键词 {terms or '（已命中）'}，但没有对应的语义 Wiki 页面。")
                excerpt = str(document.get("excerpt") or "").strip()
                if excerpt:
                    lines.extend(["", "命中的原始文本片段：", "", f"> {excerpt.replace(chr(10), chr(10) + '> ')}"])
        lines.extend([
            "",
            "### 建议",
            "为该文档补充或重新生成覆盖此主题的 Wiki 页面后，再进行知识库问答；系统不会以无依据的通用知识替代检索结果。",
        ])
        return "\n".join(lines)
