from typing import Any, Protocol

import httpx

from pmaa.schemas.task import Source


class TavilySearchError(RuntimeError):
    pass


class HttpPostClient(Protocol):
    def post(self, url: str, *, headers: dict, json: dict, timeout: float) -> Any:
        pass


class TavilySearchClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.tavily.com/search",
        search_depth: str = "basic",
        timeout_seconds: float = 30.0,
        http_client: HttpPostClient | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url
        self._search_depth = search_depth
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or httpx

    def search(self, query: str, max_results: int = 5) -> list[Source]:
        if not self._api_key:
            raise TavilySearchError("Tavily API key is missing.")

        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": self._search_depth,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        response = self._http_client.post(
            self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout_seconds,
        )

        if response.status_code >= 400:
            raise TavilySearchError(f"Tavily search failed: {response.status_code} {response.text}")

        data = response.json()
        return [self._to_source(item) for item in data.get("results", []) if item.get("url")]

    def _to_source(self, item: dict) -> Source:
        return Source(
            title=str(item.get("title") or item.get("url") or "Untitled"),
            url=str(item["url"]),
            snippet=str(item.get("content") or item.get("snippet") or item.get("raw_content") or ""),
        )
