from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    addresses: list[str] = Field(default_factory=list)


class AskResponse(BaseModel):
    answer: str
    sql_used: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    plotly_json: dict[str, Any] | None = None
    chart_kind: Literal["bar", "pie"] | None = None
    demo_mode: bool = False
    source: Literal["craft_live", "live_cache", "demo"] = "demo"
    notes: str | None = None
