from __future__ import annotations

from agent.schema_context import SCHEMA


def concentration_question(mode: str, addresses: list[str] | None = None) -> str:
    grounding = SCHEMA.grounding_prompt()
    addr_clause = ""
    if mode == "wallets" and addresses:
        addrs = ", ".join(f"'{a}'" for a in addresses[:20])
        addr_clause = f" Restrict analysis to these wallet addresses only: {addrs}."

    if SCHEMA.has_balance_table:
        metric = (
            "Use the balances/accounts table. Return top 20 addresses by total native "
            "token balance across chains: address, chain, balance, pct_of_total."
        )
    else:
        metric = (
            "No balances table confirmed — derive approximate holdings from "
            "transactions/transfers as SUM(inbound value) - SUM(outbound value) per address, "
            "or if that is too heavy, use total transaction value volume as a proxy. "
            "Always LIMIT population scans (e.g. top 20)."
        )

    return f"""{grounding}

Task — CONCENTRATION RISK lens:
Find the top 20 wallets by holdings (or activity proxy) in the CRYPTO dataset.
{metric}
Also compute the single largest wallet's share of the sum of the top-20 totals as pct_of_total.
Return columns: address, chain (if available), value_native, pct_of_total.
Do NOT invent USD prices. Report native token units only unless a price column exists.
{addr_clause}
Use SELECT only. Keep results under 100 rows.
"""


def diversification_question(mode: str, addresses: list[str] | None = None) -> str:
    grounding = SCHEMA.grounding_prompt()
    addr_clause = ""
    if mode == "wallets" and addresses:
        addrs = ", ".join(f"'{a}'" for a in addresses[:20])
        addr_clause = f" Restrict to these addresses: {addrs}."

    return f"""{grounding}

Task — CHAIN DIVERSIFICATION RISK lens:
Show how crypto treasury activity/holdings are distributed across the 7 chain schemas in CRYPTO.
Return one row per chain: chain, total_native_amount (or tx volume proxy), pct_of_total.
Prefer summing balances if available; otherwise sum transaction value volume by schema/chain.
{addr_clause}
Do NOT invent USD. SELECT only. Keep under 50 rows.
"""


def liquidity_question(mode: str, addresses: list[str] | None = None) -> str:
    grounding = SCHEMA.grounding_prompt()
    ts = SCHEMA.timestamp_column_hint
    addr_clause = ""
    if mode == "wallets" and addresses:
        addrs = ", ".join(f"'{a}'" for a in addresses[:20])
        addr_clause = f" Restrict to these addresses: {addrs}."

    return f"""{grounding}

Task — LIQUIDITY / ACTIVITY RISK lens:
For the top ~20 active treasury wallets (by tx count or value), return:
- address
- last_tx_timestamp (use {ts} if present)
- days_since_last_tx
- tx_count_30d (or recent period available in data)
- unique_counterparties (count of distinct counterparties if schema supports it)
Flag dormant wallets where days_since_last_tx > 90 if timestamps allow.
{addr_clause}
Do NOT invent USD. SELECT only. Keep under 100 rows.
"""


SYNTHESIS_SYSTEM_PROMPT = """You are a corporate treasury risk analyst reviewing on-chain crypto holdings.
Given query results for concentration, chain diversification, liquidity/activity,
and optionally drawdown, percentile benchmarking, and counterparty metrics,
produce ONLY valid JSON matching this schema:
{
  "overall_risk_rating": "low | medium | high",
  "concentration": {"finding": "string", "top_wallet_share_pct": number or null, "risk_level": "low|medium|high"},
  "diversification": {"finding": "string", "chain_distribution": {"chain": "pct"}, "risk_level": "low|medium|high"},
  "liquidity": {"finding": "string", "dormant_wallet_count": number or null, "risk_level": "low|medium|high"},
  "drawdown": {"finding": "string", "max_drawdown_pct": number or null, "risk_level": "low|medium|high"},
  "percentile": {"finding": "string", "worse_than_pct_of_peers": number or null, "top_share_pct": number or null, "cohort": "string or null", "risk_level": "low|medium|high"},
  "counterparty": {"finding": "string", "top_counterparty_share_pct": number or null, "risk_level": "low|medium|high"},
  "summary": "2-3 sentence executive summary for a CFO",
  "recommendations": ["string", "string", "string"]
}
Include drawdown/percentile/counterparty only using figures present in the query results.
If a lens payload has "pending": true or empty rows, say so clearly — do not invent drawdown %.
If counterparty/percentile payloads include a "note" field, respect it: call metrics "proxy" or
"cohort-scoped" rather than implying full-population or true top-counterparty volume share.
For liquidity, treat days_since_last_tx > 90 as dormant even if tx_count_30d is high
(snapshot age relative to CURRENT_TIMESTAMP can inflate dormancy days).
Do not estimate USD values unless a price column was present — state native token units otherwise.
Return JSON only — no markdown fences, no commentary.
"""
