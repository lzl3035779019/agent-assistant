import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import anyio
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client


MCPTransport = Literal["stdio", "sse", "http"]


@dataclass(frozen=True)
class MCPServerConfig:
    transport: MCPTransport = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    cwd: str | Path | None = None
    env: dict[str, str] | None = None
    url: str = ""
    headers: dict[str, str] | None = None
    timeout: float = 30.0
    sse_read_timeout: float = 300.0


class MCPClientConfigurationError(RuntimeError):
    pass


class MCPToolCallError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config

    def list_tools(self) -> Any:
        return anyio.run(self._list_tools)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return anyio.run(self._call_tool, name, arguments or {})

    async def _list_tools(self) -> Any:
        async with self._session() as session:
            return await session.list_tools()

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        async with self._session() as session:
            result = await session.call_tool(name, arguments)
            if getattr(result, "isError", False):
                content = getattr(result, "content", [])
                message = getattr(content[0], "text", "MCP tool call failed.") if content else "MCP tool call failed."
                raise MCPToolCallError(f"{name}: {message}")
            return result

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        async with self._streams() as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session

    @asynccontextmanager
    async def _streams(self) -> AsyncIterator[tuple[Any, Any]]:
        transport = self._config.transport
        if transport == "stdio":
            if not self._config.command:
                raise MCPClientConfigurationError("MCP stdio command is required.")
            server = StdioServerParameters(
                command=self._config.command,
                args=self._config.args,
                cwd=self._config.cwd,
                env=self._config.env or os.environ.copy(),
            )
            async with stdio_client(server) as (read_stream, write_stream):
                yield read_stream, write_stream
            return
        if transport == "sse":
            if not self._config.url:
                raise MCPClientConfigurationError("MCP SSE url is required.")
            async with sse_client(
                self._config.url,
                headers=self._config.headers,
                timeout=self._config.timeout,
                sse_read_timeout=self._config.sse_read_timeout,
            ) as (read_stream, write_stream):
                yield read_stream, write_stream
            return
        if transport == "http":
            if not self._config.url:
                raise MCPClientConfigurationError("MCP HTTP url is required.")
            async with streamablehttp_client(
                self._config.url,
                headers=self._config.headers,
                timeout=self._config.timeout,
                sse_read_timeout=self._config.sse_read_timeout,
            ) as (read_stream, write_stream, _get_session_id):
                yield read_stream, write_stream
            return
        raise MCPClientConfigurationError(f"Unsupported MCP transport: {transport}")
