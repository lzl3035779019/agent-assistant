from types import SimpleNamespace

import pytest

from pmaa.wiki import enrichment


class FakeToolClient:
    def __init__(self, tool_names: list[str]) -> None:
        self._tool_names = tool_names

    def list_tools(self):
        return SimpleNamespace(
            tools=[SimpleNamespace(name=name) for name in self._tool_names]
        )


def test_enrichment_reports_missing_native_gbrain_tools(monkeypatch):
    monkeypatch.setattr(
        enrichment,
        "_native_client",
        lambda: FakeToolClient(["get_page", "put_page"]),
    )

    with pytest.raises(RuntimeError) as exc_info:
        enrichment.enrich_source_with_gbrain_skills("sources/documents/source-1")

    message = str(exc_info.value)
    assert "GBrain 官方 Skill 整理需要原生 MCP 工具" in message
    assert "add_link" in message
    assert "get_skill" in message
