import os

from dotenv import load_dotenv
from pydantic import BaseModel


load_dotenv()


class Settings(BaseModel):
    app_name: str = "PMAA"
    app_env: str = "local"
    llm_provider: str = "mock"
    llm_model: str = "deepseek-v4-flash"
    search_provider: str = "mock"
    max_reflection_retries: int = 1
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com/search"
    tavily_max_results: int = 5
    gbrain_mcp_enabled: bool = False
    gbrain_mcp_transport: str = "stdio"
    gbrain_mcp_command: str = "wsl.exe"
    gbrain_mcp_args: list[str] = [
        "-d",
        "Ubuntu",
        "--",
        "bash",
        "/home/lzl/.local/bin/gbrain-native-mcp",
    ]
    gbrain_mcp_url: str = ""
    # Compatibility defaults for embedded/test callers. Runtime settings use
    # the environment defaults below, which point at native GBrain tools.
    gbrain_mcp_search_tool: str = "wiki_search"
    gbrain_mcp_get_page_tool: str = "wiki_get_page"
    gbrain_mcp_max_results: int = 5
    gbrain_wiki_bridge_command: str = "wsl.exe"
    gbrain_wiki_bridge_args: list[str] = [
        "-d",
        "Ubuntu",
        "--",
        "bash",
        "/home/lzl/.local/bin/gbrain-wiki-mcp",
    ]
    gbrain_inbox_dir: str = r"C:\Users\lzl\GbrainInbox"
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    api_base_url: str = "http://127.0.0.1:8000"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name, str(default)).lower()
    return value in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    value = _env(name)
    if not value:
        return default
    return [item.strip() for item in value.split("|") if item.strip()]


def load_settings() -> Settings:
    load_dotenv(override=True)
    return Settings(
        app_name=_env("APP_NAME", "PMAA"),
        app_env=_env("APP_ENV", "local"),
        llm_provider=_env("LLM_PROVIDER", "mock").lower(),
        llm_model=_env("LLM_MODEL", "deepseek-v4-flash"),
        search_provider=_env("SEARCH_PROVIDER", "mock").lower(),
        max_reflection_retries=int(_env("MAX_REFLECTION_RETRIES", "1")),
        tavily_api_key=_env("TAVILY_API_KEY"),
        tavily_base_url=_env("TAVILY_BASE_URL", "https://api.tavily.com/search"),
        tavily_max_results=int(_env("TAVILY_MAX_RESULTS", "5")),
        gbrain_mcp_enabled=_env_bool("GBRAIN_MCP_ENABLED", False),
        gbrain_mcp_transport=_env("GBRAIN_MCP_TRANSPORT", "stdio").lower(),
        gbrain_mcp_command=_env("GBRAIN_MCP_COMMAND", "wsl.exe"),
        gbrain_mcp_args=_env_list(
            "GBRAIN_MCP_ARGS",
            ["-d", "Ubuntu", "--", "bash", "/home/lzl/.local/bin/gbrain-native-mcp"],
        ),
        gbrain_mcp_url=_env("GBRAIN_MCP_URL"),
        gbrain_mcp_search_tool=_env("GBRAIN_MCP_SEARCH_TOOL", "search"),
        gbrain_mcp_get_page_tool=_env("GBRAIN_MCP_GET_PAGE_TOOL", "get_page"),
        gbrain_mcp_max_results=int(_env("GBRAIN_MCP_MAX_RESULTS", "5")),
        gbrain_wiki_bridge_command=_env("GBRAIN_WIKI_BRIDGE_COMMAND", "wsl.exe"),
        gbrain_wiki_bridge_args=_env_list(
            "GBRAIN_WIKI_BRIDGE_ARGS",
            ["-d", "Ubuntu", "--", "bash", "/home/lzl/.local/bin/gbrain-wiki-mcp"],
        ),
        gbrain_inbox_dir=_env("GBRAIN_INBOX_DIR", r"C:\Users\lzl\GbrainInbox"),
        qwen_api_key=_env("QWEN_API_KEY"),
        qwen_base_url=_env("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        deepseek_api_key=_env("DEEPSEEK_API_KEY") or _env("DEEPSEEk_API_KEY"),
        deepseek_base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_base_url=_env("PMAA_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
    )


settings = load_settings()
