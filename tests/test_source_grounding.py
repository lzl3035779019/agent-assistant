from pmaa.agents.reflection import ReflectionAgent
from pmaa.agents.writer import WriterAgent
from pmaa.llm.client import FakeLLMClient
from pmaa.schemas.task import ExecutionPlan, PlanStep, Source


class CapturingTextLLMClient(FakeLLMClient):
    def __init__(self, text_payload: str) -> None:
        super().__init__(text_payload=text_payload)
        self.text_messages = []

    def complete_text(self, messages):
        self.text_messages = messages
        return super().complete_text(messages)


def test_writer_prompt_numbers_sources_and_requires_citations():
    plan = ExecutionPlan(
        goal="查询台风巴威",
        steps=[
            PlanStep(
                step_id="search-1",
                description="搜索实时资料",
                agent="search",
                expected_output="资料来源",
            )
        ],
    )
    sources = [
        Source(
            title="中央气象台台风网",
            url="https://typhoon.nmc.cn/",
            snippet="台风路径和强度信息",
        )
    ]
    client = CapturingTextLLMClient(text_payload="回答正文")

    WriterAgent(llm_client=client).write(plan, sources)

    prompt = "\n".join(message.content for message in client.text_messages)
    assert "[S1]" in prompt
    assert "https://typhoon.nmc.cn/" in prompt
    assert "引用" in prompt


def test_writer_fallback_adds_numbered_source_citations():
    plan = ExecutionPlan(goal="查询台风巴威", steps=[])
    sources = [
        Source(
            title="中央气象台台风网",
            url="https://typhoon.nmc.cn/",
            snippet="台风路径和强度信息",
        )
    ]

    answer = WriterAgent().write(plan, sources)

    assert "[S1]" in answer
    assert "[中央气象台台风网](https://typhoon.nmc.cn/)" in answer
    assert "台风路径和强度信息" not in answer.split("## 资料来源", 1)[-1]


def test_reflection_rejects_placeholder_sources():
    reflection = ReflectionAgent().reflect(
        "查询台风巴威",
        "根据资料来源 [S1] 生成回答。",
        [Source(title="placeholder", url="https://example.com/overview", snippet="fake")],
    )

    assert reflection.passed is False
    assert reflection.need_retry is True
    assert any("placeholder" in issue.lower() or "占位" in issue for issue in reflection.issues)


def test_reflection_rejects_answer_without_source_citation():
    reflection = ReflectionAgent().reflect(
        "查询台风巴威",
        "台风巴威已经减弱。",
        [Source(title="中央气象台台风网", url="https://typhoon.nmc.cn/", snippet="台风路径")],
    )

    assert reflection.passed is False
    assert reflection.need_retry is True
    assert any("citation" in issue.lower() or "引用" in issue for issue in reflection.issues)
