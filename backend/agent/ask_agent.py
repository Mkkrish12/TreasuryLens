"""Natural-language treasury Q&A over CRAFT CRYPTO.

Flow: question → generate_sql → execute_query → grounded Nebius answer + local chart.
Falls back to live_report_cache answers when Craft is unavailable or times out.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import OpenAI

from agent.schema_context import SCHEMA
from agent.treasury_agent import (
    _extract_rows,
    _extract_sql,
    _local_bar_chart,
    _local_pie_chart,
    _load_live_cache,
    _rows_from_preview,
)
from app.settings import Settings
from craft.craft_client import CraftClient
from models.ask import AskRequest, AskResponse

logger = logging.getLogger(__name__)

FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|MERGE|CREATE|GRANT|REVOKE|CALL|EXECUTE)\b",
    re.IGNORECASE,
)

ANSWER_SYSTEM = """You are a corporate crypto treasury analyst.
Answer ONLY using the SQL result rows provided. If rows are empty, say so.
Keep the answer to 3-5 short sentences for a CFO.
Mention native token units (no USD) unless a price column appears in the rows.
If the question is outside on-chain treasury risk, say what you can answer instead.
Return plain text only — no markdown fences."""


def _pick_schema(question: str) -> tuple[str, str, str]:
    """Return (schema_name, schema_fqn, chart_hint)."""
    q = question.lower()
    connection = SCHEMA.connection_slug or "crypto-70a8f494"
    if any(w in q for w in ("balance", "holder", "concentration", "richest", "top wallet", "percentile")):
        return (
            "CRYPTO_ETHEREUM_CLASSIC",
            f"{connection}.CRYPTO.CRYPTO_ETHEREUM_CLASSIC",
            "bar",
        )
    if any(w in q for w in ("bitcoin", "btc", "dash", "band", "cash", "chain mix", "diversif")):
        # Diversification spans chains; Craft generate_sql scoped to one schema —
        # use ETHEREUM as primary and phrase the question carefully.
        return (
            "CRYPTO_ETHEREUM",
            f"{connection}.CRYPTO.CRYPTO_ETHEREUM",
            "pie",
        )
    return (
        "CRYPTO_ETHEREUM",
        f"{connection}.CRYPTO.CRYPTO_ETHEREUM",
        "bar",
    )


def _scope_question(question: str, addresses: list[str]) -> str:
    base = (
        "Read-only analytics on the CRYPTO dataset. "
        "Prefer aggregates, LIMIT 20 or less, and recent date filters when using transactions. "
        "Return columns useful for a CFO risk view. "
        f"Question: {question.strip()}"
    )
    if addresses:
        sample = ", ".join(addresses[:25])
        base += f" Restrict to these wallet addresses when relevant: {sample}."
    return base


def _validate_sql(sql: str) -> str:
    cleaned = sql.strip().rstrip(";")
    if not cleaned:
        raise ValueError("Craft returned empty SQL.")
    if FORBIDDEN_SQL.search(cleaned):
        raise ValueError("Refusing non-SELECT SQL from Craft.")
    upper = cleaned.upper()
    if not upper.lstrip().startswith(("SELECT", "WITH")):
        raise ValueError("Only SELECT / WITH queries are allowed.")
    if "LIMIT" not in upper and "QUALIFY" not in upper:
        cleaned = f"SELECT * FROM ({cleaned}) AS q LIMIT 20"
    return cleaned


def _chart_from_rows(rows: list[dict[str, Any]], hint: str) -> tuple[dict[str, Any] | None, str | None]:
    if not rows:
        return None, None
    sample = rows[0]
    keys = {str(k).lower(): k for k in sample}
    if hint == "pie" or "chain" in keys or "schema_name" in keys:
        return _local_pie_chart(rows, "Query result"), "pie"
    x_key = keys.get("address") or keys.get("from_address") or keys.get("chain") or next(iter(sample))
    y_candidates = (
        "pct_of_total",
        "share_pct",
        "eth_balance",
        "value_native",
        "tx_count",
        "transaction_count",
        "days_since_last_tx",
        "unique_counterparties",
        "total_native_amount",
        "count",
    )
    y_key = None
    for cand in y_candidates:
        if cand in keys:
            y_key = keys[cand]
            break
    if y_key is None:
        # first numeric column
        for k, v in sample.items():
            if isinstance(v, (int, float)) and str(k).lower() not in ("rn", "rank"):
                y_key = k
                break
    if y_key is None:
        return None, None
    return _local_bar_chart(rows, str(x_key), str(y_key), "Query result"), "bar"


def _answer_with_nebius(settings: Settings, question: str, rows: list[dict[str, Any]], sql: str | None) -> str:
    if not settings.nebius_configured:
        return _heuristic_answer(question, rows)
    client = OpenAI(base_url=settings.nebius_base_url, api_key=settings.nebius_api_key)
    payload = {
        "question": question,
        "sql": sql,
        "row_count": len(rows),
        "rows_preview": rows[:30],
        "units": "native token units unless a price column is present",
    }
    try:
        resp = client.chat.completions.create(
            model=settings.nebius_model,
            messages=[
                {"role": "system", "content": ANSWER_SYSTEM},
                {"role": "user", "content": json.dumps(payload, default=str)[:80_000]},
            ],
            temperature=0.2,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or _heuristic_answer(question, rows)
    except Exception:  # noqa: BLE001
        logger.exception("Nebius ask answer failed")
        return _heuristic_answer(question, rows)


def _heuristic_answer(question: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            "No rows came back for that question. Try asking about top ETC balances, "
            "chain transaction mix, or recent ETH sender activity."
        )
    preview = rows[0]
    keys = ", ".join(list(preview.keys())[:6])
    return (
        f"Returned {len(rows)} row(s) for: {question.strip()}. "
        f"First row fields include {keys}. "
        "Figures are in native token units unless a price column appears."
    )


def _cache_fallback(question: str, settings: Settings) -> AskResponse | None:
    cache = _load_live_cache()
    if not cache:
        return None
    q = question.lower()
    rows: list[dict[str, Any]] = []
    sql = None
    note = "Answered from cached live Craft results (set CRAFT_FORCE_LIVE / reconnect for fresh SQL)."
    chart_hint = "bar"

    if any(w in q for w in ("concentrat", "balance", "top wallet", "holder", "richest", "percentile")):
        rows = list((cache.get("concentration") or {}).get("rows") or [])
        sqls = cache.get("sql_used") or []
        sql = sqls[0] if sqls else None
        chart_hint = "bar"
    elif any(w in q for w in ("diversif", "chain", "bitcoin", "ethereum", "mix")):
        rows = list((cache.get("diversification") or {}).get("rows") or [])
        sqls = cache.get("sql_used") or []
        sql = sqls[1] if len(sqls) > 1 else (sqls[0] if sqls else None)
        chart_hint = "pie"
    elif any(w in q for w in ("liquid", "dormant", "activity", "last tx", "counterparty")):
        rows = list((cache.get("liquidity") or {}).get("rows") or [])
        sqls = cache.get("sql_used") or []
        sql = sqls[2] if len(sqls) > 2 else (sqls[0] if sqls else None)
        chart_hint = "bar"
    else:
        # generic: show concentration as default treasury snapshot
        rows = list((cache.get("concentration") or {}).get("rows") or [])
        sqls = cache.get("sql_used") or []
        sql = sqls[0] if sqls else None
        note = (
            "Matched a general treasury question to the cached concentration snapshot. "
            "Ask about concentration, chain mix, or liquidity for a tighter match — "
            "or enable live Craft for open-ended SQL."
        )

    if not rows:
        return None

    plotly, kind = _chart_from_rows(rows, chart_hint)
    answer = _answer_with_nebius(settings, question, rows, sql)
    return AskResponse(
        answer=answer,
        sql_used=sql,
        rows=rows[:20],
        row_count=len(rows),
        plotly_json=plotly,
        chart_kind=kind,  # type: ignore[arg-type]
        demo_mode=False,
        source="live_cache",
        notes=note,
    )


async def answer_question(
    settings: Settings,
    request: AskRequest,
    craft: CraftClient | None = None,
) -> AskResponse:
    question = request.question.strip()
    if len(question) < 3:
        raise ValueError("Question is too short.")

    headless = (craft is not None) or settings.craft_headless_ready

    # Fast path: cached live Craft results (reliable for demos)
    if not settings.craft_force_live:
        cached = _cache_fallback(question, settings)
        if cached:
            if headless:
                cached.notes = (
                    (cached.notes or "")
                    + " Live Craft is connected — set CRAFT_FORCE_LIVE=true to run fresh generate_sql."
                ).strip()
            return cached

    # Live Craft when forced (or no cache available)
    if headless and craft is not None:
        try:
            return await _answer_via_craft(settings, request, craft)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Live Craft ask failed (%s); trying cache fallback", exc)
            cached = _cache_fallback(question, settings)
            if cached:
                cached.notes = (
                    f"Live Craft query failed ({exc}). Served cached live results instead."
                )
                return cached
            raise

    cached = _cache_fallback(question, settings)
    if cached:
        return cached

    # Last resort labeled demo
    demo_rows = [
        {"address": "0xdemo01…", "pct_of_total": 28.5, "chain": "ethereum"},
        {"address": "0xdemo02…", "pct_of_total": 18.2, "chain": "bitcoin"},
        {"address": "0xdemo03…", "pct_of_total": 12.1, "chain": "litecoin"},
    ]
    plotly, kind = _chart_from_rows(demo_rows, "bar")
    return AskResponse(
        answer=(
            "[DEMO] CRAFT is not connected, so this is a labeled synthetic answer. "
            f"You asked: “{question}”. Connect CRAFT_ACCESS_TOKEN for live SQL Q&A."
        ),
        sql_used="-- DEMO: generate_sql + execute_query unavailable without CRAFT_ACCESS_TOKEN",
        rows=demo_rows,
        row_count=len(demo_rows),
        plotly_json=plotly,
        chart_kind=kind,  # type: ignore[arg-type]
        demo_mode=True,
        source="demo",
        notes="Demo fallback — not live CRYPTO data.",
    )


async def _answer_via_craft(
    settings: Settings,
    request: AskRequest,
    craft: CraftClient,
) -> AskResponse:
    schema_name, schema_fqn, chart_hint = _pick_schema(request.question)
    scoped = _scope_question(request.question, request.addresses)

    gen = await craft.generate_sql(
        scoped,
        schema_name=schema_name,
        schema_fqn=schema_fqn,
    )
    sql = _extract_sql(gen)
    if isinstance(gen, dict) and isinstance(gen.get("generate_sql"), dict):
        sql = gen["generate_sql"].get("sql") or sql
    sql = _validate_sql(sql)

    exec_result = await craft.execute_query(sql, max_rows=100)
    rows_payload = _extract_rows(exec_result)
    if not rows_payload.get("rows") and isinstance(exec_result, dict):
        nested = exec_result.get("execute_query") or exec_result
        artifact = nested.get("artifact_fqn") if isinstance(nested, dict) else None
        if artifact:
            page = await craft.call_tool(
                "get_result_page",
                {"artifact_fqn": artifact, "offset": 0, "limit": 50},
            )
            rows_payload = _rows_from_preview(page)

    rows = list(rows_payload.get("rows") or [])[:50]
    plotly, kind = _chart_from_rows(rows, chart_hint)
    answer = _answer_with_nebius(settings, request.question, rows, sql)

    return AskResponse(
        answer=answer,
        sql_used=sql,
        rows=rows[:20],
        row_count=int(rows_payload.get("row_count") or len(rows)),
        plotly_json=plotly,
        chart_kind=kind,  # type: ignore[arg-type]
        demo_mode=False,
        source="craft_live",
        notes=f"Queried schema {schema_name} via CRAFT generate_sql → execute_query.",
    )
