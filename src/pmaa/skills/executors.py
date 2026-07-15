import webbrowser
import shlex
import shutil
import subprocess
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
    command_exists: Callable[[str], bool] | None = None,
    command_runner: Callable[[list[str], int], tuple[int, str, str]] | None = None,
    timeout_seconds: int = 120,
) -> ActionExecutorRegistry:
    registry = ActionExecutorRegistry()
    registry.register(
        "browser.open_url",
        _build_browser_open_url_executor(browser_opener or webbrowser.open),
    )
    registry.register(
        "browser.task",
        _build_browser_task_executor(
            command_exists=command_exists or (lambda command: shutil.which(command) is not None),
            command_runner=command_runner or _run_command,
            timeout_seconds=timeout_seconds,
        ),
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


def _build_browser_task_executor(
    *,
    command_exists: Callable[[str], bool],
    command_runner: Callable[[list[str], int], tuple[int, str, str]],
    timeout_seconds: int,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _execute(plan: dict[str, Any]) -> dict[str, Any]:
        if not command_exists("agent-browser"):
            return {
                "status": "missing_runtime",
                "reason": "agent-browser command is not installed or not on PATH.",
            }
        raw_commands = plan.get("command_plan", [])
        if not isinstance(raw_commands, list):
            return {
                "status": "rejected",
                "reason": "browser.task command_plan must be a list.",
            }
        commands = [str(command).strip() for command in raw_commands if str(command).strip()]
        if not commands:
            return {
                "status": "rejected",
                "reason": "browser.task command_plan is empty.",
            }
        completed: list[dict[str, Any]] = []
        for command in commands:
            if "<ref>" in command or "<value>" in command:
                return {
                    "status": "requires_agent_iteration",
                    "reason": "This browser task needs a snapshot ref before it can continue.",
                    "completed_commands": completed,
                    "blocked_command": command,
                }
            args = _split_command(command)
            if not args or args[0] != "agent-browser":
                return {
                    "status": "rejected",
                    "reason": f"Unsupported browser task command: {command}",
                    "completed_commands": completed,
                }
            try:
                returncode, stdout, stderr = command_runner(args, timeout_seconds)
            except Exception as exc:
                return {
                    "status": "failed",
                    "reason": str(exc),
                    "completed_commands": completed,
                    "failed_command": args,
                }
            entry = {
                "command": args,
                "returncode": returncode,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            }
            completed.append(entry)
            if returncode != 0:
                return {
                    "status": "failed",
                    "reason": stderr.strip() or stdout.strip() or "agent-browser command failed.",
                    "completed_commands": completed,
                }
        return {
            "status": "executed",
            "completed_commands": completed,
        }

    return _execute


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=False)
    except ValueError:
        return command.split()


def _run_command(command: list[str], timeout_seconds: int) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr
