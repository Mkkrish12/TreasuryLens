"""Extra treasury risk lenses beyond the core three.

Priority implementations:
1. Max drawdown (window functions) — SQL ready; filled when Craft returns rows
5. Population / cohort percentile benchmarking — derived from concentration cohort
2. Counterparty concentration — derived from liquidity counterparties when available
"""

from __future__ import annotations

from typing import Any


DRAWDOWN_SQL = """
WITH top_addrs AS (
  SELECT from_address AS address
  FROM CRYPTO.CRYPTO_ETHEREUM.TRANSACTIONS
  WHERE from_address IS NOT NULL
    AND TO_TIMESTAMP(block_timestamp, 6) >= '2024-01-01'
  GROUP BY from_address
  ORDER BY COUNT(*) DESC
  LIMIT 3
),
flows AS (
  SELECT
    a.address,
    DATE_TRUNC('day', TO_TIMESTAMP(t.block_timestamp, 6)) AS day,
    SUM(CASE WHEN t.to_address = a.address THEN t.value ELSE 0 END)
      - SUM(CASE WHEN t.from_address = a.address THEN t.value ELSE 0 END) AS net_flow
  FROM top_addrs a
  JOIN CRYPTO.CRYPTO_ETHEREUM.TRANSACTIONS t
    ON t.from_address = a.address OR t.to_address = a.address
  WHERE TO_TIMESTAMP(t.block_timestamp, 6) >= '2024-01-01'
  GROUP BY 1, 2
),
cum AS (
  SELECT address, day, net_flow,
    SUM(net_flow) OVER (
      PARTITION BY address ORDER BY day
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cum_bal
  FROM flows
),
peaks AS (
  SELECT address, day, cum_bal,
    MAX(cum_bal) OVER (
      PARTITION BY address ORDER BY day
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS run_max
  FROM cum
)
SELECT address,
  ROUND(MAX(CASE WHEN run_max > 0 THEN (run_max - cum_bal) / run_max * 100 ELSE 0 END), 2)
    AS max_drawdown_pct,
  MAX(run_max) AS peak_balance_native,
  MIN(cum_bal) AS trough_balance_native
FROM peaks
GROUP BY address
ORDER BY max_drawdown_pct DESC
""".strip()

PERCENTILE_SQL = """
WITH bal AS (
  SELECT address, eth_balance
  FROM CRYPTO.CRYPTO_ETHEREUM_CLASSIC.BALANCES
  WHERE eth_balance IS NOT NULL AND eth_balance > 0
),
tot AS (SELECT SUM(eth_balance) AS total_bal FROM bal),
shares AS (
  SELECT b.address, b.eth_balance / NULLIF(t.total_bal, 0) * 100 AS share_pct
  FROM bal b CROSS JOIN tot t
),
top1 AS (SELECT * FROM shares ORDER BY share_pct DESC LIMIT 1),
ranks AS (
  SELECT address, share_pct,
         PERCENT_RANK() OVER (ORDER BY share_pct) * 100 AS worse_than_pct_of_peers
  FROM shares
)
SELECT t.address AS top_address,
       ROUND(t.share_pct, 4) AS top_share_pct,
       ROUND(r.worse_than_pct_of_peers, 2) AS worse_than_pct_of_peers
FROM top1 t JOIN ranks r ON t.address = r.address
""".strip()

COUNTERPARTY_SQL = """
WITH top_senders AS (
  SELECT from_address
  FROM CRYPTO.CRYPTO_ETHEREUM.TRANSACTIONS
  WHERE from_address IS NOT NULL
    AND TO_TIMESTAMP(block_timestamp, 6) >= '2024-01-01'
  GROUP BY from_address
  ORDER BY COUNT(*) DESC
  LIMIT 5
),
flows AS (
  SELECT s.from_address AS address, t.to_address AS counterparty, COUNT(*) AS tx_count
  FROM top_senders s
  JOIN CRYPTO.CRYPTO_ETHEREUM.TRANSACTIONS t
    ON t.from_address = s.from_address
  WHERE TO_TIMESTAMP(t.block_timestamp, 6) >= '2024-01-01'
  GROUP BY 1, 2
),
ranked AS (
  SELECT address, counterparty, tx_count,
         tx_count / SUM(tx_count) OVER (PARTITION BY address) * 100 AS share_pct,
         ROW_NUMBER() OVER (PARTITION BY address ORDER BY tx_count DESC) AS rn
  FROM flows
)
SELECT address, counterparty, tx_count, ROUND(share_pct, 2) AS top_counterparty_share_pct
FROM ranked
WHERE rn = 1
ORDER BY top_counterparty_share_pct DESC
""".strip()


def derive_percentile_from_concentration(conc: dict[str, Any]) -> dict[str, Any]:
    """Honest cohort percentile among the scanned top-N balance holders."""
    rows = list(conc.get("rows") or [])
    if not rows:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}

    n = len(rows)
    top = rows[0]
    top_share = float(top.get("pct_of_total") or 0)
    # Rank 1 of N ⇒ worse than (N-1)/N of this cohort
    worse_than = round((n - 1) / n * 100, 2) if n > 1 else 0.0
    dist = []
    for i, row in enumerate(rows):
        dist.append(
            {
                "rank": i + 1,
                "address": str(row.get("address") or "")[:16] + "…",
                "share_pct": round(float(row.get("pct_of_total") or 0), 2),
            }
        )
    return {
        "columns": [
            "top_address",
            "top_share_pct",
            "worse_than_pct_of_peers",
            "cohort",
            "cohort_size",
        ],
        "rows": [
            {
                "top_address": top.get("address"),
                "top_share_pct": round(top_share, 2),
                "worse_than_pct_of_peers": worse_than,
                "cohort": "top_N_ETC_BALANCES_holders",
                "cohort_size": n,
            }
        ],
        "distribution": dist,
        "row_count": 1,
        "truncated": False,
        "note": (
            "Percentile framed within the scanned top-N ETC BALANCES cohort "
            "(not full population). Full-table PERCENT_RANK SQL is prepared for Craft."
        ),
    }


def derive_counterparty_from_liquidity(liq: dict[str, Any]) -> dict[str, Any]:
    """Proxy relationship risk from unique counterparties / tx density.

    True top-counterparty volume share needs COUNTERPARTY_SQL on Craft.
    Until then: prefer avg txs per counterparty when networks are broad;
    use 100/unique_counterparties only when the counterparty set is small.
    """
    rows = list(liq.get("rows") or [])
    out = []
    for row in rows:
        cp = row.get("unique_counterparties")
        txs = row.get("tx_count_30d") or row.get("tx_count")
        try:
            cp_n = float(cp) if cp is not None else None
            tx_n = float(txs) if txs is not None else None
        except (TypeError, ValueError):
            continue
        if cp_n is None or tx_n is None or tx_n <= 0 or cp_n <= 0:
            continue
        avg_per_cp = round(tx_n / cp_n, 2)
        if cp_n <= 20:
            share_proxy = round(min(100.0, (1.0 / cp_n) * 100), 2)
            metric_note = "Proxy = 100/unique_counterparties (small network)"
        else:
            # Broad networks: density is the readable signal (higher = stickier counterparties)
            share_proxy = round(min(100.0, avg_per_cp * 10.0), 2)
            metric_note = "Proxy ~ avg txs/counterparty x 10 (broad network)"
        out.append(
            {
                "address": row.get("address"),
                "unique_counterparties": int(cp_n),
                "tx_count": int(tx_n),
                "avg_txs_per_counterparty": avg_per_cp,
                "top_counterparty_share_pct": share_proxy,
                "note": metric_note,
            }
        )
    out.sort(key=lambda r: r["top_counterparty_share_pct"], reverse=True)
    return {
        "columns": [
            "address",
            "unique_counterparties",
            "tx_count",
            "avg_txs_per_counterparty",
            "top_counterparty_share_pct",
        ],
        "rows": out[:12],
        "row_count": len(out[:12]),
        "truncated": False,
        "note": (
            "Relationship-risk proxy until Craft COUNTERPARTY_SQL returns true "
            "top-counterparty volume share. Broad networks use tx density; "
            "narrow networks use 100/unique_counterparties."
        ),
    }


def empty_drawdown_payload() -> dict[str, Any]:
    return {
        "columns": [
            "address",
            "max_drawdown_pct",
            "peak_balance_native",
            "trough_balance_native",
        ],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "pending": True,
        "note": (
            "Max drawdown uses cumulative net flow + running max "
            "(SUM/MAX window functions). SQL is ready; re-run when Craft MCP is connected "
            "(heavy scan on ETH transactions)."
        ),
        "sql": DRAWDOWN_SQL,
    }


def enrich_lens_results(lens_results: dict[str, Any]) -> dict[str, Any]:
    """Attach derived extra lenses onto an existing core lens_results dict."""
    out = dict(lens_results)
    if "percentile" not in out or not (out.get("percentile") or {}).get("rows"):
        out["percentile"] = derive_percentile_from_concentration(
            out.get("concentration") or {}
        )
    if "counterparty" not in out or not (out.get("counterparty") or {}).get("rows"):
        out["counterparty"] = derive_counterparty_from_liquidity(
            out.get("liquidity") or {}
        )
    if "drawdown" not in out:
        out["drawdown"] = empty_drawdown_payload()
    return out
