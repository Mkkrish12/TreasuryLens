from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high"]


class ConcentrationFinding(BaseModel):
    finding: str
    top_wallet_share_pct: float | None = None
    risk_level: RiskLevel


class DiversificationFinding(BaseModel):
    finding: str
    chain_distribution: dict[str, float] = Field(default_factory=dict)
    risk_level: RiskLevel


class LiquidityFinding(BaseModel):
    finding: str
    dormant_wallet_count: int | None = None
    risk_level: RiskLevel


class DrawdownFinding(BaseModel):
    finding: str
    max_drawdown_pct: float | None = None
    risk_level: RiskLevel


class PercentileFinding(BaseModel):
    finding: str
    worse_than_pct_of_peers: float | None = None
    top_share_pct: float | None = None
    cohort: str | None = None
    risk_level: RiskLevel


class CounterpartyFinding(BaseModel):
    finding: str
    top_counterparty_share_pct: float | None = None
    risk_level: RiskLevel


class RiskReport(BaseModel):
    overall_risk_rating: RiskLevel
    concentration: ConcentrationFinding
    diversification: DiversificationFinding
    liquidity: LiquidityFinding
    drawdown: DrawdownFinding | None = None
    percentile: PercentileFinding | None = None
    counterparty: CounterpartyFinding | None = None
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    units_note: str = (
        "Values reported in native token units; no USD valuation unless present in source data."
    )


LensName = Literal[
    "concentration",
    "diversification",
    "liquidity",
    "drawdown",
    "percentile",
    "counterparty",
]


class ChartPayload(BaseModel):
    lens: LensName
    plotly_json: dict[str, Any]


class ReportRequest(BaseModel):
    mode: Literal["population", "wallets"] = "population"
    addresses: list[str] = Field(default_factory=list)


class ReportResponse(BaseModel):
    report_json: RiskReport
    charts: list[ChartPayload]
    sql_used: list[str]
    demo_mode: bool = False
    schema_notes: str | None = None
