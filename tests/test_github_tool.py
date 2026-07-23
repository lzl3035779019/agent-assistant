import httpx
import pytest

from pmaa.tools.github_tool import GitHubMonitorTool, GitHubToolError


def test_github_tool_discovers_and_deduplicates_ai_repositories() -> None:
    seen_authorization: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_authorization.append(request.headers.get("authorization", ""))
        assert request.url.path == "/search/repositories"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "full_name": "example/agent-kit",
                        "html_url": "https://github.com/example/agent-kit",
                        "description": "Agent framework",
                        "stargazers_count": 12000,
                        "forks_count": 900,
                        "open_issues_count": 20,
                        "language": "Python",
                        "topics": ["llm", "agents"],
                        "pushed_at": "2026-07-23T00:00:00Z",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    tool = GitHubMonitorTool(token="secret", client=client, max_results=10)

    result = tool(
        {
            "monitor_rule_id": "rule-1",
            "monitor_target": "热门 AI 项目",
            "objective": "监控 LLM Agent RAG MCP 热门项目",
        }
    )

    assert result["mode"] == "ai_repository_discovery"
    assert result["rule_id"] == "rule-1"
    assert len(result["items"]) == 1
    assert result["items"][0]["stars"] == 12000
    assert all(value == "Bearer secret" for value in seen_authorization)


def test_github_tool_reads_repository_and_latest_release() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(
                200,
                json={"tag_name": "v2.0.0", "published_at": "2026-07-22T00:00:00Z"},
            )
        return httpx.Response(
            200,
            json={
                "full_name": "langchain-ai/langgraph",
                "html_url": "https://github.com/langchain-ai/langgraph",
                "description": "Graph orchestration",
                "stargazers_count": 15000,
                "forks_count": 2000,
                "open_issues_count": 50,
                "language": "Python",
                "topics": ["agents"],
                "pushed_at": "2026-07-23T00:00:00Z",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    tool = GitHubMonitorTool(client=client)

    result = tool(
        {
            "monitor_target": "langchain-ai/langgraph",
            "objective": "检查 LangGraph 更新",
        }
    )

    assert result["mode"] == "repository_snapshot"
    assert result["items"][0]["latest_release"] == "v2.0.0"


def test_github_tool_reports_invalid_token_without_leaking_it() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(401, json={"message": "Bad credentials"})
        )
    )
    tool = GitHubMonitorTool(token="do-not-leak", client=client)

    with pytest.raises(GitHubToolError, match="Token 无效") as error:
        tool({"monitor_target": "热门 AI 项目"})

    assert "do-not-leak" not in str(error.value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("langchain-ai/langgraph", "langchain-ai/langgraph"),
        ("https://github.com/modelcontextprotocol/servers", "modelcontextprotocol/servers"),
        ("not a repository", ""),
    ],
)
def test_parse_repository(value: str, expected: str) -> None:
    assert GitHubMonitorTool.parse_repository(value) == expected
