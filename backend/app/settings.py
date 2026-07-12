from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always prefer the project-root .env (where fetch_craft_creds.py writes).
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


def _load_env() -> None:
    if _ROOT_ENV.is_file():
        load_dotenv(_ROOT_ENV, override=True)


_load_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT_ENV) if _ROOT_ENV.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        # Prefer explicit env / dotenv over empty defaults
        env_ignore_empty=True,
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
    # Prefer cached live Craft results for fast demos; set true to re-query Craft every scan
    craft_force_live: bool = False
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
        return bool(self.craft_project_id.strip() and self.craft_access_token.strip())

    @property
    def nebius_configured(self) -> bool:
        return bool(self.nebius_api_key)


@lru_cache
def get_settings() -> Settings:
    _load_env()
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
