from pmaa.llm.client import FakeLLMClient, LLMMessage, parse_json_object, parse_json_value


def test_fake_llm_client_returns_configured_json():
    client = FakeLLMClient(json_payload={"goal": "研究 LangGraph"})

    result = client.complete_json([LLMMessage(role="user", content="plan")])

    assert result == {"goal": "研究 LangGraph"}


def test_parse_json_object_extracts_json_from_markdown_fence():
    content = """
    ```json
    {"passed": true, "issues": []}
    ```
    """

    assert parse_json_object(content) == {"passed": True, "issues": []}


def test_parse_json_value_preserves_a_top_level_pages_array():
    content = '[{"type":"concept","title":"RAG"}, {"type":"method","title":"重排序"}]'

    assert parse_json_value(content) == [
        {"type": "concept", "title": "RAG"},
        {"type": "method", "title": "重排序"},
    ]
