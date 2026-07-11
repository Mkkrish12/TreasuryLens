from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import OpenAI

from agent.prompts import SYNTHESIS_SYSTEM_PROMPT
from app.settings import Settings
from models.report import RiskReport

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise
        return json.loads(match.group(0))


def _coerce_pct(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def cross_check_report(report: RiskReport, lens_results: dict[str, Any]) -> RiskReport:
    """Overwrite hallucinated numeric fields with values derived from query rows when possible."""
    conc_rows = _rows(lens_results.get("concentration"))
    if conc_rows:
        top_pct = _first_numeric(conc_rows[0], ("pct_of_total", "PCT_OF_TOTAL", "share_pct", "top_wallet_share_pct"))
        if top_pct is not None:
            # Normalize if returned as fraction
            if top_pct <= 1.0:
                top_pct *= 100.0
            report.concentration.top_wallet_share_pct = round(top_pct, 2)

    div_rows = _rows(lens_results.get("diversification"))
    if div_rows:
        dist: dict[str, float] = {}
        for row in div_rows:
            chain = (
                row.get("chain")
                or row.get("CHAIN")
                or row.get("schema_name")
                or row.get("SCHEMA_NAME")
                or row.get("blockchain")
            )
            pct = _first_numeric(row, ("pct_of_total", "PCT_OF_TOTAL", "pct", "percentage"))
            if chain is not None and pct is not None:
                if pct <= 1.0:
                    pct *= 100.0
                dist[str(chain)] = round(pct, 2)
        if dist:
            report.diversification.chain_distribution = dist

    liq_rows = _rows(lens_results.get("liquidity"))
    if liq_rows:
        dormant = 0
        for row in liq_rows:
            days = _first_numeric(row, ("days_since_last_tx", "DAYS_SINCE_LAST_TX", "days_dormant"))
            if days is not None and days > 90:
                dormant += 1
            flag = row.get("is_dormant") or row.get("IS_DORMANT")
            if flag in (True, 1, "true", "TRUE", "yes"):
                dormant += 1
        report.liquidity.dormant_wallet_count = dormant
        if dormant >= 5 or (liq_rows and dormant / max(len(liq_rows), 1) >= 0.4):
            report.liquidity.risk_level = "high"
        elif dormant >= 2:
            report.liquidity.risk_level = "medium"
        else:
            report.liquidity.risk_level = "low"
        report.liquidity.finding = (
            f"{dormant} scanned wallets appear dormant (>90 days since last tx). "
            "Dataset snapshot age can inflate days_since_last_tx vs wall-clock."
        )

    pct_rows = _rows(lens_results.get("percentile"))
    if pct_rows and report.percentile is not None:
        worse = _first_numeric(
            pct_rows[0],
            ("worse_than_pct_of_peers", "WORSE_THAN_PCT_OF_PEERS", "percentile_rank_0_to_100"),
        )
        top_share = _first_numeric(pct_rows[0], ("top_share_pct", "TOP_SHARE_PCT", "share_pct"))
        if worse is not None:
            report.percentile.worse_than_pct_of_peers = round(worse, 2)
        if top_share is not None:
            report.percentile.top_share_pct = round(top_share, 2)
        cohort = pct_rows[0].get("cohort") or pct_rows[0].get("COHORT")
        if cohort:
            report.percentile.cohort = str(cohort)
        if worse is not None and top_share is not None:
            report.percentile.finding = (
                f"Top wallet concentration ({top_share:.1f}% of cohort) is higher than "
                f"{worse:.0f}% of peers in {report.percentile.cohort}."
            )
            report.percentile.risk_level = (
                "high" if worse >= 90 else "medium" if worse >= 70 else "low"
            )

    dd_payload = lens_results.get("drawdown") or {}
    dd_rows = _rows(dd_payload)
    if report.drawdown is not None:
        if dd_rows:
            mdd = _first_numeric(dd_rows[0], ("max_drawdown_pct", "MAX_DRAWDOWN_PCT"))
            if mdd is not None:
                report.drawdown.max_drawdown_pct = round(mdd, 2)
                report.drawdown.finding = (
                    f"Largest observed peak-to-trough drawdown is {mdd:.1f}% (native units)."
                )
                report.drawdown.risk_level = (
                    "high" if mdd >= 40 else "medium" if mdd >= 20 else "low"
                )
        elif dd_payload.get("pending"):
            report.drawdown.max_drawdown_pct = None
            report.drawdown.risk_level = "medium"
            report.drawdown.finding = (
                "Max drawdown lens is queued — cumulative net-flow window SQL is ready "
                "for Craft (heavy transaction scan)."
            )

    cp_payload = lens_results.get("counterparty") or {}
    cp_rows = _rows(cp_payload)
    if cp_rows and report.counterparty is not None:
        share = _first_numeric(
            cp_rows[0],
            ("top_counterparty_share_pct", "TOP_COUNTERPARTY_SHARE_PCT", "share_pct"),
        )
        if share is not None:
            report.counterparty.top_counterparty_share_pct = round(share, 2)
            report.counterparty.finding = (
                f"Highest relationship-concentration proxy is {share:.1f} among scanned "
                "active wallets (not true top-counterparty volume share until Craft SQL returns)."
            )
            report.counterparty.risk_level = (
                "high" if share >= 50 else "medium" if share >= 20 else "low"
            )

    return report


def _rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        if isinstance(payload.get("rows"), list):
            return [r for r in payload["rows"] if isinstance(r, dict)]
        if isinstance(payload.get("data"), list):
            return [r for r in payload["data"] if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def _first_numeric(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in row:
            val = _coerce_pct(row[key])
            if val is not None:
                return val
    # case-insensitive fallback
    lower_map = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key.lower() in lower_map:
            val = _coerce_pct(lower_map[key.lower()])
            if val is not None:
                return val
    return None


def heuristic_report(lens_results: dict[str, Any]) -> RiskReport:
    """Deterministic fallback when Nebius is unavailable or returns bad JSON."""
    conc_rows = _rows(lens_results.get("concentration"))
    div_rows = _rows(lens_results.get("diversification"))
    liq_rows = _rows(lens_results.get("liquidity"))

    top_pct = None
    if conc_rows:
        top_pct = _first_numeric(conc_rows[0], ("pct_of_total", "PCT_OF_TOTAL", "share_pct"))
        if top_pct is not None and top_pct <= 1.0:
            top_pct *= 100.0

    conc_level = "low"
    if top_pct is not None:
        if top_pct >= 40:
            conc_level = "high"
        elif top_pct >= 20:
            conc_level = "medium"

    dist: dict[str, float] = {}
    for row in div_rows:
        chain = row.get("chain") or row.get("CHAIN") or row.get("schema_name") or row.get("SCHEMA_NAME")
        pct = _first_numeric(row, ("pct_of_total", "PCT_OF_TOTAL", "pct"))
        if chain is not None and pct is not None:
            if pct <= 1.0:
                pct *= 100.0
            dist[str(chain)] = round(pct, 2)

    max_chain_pct = max(dist.values()) if dist else None
    div_level = "low"
    if max_chain_pct is not None:
        if max_chain_pct >= 70:
            div_level = "high"
        elif max_chain_pct >= 45:
            div_level = "medium"

    dormant = 0
    for row in liq_rows:
        days = _first_numeric(row, ("days_since_last_tx", "DAYS_SINCE_LAST_TX"))
        if days is not None and days > 90:
            dormant += 1
    liq_level = "low"
    if dormant >= 5 or (liq_rows and dormant / max(len(liq_rows), 1) >= 0.4):
        liq_level = "high"
    elif dormant >= 2:
        liq_level = "medium"

    levels = [conc_level, div_level, liq_level]

    # Percentile
    pct_rows = _rows(lens_results.get("percentile"))
    worse = None
    top_share_p = top_pct
    cohort = None
    if pct_rows:
        worse = _first_numeric(pct_rows[0], ("worse_than_pct_of_peers", "WORSE_THAN_PCT_OF_PEERS"))
        top_share_p = _first_numeric(pct_rows[0], ("top_share_pct", "TOP_SHARE_PCT")) or top_pct
        cohort = pct_rows[0].get("cohort") or pct_rows[0].get("COHORT")
    pct_level = "low"
    if worse is not None:
        if worse >= 90:
            pct_level = "high"
        elif worse >= 70:
            pct_level = "medium"
    levels.append(pct_level)

    # Drawdown
    dd_rows = _rows(lens_results.get("drawdown"))
    mdd = None
    if dd_rows:
        mdd = _first_numeric(dd_rows[0], ("max_drawdown_pct", "MAX_DRAWDOWN_PCT"))
    dd_pending = bool((lens_results.get("drawdown") or {}).get("pending"))
    dd_level = "medium" if dd_pending or not dd_rows else "low"
    if mdd is not None:
        if mdd >= 40:
            dd_level = "high"
        elif mdd >= 20:
            dd_level = "medium"
        else:
            dd_level = "low"
    levels.append(dd_level)

    # Counterparty proxy
    cp_rows = _rows(lens_results.get("counterparty"))
    cp_share = None
    if cp_rows:
        cp_share = _first_numeric(cp_rows[0], ("top_counterparty_share_pct", "TOP_COUNTERPARTY_SHARE_PCT"))
    cp_level = "low"
    if cp_share is not None:
        if cp_share >= 50:
            cp_level = "high"
        elif cp_share >= 20:
            cp_level = "medium"
    levels.append(cp_level)

    overall = "high" if "high" in levels else ("medium" if "medium" in levels else "low")

    return RiskReport(
        overall_risk_rating=overall,  # type: ignore[arg-type]
        concentration={
            "finding": (
                f"Largest wallet holds {top_pct:.1f}% of scanned value."
                if top_pct is not None
                else "Concentration computed from available wallet rankings."
            ),
            "top_wallet_share_pct": round(top_pct, 2) if top_pct is not None else None,
            "risk_level": conc_level,
        },
        diversification={
            "finding": (
                f"Largest chain share is {max_chain_pct:.1f}% of scanned activity/holdings."
                if max_chain_pct is not None
                else "Chain distribution derived from available schema aggregates."
            ),
            "chain_distribution": dist,
            "risk_level": div_level,
        },
        liquidity={
            "finding": f"{dormant} scanned wallets appear dormant (>90 days since last tx).",
            "dormant_wallet_count": dormant,
            "risk_level": liq_level,
        },
        drawdown={
            "finding": (
                f"Largest observed peak-to-trough drawdown is {mdd:.1f}% (native units)."
                if mdd is not None
                else (
                    "Max drawdown lens is queued — cumulative net-flow window SQL is ready "
                    "for Craft (heavy ETH transaction scan)."
                )
            ),
            "max_drawdown_pct": round(mdd, 2) if mdd is not None else None,
            "risk_level": dd_level,
        },
        percentile={
            "finding": (
                f"Top wallet concentration ({top_share_p:.1f}% of cohort) is higher than "
                f"{worse:.0f}% of peers in {cohort or 'the scanned cohort'}."
                if worse is not None and top_share_p is not None
                else "Percentile benchmarking unavailable."
            ),
            "worse_than_pct_of_peers": round(worse, 2) if worse is not None else None,
            "top_share_pct": round(top_share_p, 2) if top_share_p is not None else None,
            "cohort": str(cohort) if cohort else "top_N_ETC_BALANCES_holders",
            "risk_level": pct_level,
        },
        counterparty={
            "finding": (
                f"Highest relationship-concentration proxy is {cp_share:.1f} "
                f"among scanned active wallets (Craft top-counterparty volume share pending)."
                if cp_share is not None
                else "Counterparty concentration unavailable."
            ),
            "top_counterparty_share_pct": round(cp_share, 2) if cp_share is not None else None,
            "risk_level": cp_level,
        },
        summary=(
            "TreasuryLens scanned on-chain CRYPTO holdings/activity across core and extended "
            f"risk lenses. Overall risk is rated {overall}. "
            "Figures are in native token units; percentile may be cohort-scoped until "
            "full-population PERCENT_RANK finishes on Craft."
        ),
        recommendations=[
            "Reduce single-wallet concentration by splitting operational keys / multisig policies.",
            "Diversify chain exposure if one network dominates treasury activity.",
            "Review dormant wallets and narrow counterparty sets for operational liquidity risk.",
            "Track max drawdown on hot wallets once the window-function scan completes.",
        ],
    )


def synthesize_report(settings: Settings, lens_results: dict[str, Any]) -> RiskReport:
    if not settings.nebius_configured:
        logger.warning("Nebius not configured — using heuristic synthesis")
        return cross_check_report(heuristic_report(lens_results), lens_results)

    client = OpenAI(base_url=settings.nebius_base_url, api_key=settings.nebius_api_key)
    user_payload = json.dumps(lens_results, default=str)[:120_000]

    def _call(extra_user: str = "") -> RiskReport:
        messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": user_payload + (("\n\n" + extra_user) if extra_user else ""),
            },
        ]
        resp = client.chat.completions.create(
            model=settings.nebius_model,
            messages=messages,
            temperature=0.2,
        )
        content = resp.choices[0].message.content or ""
        data = _extract_json(content)
        report = RiskReport.model_validate(data)
        return cross_check_report(report, lens_results)

    try:
        return _call()
    except Exception as first_err:  # noqa: BLE001
        logger.warning("Synthesis parse failed (%s); retrying once", first_err)
        try:
            return _call("Only use figures from the provided data. Return valid JSON only.")
        except Exception as second_err:  # noqa: BLE001
            logger.exception("Nebius synthesis failed: %s", second_err)
            return cross_check_report(heuristic_report(lens_results), lens_results)
