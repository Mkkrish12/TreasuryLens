from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    craft_project_id: str = ""
    craft_mcp_url: str = "https://nebius.emergence.ai/mcp"
    craft_access_token: str = ""
    craft_database_uuid: str = ""
    craft_database_fqn: str = ""
    craft_connection_slug: str = ""
    craft_resource_uri: str = ""

    nebius_api_key: str = ""
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    nebius_model: str = "nvidia/nemotron-3-super-120b-a12b"

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # When CRAFT credentials are missing, serve labeled synthetic demo data.
    allow_demo_fallback: bool = True
    execute_query_min_interval_s: float = 6.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def craft_configured(self) -> bool:
        # Project ID is enough for Cursor MCP OAuth; bearer token only needed for headless scripts.
        return bool(self.craft_project_id)

    @property
    def craft_headless_ready(self) -> bool:
        return bool(self.craft_project_id and self.craft_access_token)

    @property
    def nebius_configured(self) -> bool:
        return bool(self.nebius_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
