from __future__ import annotations

import logging
from typing import Any

from agent.extra_lenses import (
    COUNTERPARTY_SQL,
    DRAWDOWN_SQL,
    PERCENTILE_SQL,
    enrich_lens_results,
)
from agent import prompts
from agent.schema_context import SCHEMA
from agent.synthesis import synthesize_report
from app.settings import Settings
from craft.craft_client import CraftClient
from models.report import ChartPayload, ReportRequest, ReportResponse, RiskReport

logger = logging.getLogger(__name__)


def _extract_sql(gen_result: Any) -> str:
    if isinstance(gen_result, dict):
        for key in ("sql", "SQL", "query", "generated_sql"):
            if gen_result.get(key):
                return str(gen_result[key])
        # nested
        if isinstance(gen_result.get("result"), dict):
            return _extract_sql(gen_result["result"])
    if isinstance(gen_result, str) and "SELECT" in gen_result.upper():
        return gen_result
    return str(gen_result)


def _extract_rows(exec_result: Any) -> dict[str, Any]:
    if isinstance(exec_result, dict):
        return {
            "columns": exec_result.get("columns"),
            "rows": exec_result.get("rows") or exec_result.get("data") or [],
            "row_count": exec_result.get("row_count"),
            "truncated": exec_result.get("truncated", False),
        }
    if isinstance(exec_result, list):
        return {"columns": None, "rows": exec_result, "row_count": len(exec_result), "truncated": False}
    return {"columns": None, "rows": [], "row_count": 0, "truncated": False, "raw": exec_result}


def _extract_plotly(chart_result: Any) -> dict[str, Any]:
    if isinstance(chart_result, dict):
        for key in ("plotly_json", "figure", "fig", "chart"):
            if key in chart_result and isinstance(chart_result[key], dict):
                return chart_result[key]
        if "data" in chart_result and "layout" in chart_result:
            return chart_result
    return {"data": [], "layout": {"title": "Chart unavailable"}}


def _local_bar_chart(rows: list[dict[str, Any]], x_key: str, y_key: str, title: str) -> dict[str, Any]:
    xs, ys = [], []
    for row in rows[:20]:
        # fuzzy key match
        lower = {str(k).lower(): v for k, v in row.items()}
        x = row.get(x_key) or lower.get(x_key.lower())
        y = row.get(y_key) or lower.get(y_key.lower())
        if x is None:
            for cand in ("address", "top_address", "chain", "schema_name", "wallet"):
                if cand in lower:
                    x = lower[cand]
                    break
        if y is None:
            for cand in (
                "pct_of_total",
                "share_pct",
                "value_native",
                "balance",
                "tx_count_30d",
                "total_native_amount",
                "days_since_last_tx",
                "max_drawdown_pct",
                "worse_than_pct_of_peers",
                "top_counterparty_share_pct",
            ):
                if cand in lower:
                    y = lower[cand]
                    break
        if x is not None and y is not None:
            xs.append(str(x)[:18])
            try:
                ys.append(float(y))
            except (TypeError, ValueError):
                ys.append(0)
    return {
        "data": [{"type": "bar", "x": xs, "y": ys, "marker": {"color": "#0f766e"}}],
        "layout": {
            "title": title,
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "margin": {"t": 40, "r": 10, "b": 60, "l": 50},
            "font": {"family": "IBM Plex Sans, sans-serif", "color": "#0f172a"},
        },
    }


def _local_pie_chart(rows: list[dict[str, Any]], title: str) -> dict[str, Any]:
    labels, values = [], []
    for row in rows[:20]:
        lower = {str(k).lower(): v for k, v in row.items()}
        label = lower.get("chain") or lower.get("schema_name") or lower.get("blockchain")
        val = lower.get("pct_of_total") or lower.get("total_native_amount") or lower.get("value_native")
        if label is not None and val is not None:
            labels.append(str(label))
            try:
                values.append(float(val))
            except (TypeError, ValueError):
                values.append(0)
    return {
        "data": [{"type": "pie", "labels": labels, "values": values, "hole": 0.35}],
        "layout": {
            "title": title,
            "paper_bgcolor": "rgba(0,0,0,0)",
            "margin": {"t": 40, "r": 10, "b": 10, "l": 10},
            "font": {"family": "IBM Plex Sans, sans-serif", "color": "#0f172a"},
        },
    }


def demo_lens_results() -> dict[str, Any]:
    """Labeled synthetic population scan for UI/demo when CRAFT is unavailable."""
    concentration = {
        "columns": ["address", "chain", "value_native", "pct_of_total"],
        "rows": [
            {"address": "bc1qtreasury01…a1", "chain": "bitcoin", "value_native": 1250.4, "pct_of_total": 28.5},
            {"address": "0xTreasuryEth02…b2", "chain": "ethereum", "value_native": 890.1, "pct_of_total": 20.3},
            {"address": "LTtreasury03…c3", "chain": "litecoin", "value_native": 610.0, "pct_of_total": 13.9},
            {"address": "Dtreasury04…d4", "chain": "dogecoin", "value_native": 420.2, "pct_of_total": 9.6},
            {"address": "bc1qops05…e5", "chain": "bitcoin", "value_native": 380.0, "pct_of_total": 8.7},
            {"address": "0xops06…f6", "chain": "ethereum", "value_native": 310.5, "pct_of_total": 7.1},
            {"address": "Xtreasury07…g7", "chain": "dash", "value_native": 220.0, "pct_of_total": 5.0},
            {"address": "t1treasury08…h8", "chain": "zcash", "value_native": 180.3, "pct_of_total": 4.1},
            {"address": "bitcoincash:q…i9", "chain": "bitcoin_cash", "value_native": 90.0, "pct_of_total": 2.0},
            {"address": "0xdust10…j0", "chain": "ethereum", "value_native": 35.0, "pct_of_total": 0.8},
        ],
        "row_count": 10,
        "truncated": False,
    }
    diversification = {
        "columns": ["chain", "total_native_amount", "pct_of_total"],
        "rows": [
            {"chain": "bitcoin", "total_native_amount": 1630.4, "pct_of_total": 37.2},
            {"chain": "ethereum", "total_native_amount": 1235.6, "pct_of_total": 28.2},
            {"chain": "litecoin", "total_native_amount": 610.0, "pct_of_total": 13.9},
            {"chain": "dogecoin", "total_native_amount": 420.2, "pct_of_total": 9.6},
            {"chain": "dash", "total_native_amount": 220.0, "pct_of_total": 5.0},
            {"chain": "zcash", "total_native_amount": 180.3, "pct_of_total": 4.1},
            {"chain": "bitcoin_cash", "total_native_amount": 90.0, "pct_of_total": 2.0},
        ],
        "row_count": 7,
        "truncated": False,
    }
    liquidity = {
        "columns": [
            "address",
            "last_tx_timestamp",
            "days_since_last_tx",
            "tx_count_30d",
            "unique_counterparties",
        ],
        "rows": [
            {"address": "bc1qtreasury01…a1", "last_tx_timestamp": "2026-07-08", "days_since_last_tx": 3, "tx_count_30d": 42, "unique_counterparties": 18},
            {"address": "0xTreasuryEth02…b2", "last_tx_timestamp": "2026-07-10", "days_since_last_tx": 1, "tx_count_30d": 65, "unique_counterparties": 31},
            {"address": "LTtreasury03…c3", "last_tx_timestamp": "2026-04-01", "days_since_last_tx": 101, "tx_count_30d": 0, "unique_counterparties": 0},
            {"address": "Dtreasury04…d4", "last_tx_timestamp": "2026-06-20", "days_since_last_tx": 21, "tx_count_30d": 8, "unique_counterparties": 4},
            {"address": "bc1qops05…e5", "last_tx_timestamp": "2025-12-01", "days_since_last_tx": 222, "tx_count_30d": 0, "unique_counterparties": 0},
            {"address": "0xops06…f6", "last_tx_timestamp": "2026-07-05", "days_since_last_tx": 6, "tx_count_30d": 19, "unique_counterparties": 9},
            {"address": "Xtreasury07…g7", "last_tx_timestamp": "2026-02-11", "days_since_last_tx": 150, "tx_count_30d": 0, "unique_counterparties": 1},
            {"address": "t1treasury08…h8", "last_tx_timestamp": "2026-07-01", "days_since_last_tx": 10, "tx_count_30d": 5, "unique_counterparties": 3},
        ],
        "row_count": 8,
        "truncated": False,
    }
    return {
        "concentration": concentration,
        "diversification": diversification,
        "liquidity": liquidity,
        "drawdown": {
            "columns": [
                "address",
                "max_drawdown_pct",
                "peak_balance_native",
                "trough_balance_native",
            ],
            "rows": [
                {
                    "address": "0xTreasuryEth02…b2",
                    "max_drawdown_pct": 34.2,
                    "peak_balance_native": 1200.0,
                    "trough_balance_native": 789.6,
                },
                {
                    "address": "bc1qtreasury01…a1",
                    "max_drawdown_pct": 18.5,
                    "peak_balance_native": 1400.0,
                    "trough_balance_native": 1141.0,
                },
                {
                    "address": "LTtreasury03…c3",
                    "max_drawdown_pct": 9.1,
                    "peak_balance_native": 650.0,
                    "trough_balance_native": 590.85,
                },
            ],
            "row_count": 3,
            "truncated": False,
            "pending": False,
            "note": "DEMO synthetic max drawdown from cumulative net-flow windows.",
        },
        "meta": {
            "demo": True,
            "note": "DEMO DATA — CRAFT credentials not configured. Replace with live CRYPTO queries.",
        },
    }


def _charts_from_lens_results(lens_results: dict[str, Any]) -> list[ChartPayload]:
    charts = [
        ChartPayload(
            lens="concentration",
            plotly_json=_local_bar_chart(
                lens_results["concentration"]["rows"],
                "address",
                "pct_of_total",
                "Top wallet share (%)",
            ),
        ),
        ChartPayload(
            lens="diversification",
            plotly_json=_local_pie_chart(
                lens_results["diversification"]["rows"],
                "Tx volume by chain",
            ),
        ),
        ChartPayload(
            lens="liquidity",
            plotly_json=_local_bar_chart(
                lens_results["liquidity"]["rows"],
                "address",
                "days_since_last_tx",
                "Days since last transaction",
            ),
        ),
    ]

    pct = lens_results.get("percentile") or {}
    dist = pct.get("distribution") or []
    if dist:
        charts.append(
            ChartPayload(
                lens="percentile",
                plotly_json=_local_bar_chart(
                    dist,
                    "address",
                    "share_pct",
                    "Cohort share by rank (%)",
                ),
            )
        )
    elif pct.get("rows"):
        charts.append(
            ChartPayload(
                lens="percentile",
                plotly_json=_local_bar_chart(
                    pct["rows"],
                    "top_address",
                    "worse_than_pct_of_peers",
                    "Worse than % of peers",
                ),
            )
        )

    dd = lens_results.get("drawdown") or {}
    if dd.get("rows"):
        charts.append(
            ChartPayload(
                lens="drawdown",
                plotly_json=_local_bar_chart(
                    dd["rows"],
                    "address",
                    "max_drawdown_pct",
                    "Max drawdown (%)",
                ),
            )
        )
    else:
        charts.append(
            ChartPayload(
                lens="drawdown",
                plotly_json={
                    "data": [
                        {
                            "type": "scatter",
                            "mode": "lines+markers",
                            "name": "Illustrative cumulative path",
                            "x": ["t0", "t1", "t2", "t3", "t4", "t5"],
                            "y": [0, 40, 70, 55, 30, 45],
                            "line": {"color": "#0f766e", "width": 3},
                        },
                        {
                            "type": "scatter",
                            "mode": "lines",
                            "name": "Running peak",
                            "x": ["t0", "t1", "t2", "t3", "t4", "t5"],
                            "y": [0, 40, 70, 70, 70, 70],
                            "line": {"color": "#b45309", "dash": "dot", "width": 2},
                        },
                    ],
                    "layout": {
                        "title": "Max drawdown concept (awaiting live window query)",
                        "yaxis": {"title": "Cumulative native balance (index)"},
                        "annotations": [
                            {
                                "text": "Peak→trough gap = max drawdown. Live series pending Craft.",
                                "xref": "paper",
                                "yref": "paper",
                                "x": 0,
                                "y": 1.12,
                                "showarrow": False,
                                "font": {"size": 12, "color": "#3d524f"},
                            }
                        ],
                    },
                },
            )
        )

    cp = lens_results.get("counterparty") or {}
    if cp.get("rows"):
        charts.append(
            ChartPayload(
                lens="counterparty",
                plotly_json=_local_bar_chart(
                    cp["rows"],
                    "address",
                    "top_counterparty_share_pct",
                    "Relationship concentration proxy",
                ),
            )
        )
    return charts


def _sql_bundle(lens_results: dict[str, Any], base_sql: list[str] | None = None) -> list[str]:
    sqls = list(base_sql or [])
    pct = lens_results.get("percentile") or {}
    if pct.get("note"):
        sqls.append("-- Percentile: " + str(pct.get("note")))
    sqls.append(PERCENTILE_SQL)
    dd = lens_results.get("drawdown") or {}
    sqls.append(dd.get("sql") or DRAWDOWN_SQL)
    sqls.append(COUNTERPARTY_SQL)
    return sqls


async def _run_lens(
    craft: CraftClient,
    schema_name: str,
    schema_fqn: str,
    question: str,
    chart_type: str,
    chart_title: str,
    local_chart_fn,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    gen = await craft.generate_sql(
        question,
        schema_name=schema_name,
        schema_fqn=schema_fqn,
    )
    sql = _extract_sql(gen)
    if isinstance(gen, dict) and isinstance(gen.get("generate_sql"), dict):
        sql = gen["generate_sql"].get("sql") or sql
    exec_result = await craft.execute_query(sql)
    rows_payload = _extract_rows(exec_result)
    # Newer Craft may return artifact_fqn without inline rows
    if not rows_payload.get("rows") and isinstance(exec_result, dict):
        nested = exec_result.get("execute_query") or exec_result
        artifact = nested.get("artifact_fqn") if isinstance(nested, dict) else None
        if artifact:
            page = await craft.call_tool(
                "get_result_page",
                {"artifact_fqn": artifact, "offset": 0, "limit": 100},
            )
            rows_payload = _rows_from_preview(page)
    try:
        chart_raw = await craft.generate_plotly_chart(
            data=rows_payload.get("rows") or rows_payload,
            chart_type=chart_type,
            title=chart_title,
        )
        plotly_json = _extract_plotly(chart_raw)
        if not plotly_json.get("data"):
            plotly_json = local_chart_fn(rows_payload.get("rows") or [])
    except Exception:  # noqa: BLE001
        logger.exception("generate_plotly_chart failed; using local chart")
        plotly_json = local_chart_fn(rows_payload.get("rows") or [])
    return sql, rows_payload, plotly_json


def _rows_from_preview(page: Any) -> dict[str, Any]:
    preview = page
    if isinstance(page, dict):
        preview = page.get("preview") or page
    if not isinstance(preview, dict):
        return {"columns": None, "rows": [], "row_count": 0, "truncated": False}
    columns = preview.get("columns") or []
    raw_rows = preview.get("rows") or []
    dict_rows = []
    for row in raw_rows:
        if isinstance(row, dict):
            dict_rows.append(row)
        elif isinstance(row, (list, tuple)) and columns:
            dict_rows.append(
                {str(columns[i]).lower(): row[i] for i in range(min(len(columns), len(row)))}
            )
    return {
        "columns": columns,
        "rows": dict_rows,
        "row_count": preview.get("total_rows") or len(dict_rows),
        "truncated": bool(preview.get("truncated")),
    }


def _load_live_cache() -> dict[str, Any] | None:
    from pathlib import Path
    import json

    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "docs" / "live_report_cache.json",
        here.parents[1] / "docs" / "live_report_cache.json",
        Path.cwd() / "docs" / "live_report_cache.json",
        Path.cwd().parent / "docs" / "live_report_cache.json",
    ]
    for path in candidates:
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("meta", {}).get("source") == "craft_mcp_live":
                    logger.info("Loaded live Craft cache from %s", path)
                    return data
        except Exception:  # noqa: BLE001
            logger.exception("Failed reading live cache %s", path)
    logger.warning("No live Craft cache found; tried %s", [str(p) for p in candidates])
    return None


async def generate_treasury_report(
    settings: Settings,
    request: ReportRequest,
    craft: CraftClient | None = None,
) -> ReportResponse:
    live_cache = None if settings.craft_headless_ready else _load_live_cache()
    use_demo = not settings.craft_headless_ready and live_cache is None
    if use_demo and not settings.allow_demo_fallback:
        raise RuntimeError(
            "CRAFT headless credentials missing. Set CRAFT_ACCESS_TOKEN for live queries, "
            "or enable ALLOW_DEMO_FALLBACK."
        )

    if live_cache is not None:
        logger.info("Serving live Craft MCP cache (no headless token)")
        lens_results = enrich_lens_results(
            {
                "concentration": live_cache["concentration"],
                "diversification": live_cache["diversification"],
                "liquidity": live_cache["liquidity"],
                "meta": live_cache.get("meta", {}),
                **{
                    k: live_cache[k]
                    for k in ("percentile", "drawdown", "counterparty")
                    if k in live_cache
                },
            }
        )
        report = synthesize_report(settings, lens_results)
        return ReportResponse(
            report_json=report,
            charts=_charts_from_lens_results(lens_results),
            sql_used=_sql_bundle(lens_results, list(live_cache.get("sql_used") or [])),
            demo_mode=False,
            schema_notes=live_cache.get("meta", {}).get("note") or SCHEMA.recon_notes,
        )

    if use_demo:
        logger.warning(
            "Running in DEMO MODE — CRAFT_ACCESS_TOKEN not set "
            "(Cursor MCP OAuth does not populate the backend token)"
        )
        lens_results = enrich_lens_results(demo_lens_results())
        report = synthesize_report(settings, lens_results)
        if not report.summary.startswith("[DEMO]"):
            report.summary = "[DEMO] " + report.summary
        return ReportResponse(
            report_json=report,
            charts=_charts_from_lens_results(lens_results),
            sql_used=_sql_bundle(
                lens_results,
                [
                    "-- DEMO MODE: CRAFT not configured. Core lens SQL would be generated via generate_sql.",
                ],
            ),
            demo_mode=True,
            schema_notes=SCHEMA.recon_notes,
        )

    assert craft is not None
    connection = settings.craft_connection_slug or SCHEMA.connection_slug or "crypto-70a8f494"
    schema_name = "CRYPTO_ETHEREUM_CLASSIC"
    schema_fqn = f"{connection}.CRYPTO.{schema_name}"
    addresses = request.addresses if request.mode == "wallets" else None

    questions = {
        "concentration": prompts.concentration_question(request.mode, addresses),
        "diversification": prompts.diversification_question(request.mode, addresses),
        "liquidity": prompts.liquidity_question(request.mode, addresses),
    }

    sql_used: list[str] = []
    lens_payloads: dict[str, Any] = {}

    sql, rows, _plotly = await _run_lens(
        craft,
        schema_name,
        schema_fqn,
        questions["concentration"],
        "bar",
        "Concentration — top wallet share",
        lambda r: _local_bar_chart(r, "address", "pct_of_total", "Top wallet share (%)"),
    )
    sql_used.append(sql)
    lens_payloads["concentration"] = rows

    eth_schema = "CRYPTO_ETHEREUM"
    eth_fqn = f"{connection}.CRYPTO.{eth_schema}"
    sql, rows, _plotly = await _run_lens(
        craft,
        eth_schema,
        eth_fqn,
        questions["diversification"],
        "pie",
        "Diversification — value by chain",
        lambda r: _local_pie_chart(r, "Chain distribution"),
    )
    sql_used.append(sql)
    lens_payloads["diversification"] = rows

    sql, rows, _plotly = await _run_lens(
        craft,
        eth_schema,
        eth_fqn,
        questions["liquidity"],
        "bar",
        "Liquidity — days since last tx",
        lambda r: _local_bar_chart(r, "address", "days_since_last_tx", "Days since last transaction"),
    )
    sql_used.append(sql)
    lens_payloads["liquidity"] = rows

    lens_payloads["meta"] = {
        "demo": False,
        "has_usd_price_column": SCHEMA.has_usd_price_column,
        "value_unit": SCHEMA.value_unit,
        "mode": request.mode,
        "connection": connection,
    }

    lens_payloads = enrich_lens_results(lens_payloads)
    report: RiskReport = synthesize_report(settings, lens_payloads)
    return ReportResponse(
        report_json=report,
        charts=_charts_from_lens_results(lens_payloads),
        sql_used=_sql_bundle(lens_payloads, sql_used),
        demo_mode=False,
        schema_notes=SCHEMA.recon_notes if not SCHEMA.recon_complete else None,
    )


def _find_crypto_database_id(dbs: Any) -> str | None:
    items = dbs
    if isinstance(dbs, dict):
        items = (
            dbs.get("databases")
            or dbs.get("data")
            or dbs.get("items")
            or (dbs.get("list_metadata") or {}).get("results")
            or [dbs]
        )
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("database_name") or item.get("id") or "").upper()
        if "CRYPTO" in name:
            return str(
                item.get("id")
                or item.get("uuid")
                or item.get("database")
                or item.get("connection_id")
                or item.get("resource_uri")
                or ""
            ) or None
    return None
