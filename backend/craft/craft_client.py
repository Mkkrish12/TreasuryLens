from __future__ import annotations

import json
import logging
from typing import Any

from app.settings import Settings
from craft.rate_limiter import QueryRateLimiter

logger = logging.getLogger(__name__)


def _parse_tool_result(result: Any) -> Any:
    """Normalize FastMCP / MCP tool call results into Python objects."""
    if result is None:
        return None
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content"):
        parts = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if text:
                parts.append(text)
        joined = "\n".join(parts)
        if not joined:
            return result
        try:
            return json.loads(joined)
        except json.JSONDecodeError:
            return joined
    if isinstance(result, (dict, list, str, int, float, bool)):
        return result
    return str(result)


class CraftClient:
    """CRAFT MCP client using connection-slug API (Nebius / em-runtime-mcp)."""

    def __init__(self, settings: Settings, rate_limiter: QueryRateLimiter | None = None):
        self.settings = settings
        self.rate_limiter = rate_limiter or QueryRateLimiter(
            min_interval_s=settings.execute_query_min_interval_s
        )
        self._client = None

    @property
    def connection(self) -> str:
        return (
            self.settings.craft_connection_slug
            or "crypto-70a8f494"
        )

    @property
    def configured(self) -> bool:
        return self.settings.craft_headless_ready

    def _headers(self) -> dict[str, str]:
        headers = {"X-Project-ID": self.settings.craft_project_id}
        if self.settings.craft_access_token:
            headers["Authorization"] = f"Bearer {self.settings.craft_access_token}"
        return headers

    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport

        transport = StreamableHttpTransport(
            url=self.settings.craft_mcp_url,
            headers=self._headers(),
        )
        self._client = Client(transport)
        await self._client.__aenter__()
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                logger.exception("Error closing CRAFT MCP client")
            self._client = None

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        client = await self._ensure_client()
        logger.info("CRAFT tool call: %s args=%s", name, list((arguments or {}).keys()))
        result = await client.call_tool(name, arguments or {})
        return _parse_tool_result(result)

    async def hello_world(self) -> Any:
        return await self.call_tool("hello_world", {})

    async def list_data_connections(self, limit: int = 100) -> Any:
        return await self.call_tool("list_data_connections", {"limit": limit})

    async def list_databases(self, connection: str | None = None) -> Any:
        return await self.call_tool(
            "list_databases",
            {"connection": connection or self.connection},
        )

    async def search_schema(self, query: str, connection: str | None = None) -> Any:
        args: dict[str, Any] = {"query": query}
        if connection or self.connection:
            args["connection"] = connection or self.connection
        return await self.call_tool("search_schema", args)

    async def get_schema(self, fqn: str, connection: str | None = None, include_children: bool = True) -> Any:
        return await self.call_tool(
            "get_schema",
            {
                "connection": connection or self.connection,
                "fqn": fqn,
                "include_children": include_children,
            },
        )

    async def sample_data(self, table_fqn: str, connection: str | None = None, limit: int = 10) -> Any:
        # Prefer FQN-based sample if tool accepts connection + fqn variants
        return await self.call_tool(
            "sample_data",
            {
                "connection": connection or self.connection,
                "table_fqn": table_fqn,
                "limit": limit,
            },
        )

    async def generate_sql(
        self,
        question: str,
        schema_name: str,
        schema_fqn: str | None = None,
        connection: str | None = None,
    ) -> Any:
        schema_obj: dict[str, Any] = {"schema_name": schema_name}
        if schema_fqn:
            schema_obj["schema_fqn"] = schema_fqn
        return await self.call_tool(
            "generate_sql",
            {
                "question": question,
                "connection": connection or self.connection,
                "schema": schema_obj,
            },
        )

    async def execute_query(
        self,
        sql: str,
        connection: str | None = None,
        max_rows: int = 500,
    ) -> Any:
        await self.rate_limiter.acquire()
        return await self.call_tool(
            "execute_query",
            {
                "sql": sql,
                "connection": connection or self.connection,
                "max_rows": max_rows,
            },
        )

    async def generate_plotly_chart(
        self,
        data: Any,
        chart_type: str,
        title: str | None = None,
    ) -> Any:
        # Craft schema accepts data + chart_type only (title is rejected)
        args: dict[str, Any] = {"data": data, "chart_type": chart_type}
        _ = title  # kept for call-site compatibility
        return await self.call_tool("generate_plotly_chart", args)
