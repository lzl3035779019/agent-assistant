import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from pmaa.config import Settings, settings


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


class LLMClient(Protocol):
    def complete_text(self, messages: list[LLMMessage]) -> str:
        ...

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        ...


class LLMClientError(RuntimeError):
    pass


def parse_json_value(content: str) -> Any:
    """Extract one JSON value from a model response without corrupting arrays.

    Some OpenAI-compatible providers occasionally return a JSON array despite a
    requested JSON object.  In particular, do not slice from the first ``{`` to
    the last ``}``: doing so turns a perfectly valid ``[{...}, {...}]`` into
    invalid JSON.
    """
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # Tolerate a short natural-language preamble, but use JSONDecoder so a
        # complete array/object retains its actual outer shape.
        decoder = json.JSONDecoder()
        starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
        for start in sorted(starts):
            try:
                parsed, _end = decoder.raw_decode(text[start:])
                return parsed
            except json.JSONDecodeError:
                continue
        preview = re.sub(r"\s+", " ", content).strip()[:500]
        raise LLMClientError(f"LLM 未返回可解析的 JSON（前 500 字符：{preview}）") from exc


def parse_json_object(content: str) -> dict[str, Any]:
    parsed = parse_json_value(content)
    if not isinstance(parsed, dict):
        raise LLMClientError("LLM JSON response must be an object.")
    return parsed


class FakeLLMClient:
    def __init__(
        self,
        text_payload: str = "",
        json_payload: dict[str, Any] | None = None,
    ) -> None:
        self._text_payload = text_payload
        self._json_payload = json_payload or {}

    def complete_text(self, messages: list[LLMMessage]) -> str:
        return self._text_payload

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        return self._json_payload


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float | None = 60,
    ) -> None:
        if not api_key:
            raise LLMClientError("LLM API key is empty.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    def complete_text(self, messages: list[LLMMessage]) -> str:
        payload = self._request(messages)
        return self._extract_content(payload)

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        payload = self._request(
            messages,
            extra_payload={"response_format": {"type": "json_object"}},
        )
        return parse_json_object(self._extract_content(payload))

    def _request(
        self,
        messages: list[LLMMessage],
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [message.__dict__ for message in messages],
            "temperature": 0.2,
        }
        if extra_payload:
            payload.update(extra_payload)

        response = httpx.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout_seconds,
        )
        if response.status_code >= 400:
            raise LLMClientError(f"LLM request failed: {response.status_code} {response.text}")
        return response.json()

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(f"Unexpected LLM response: {payload}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("LLM returned empty content.")
        return content


def create_llm_client(
    app_settings: Settings = settings,
    timeout_seconds: float | None = 60,
) -> LLMClient | None:
    provider = app_settings.llm_provider.lower()
    if provider == "mock":
        return None

    if provider in {"qwen", "aliyun", "bailian", "dashscope"}:
        return OpenAICompatibleLLMClient(
            api_key=app_settings.qwen_api_key,
            base_url=app_settings.qwen_base_url,
            model=app_settings.llm_model,
            timeout_seconds=timeout_seconds,
        )

    if provider == "deepseek":
        return OpenAICompatibleLLMClient(
            api_key=app_settings.deepseek_api_key,
            base_url=app_settings.deepseek_base_url,
            model=app_settings.llm_model,
            timeout_seconds=timeout_seconds,
        )

    if provider == "auto":
        if app_settings.qwen_api_key:
            return OpenAICompatibleLLMClient(
                api_key=app_settings.qwen_api_key,
                base_url=app_settings.qwen_base_url,
                model=app_settings.llm_model,
                timeout_seconds=timeout_seconds,
            )
        if app_settings.deepseek_api_key:
            return OpenAICompatibleLLMClient(
                api_key=app_settings.deepseek_api_key,
                base_url=app_settings.deepseek_base_url,
                model=app_settings.llm_model,
                timeout_seconds=timeout_seconds,
            )

    raise LLMClientError(f"Unsupported or unconfigured LLM provider: {app_settings.llm_provider}")
