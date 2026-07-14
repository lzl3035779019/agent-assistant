import pytest

from pmaa.schemas.task import Source
from pmaa.tools.tavily_search import TavilySearchClient, TavilySearchError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[dict] = []

    def post(self, url: str, *, headers: dict, json: dict, timeout: float) -> FakeResponse:
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.response


def test_tavily_search_client_maps_results_to_sources():
    http_client = FakeHttpClient(
        FakeResponse(
            200,
            {
                "results": [
                    {
                        "title": "LangGraph docs",
                        "url": "https://langchain-ai.github.io/langgraph/",
                        "content": "StateGraph supports stateful agent workflows.",
                    }
                ]
            },
        )
    )
    client = TavilySearchClient(api_key="test-key", http_client=http_client)

    sources = client.search("LangGraph StateGraph", max_results=3)

    assert sources == [
        Source(
            title="LangGraph docs",
            url="https://langchain-ai.github.io/langgraph/",
            snippet="StateGraph supports stateful agent workflows.",
        )
    ]
    assert http_client.requests[0]["json"]["query"] == "LangGraph StateGraph"
    assert http_client.requests[0]["json"]["max_results"] == 3
    assert http_client.requests[0]["json"]["api_key"] == "test-key"
    assert http_client.requests[0]["headers"]["Authorization"] == "Bearer test-key"


def test_tavily_search_client_raises_on_http_error():
    client = TavilySearchClient(
        api_key="test-key",
        http_client=FakeHttpClient(FakeResponse(401, {"error": "unauthorized"})),
    )

    with pytest.raises(TavilySearchError):
        client.search("LangGraph")
