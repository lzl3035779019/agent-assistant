import webbrowser
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse


class ActionExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def register(
        self,
        action: str,
        executor: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._executors[action] = executor

    def execute(self, action: str, plan: dict[str, Any]) -> dict[str, Any]:
        executor = self._executors.get(action)
        if executor is None:
            return {
                "status": "unsupported",
                "reason": f"No executor registered for action: {action}",
            }
        return executor(plan)


def create_default_executor_registry(
    browser_opener: Callable[[str], bool] | None = None,
) -> ActionExecutorRegistry:
    registry = ActionExecutorRegistry()
    registry.register(
        "browser.open_url",
        _build_browser_open_url_executor(browser_opener or webbrowser.open),
    )
    return registry


def _build_browser_open_url_executor(
    browser_opener: Callable[[str], bool],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _execute(plan: dict[str, Any]) -> dict[str, Any]:
        url = str(plan.get("url", "")).strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {
                "status": "rejected",
                "reason": "Only http and https URLs are allowed.",
            }
        try:
            opened = browser_opener(url)
        except Exception as exc:
            return {
                "status": "failed",
                "reason": str(exc),
            }
        if not opened:
            return {
                "status": "failed",
                "reason": "Browser opener returned false.",
            }
        return {
            "status": "executed",
            "url": url,
        }

    return _execute
