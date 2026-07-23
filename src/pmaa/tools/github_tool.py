from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx


DEFAULT_DISCOVERY_QUERIES = [
    "topic:llm stars:>1000 archived:false",
    "topic:ai-agents stars:>500 archived:false",
    "topic:rag stars:>500 archived:false",
    "topic:mcp stars:>200 archived:false",
]


class GitHubToolError(RuntimeError):
    pass


class GitHubMonitorTool:
    """Read-only GitHub connector for repository discovery and monitoring."""

    def __init__(
        self,
        *,
        token: str = "",
        base_url: str = "https://api.github.com",
        max_results: int = 10,
        client: httpx.Client | None = None,
    ) -> None:
        self.token = token.strip()
        self.base_url = base_url.rstrip("/")
        self.max_results = max(1, min(int(max_results), 30))
        self.client = client

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        rule_id = str(request.get("monitor_rule_id") or "")
        target = str(request.get("monitor_target") or "").strip()
        objective = str(request.get("objective") or "").strip()
        repository = self.parse_repository(target) or self.parse_repository(objective)
        if repository:
            items = [self.get_repository_snapshot(repository)]
            mode = "repository_snapshot"
        else:
            items = self.discover_hot_ai_repositories(objective or target)
            mode = "ai_repository_discovery"
        return {
            "status": "completed",
            "provider": "github",
            "mode": mode,
            "rule_id": rule_id,
            "items": items,
            "authenticated": bool(self.token),
        }

    def discover_hot_ai_repositories(self, query: str = "") -> list[dict[str, Any]]:
        discovery_queries = self._discovery_queries(query)
        unique: dict[str, dict[str, Any]] = {}
        per_query = max(3, min(self.max_results, 10))
        for discovery_query in discovery_queries:
            payload = self._get_json(
                "/search/repositories",
                params={
                    "q": discovery_query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": per_query,
                },
            )
            for repository in payload.get("items", []):
                if not isinstance(repository, dict):
                    continue
                item = self._repository_item(repository)
                key = item["url"].lower()
                unique.setdefault(key, item)
        return sorted(
            unique.values(),
            key=lambda item: int(item.get("stars", 0)),
            reverse=True,
        )[: self.max_results]

    def get_repository_snapshot(self, repository: str) -> dict[str, Any]:
        payload = self._get_json(f"/repos/{repository}")
        latest_release: dict[str, Any] = {}
        try:
            release_payload = self._get_json(f"/repos/{repository}/releases/latest")
            if isinstance(release_payload, dict):
                latest_release = release_payload
        except GitHubToolError as exc:
            if "404" not in str(exc):
                raise
        return self._repository_item(payload, latest_release=latest_release)

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PMAA-Information-Monitor",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        client = self.client or httpx
        try:
            response = client.get(
                f"{self.base_url}{path}",
                params=params,
                headers=headers,
                timeout=20.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise GitHubToolError("GitHub Token 无效或已过期（HTTP 401）。") from exc
            if status in {403, 429}:
                remaining = exc.response.headers.get("x-ratelimit-remaining", "")
                raise GitHubToolError(
                    f"GitHub API 已限流（HTTP {status}, remaining={remaining or 'unknown'}）。"
                ) from exc
            raise GitHubToolError(f"GitHub API 请求失败（HTTP {status}）。") from exc
        except httpx.HTTPError as exc:
            raise GitHubToolError(f"GitHub API 连接失败：{exc}") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise GitHubToolError("GitHub API 返回了无法识别的数据格式。")
        return payload

    @staticmethod
    def parse_repository(value: str) -> str:
        text = value.strip()
        if not text:
            return ""
        if "github.com" in text.lower():
            parsed = urlparse(text if "://" in text else f"https://{text}")
            parts = [part for part in parsed.path.strip("/").split("/") if part]
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1].removesuffix('.git')}"
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", text)
        if match:
            return f"{match.group(1)}/{match.group(2).removesuffix('.git')}"
        return ""

    @staticmethod
    def _repository_item(
        repository: dict[str, Any],
        *,
        latest_release: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        full_name = str(repository.get("full_name") or repository.get("name") or "")
        release = latest_release or {}
        return {
            "title": full_name,
            "url": str(repository.get("html_url") or ""),
            "snippet": str(repository.get("description") or ""),
            "provider": "github",
            "stars": int(repository.get("stargazers_count") or 0),
            "forks": int(repository.get("forks_count") or 0),
            "open_issues": int(repository.get("open_issues_count") or 0),
            "language": str(repository.get("language") or ""),
            "topics": list(repository.get("topics") or []),
            "pushed_at": str(repository.get("pushed_at") or ""),
            "latest_release": str(release.get("tag_name") or ""),
            "latest_release_at": str(release.get("published_at") or ""),
        }

    @staticmethod
    def _discovery_queries(query: str) -> list[str]:
        lowered = query.lower()
        selected: list[str] = []
        topic_queries = {
            "llm": "topic:llm stars:>1000 archived:false",
            "大模型": "topic:llm stars:>1000 archived:false",
            "agent": "topic:ai-agents stars:>500 archived:false",
            "智能体": "topic:ai-agents stars:>500 archived:false",
            "rag": "topic:rag stars:>500 archived:false",
            "mcp": "topic:mcp stars:>200 archived:false",
        }
        for marker, github_query in topic_queries.items():
            if marker in lowered and github_query not in selected:
                selected.append(github_query)
        return selected or DEFAULT_DISCOVERY_QUERIES
