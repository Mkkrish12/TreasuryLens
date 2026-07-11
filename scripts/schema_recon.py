#!/usr/bin/env python3
"""Step 0 — CRYPTO schema recon via CRAFT MCP.

Requires CRAFT_PROJECT_ID and CRAFT_ACCESS_TOKEN in env / .env.
Writes docs/schema_notes.md and docs/schema_recon.json, and prints a summary.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(BACKEND / ".env")

from app.settings import get_settings  # noqa: E402
from craft.craft_client import CraftClient  # noqa: E402


SEARCH_TERMS = ["address", "balance", "wallet", "transaction", "value", "amount", "CRYPTO"]


def _as_list(payload) -> list:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("databases", "results", "items", "data", "tables", "schemas"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    return []


def _guess_role(name: str) -> str:
    n = name.lower()
    if "balance" in n or "account" in n:
        return "balances"
    if "transfer" in n or "token_transfer" in n:
        return "transfers"
    if "transaction" in n or "tx" in n:
        return "transactions"
    if "block" in n:
        return "blocks"
    return "other"


async def main() -> int:
    settings = get_settings()
    if not settings.craft_project_id:
        print("ERROR: CRAFT_PROJECT_ID is not set.")
        print("Set it in .env and obtain CRAFT_ACCESS_TOKEN via OAuth / service account.")
        return 1
    if not settings.craft_access_token:
        print("WARNING: CRAFT_ACCESS_TOKEN missing — calls may fail with invalid_token.")

    craft = CraftClient(settings)
    notes: list[str] = []
    payload: dict = {
        "database_name": "CRYPTO",
        "database_uuid": "",
        "resource_uri": settings.craft_resource_uri,
        "chain_schemas": [],
        "tables": [],
        "has_balance_table": False,
        "has_usd_price_column": False,
        "value_unit": "native_token",
        "timestamp_column_hint": "block_timestamp",
        "recon_complete": False,
        "recon_notes": "",
        "demo_wallets": [],
        "raw": {},
    }

    try:
        hello = await craft.hello_world()
        notes.append(f"hello_world: {hello}")
        print("hello_world OK:", hello)

        dbs = await craft.list_databases(settings.craft_resource_uri)
        payload["raw"]["list_databases"] = dbs
        notes.append("## list_databases\n```json\n" + json.dumps(dbs, indent=2, default=str)[:8000] + "\n```")

        for item in _as_list(dbs):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("database_name") or "")
            if name.upper() == "CRYPTO" or "CRYPTO" in name.upper():
                payload["database_name"] = name or "CRYPTO"
                payload["database_uuid"] = str(
                    item.get("id")
                    or item.get("uuid")
                    or item.get("database")
                    or item.get("connection_id")
                    or ""
                )
                payload["resource_uri"] = str(
                    item.get("resource_uri") or settings.craft_resource_uri or ""
                )
                schemas = item.get("schemas") or item.get("schema_names") or []
                if isinstance(schemas, list):
                    payload["chain_schemas"] = [str(s) for s in schemas]
                break

        search_hits = {}
        for term in SEARCH_TERMS:
            try:
                hits = await craft.search_schema(term)
                search_hits[term] = hits
                print(f"search_schema({term!r}) ok")
            except Exception as exc:  # noqa: BLE001
                search_hits[term] = {"error": str(exc)}
                print(f"search_schema({term!r}) failed: {exc}")
        payload["raw"]["search_schema"] = search_hits
        notes.append("## search_schema\nTerms: " + ", ".join(SEARCH_TERMS))

        # Collect candidate table FQNs from search hits
        candidates: list[str] = []
        for hits in search_hits.values():
            for item in _as_list(hits):
                if not isinstance(item, dict):
                    continue
                fqn = (
                    item.get("fqn")
                    or item.get("table_fqn")
                    or item.get("fully_qualified_name")
                    or item.get("name")
                )
                if fqn and isinstance(fqn, str) and fqn.count(".") >= 1:
                    candidates.append(fqn)
                schema = item.get("schema_name") or item.get("schema")
                if schema and schema not in payload["chain_schemas"]:
                    payload["chain_schemas"].append(str(schema))

        # Deduplicate, prefer balance/transaction tables
        uniq = []
        for c in candidates:
            if c not in uniq:
                uniq.append(c)
        prefer = sorted(
            uniq,
            key=lambda x: (
                0 if "balance" in x.lower() else 1 if "transaction" in x.lower() else 2,
                x,
            ),
        )[:6]

        resource_uri = payload["resource_uri"] or settings.craft_resource_uri
        for fqn in prefer:
            try:
                schema = await craft.get_schema(resource_uri, fqn)
                payload["raw"].setdefault("get_schema", {})[fqn] = schema
                parts = fqn.split(".")
                table_name = parts[-1]
                schema_name = parts[-2] if len(parts) >= 2 else ""
                key_columns = {}
                cols = []
                if isinstance(schema, dict):
                    cols = schema.get("columns") or schema.get("fields") or []
                for col in cols if isinstance(cols, list) else []:
                    if isinstance(col, dict):
                        cname = str(col.get("name") or col.get("column_name") or "")
                        ctype = str(col.get("type") or col.get("data_type") or "")
                        key_columns[cname] = ctype
                        lower = cname.lower()
                        if any(p in lower for p in ("usd", "price", "fiat")):
                            payload["has_usd_price_column"] = True
                        if "timestamp" in lower or lower.endswith("_at") or lower == "time":
                            payload["timestamp_column_hint"] = cname
                role = _guess_role(table_name)
                if role == "balances":
                    payload["has_balance_table"] = True
                payload["tables"].append(
                    {
                        "fqn": fqn,
                        "schema_name": schema_name,
                        "table_name": table_name,
                        "role": role,
                        "key_columns": key_columns,
                        "notes": "",
                    }
                )
                print(f"get_schema({fqn}) ok — {len(key_columns)} columns")
            except Exception as exc:  # noqa: BLE001
                print(f"get_schema({fqn}) failed: {exc}")

            try:
                sample = await craft.sample_data(resource_uri, fqn, limit=5)
                payload["raw"].setdefault("sample_data", {})[fqn] = sample
                # Harvest demo addresses
                rows = []
                if isinstance(sample, dict):
                    rows = sample.get("rows") or sample.get("data") or []
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    for k, v in row.items():
                        if "address" in str(k).lower() and isinstance(v, str) and len(v) >= 10:
                            if v not in payload["demo_wallets"] and len(payload["demo_wallets"]) < 5:
                                payload["demo_wallets"].append(v)
                # Unit heuristic
                sample_txt = json.dumps(sample, default=str).lower()
                if "wei" in sample_txt:
                    payload["value_unit"] = "wei"
                elif "satoshi" in sample_txt or "sats" in sample_txt:
                    payload["value_unit"] = "satoshi"
                print(f"sample_data({fqn}) ok")
            except Exception as exc:  # noqa: BLE001
                print(f"sample_data({fqn}) failed: {exc}")

        payload["recon_complete"] = bool(payload["tables"] or payload["database_uuid"])
        if payload["has_balance_table"]:
            decision = "Balance table found — concentration can use SUM(balance)."
        else:
            decision = (
                "No balance table confirmed — derive holdings from inbound-outbound "
                "or use tx volume proxy with LIMIT."
            )
        payload["recon_notes"] = decision
        notes.insert(0, f"# CRYPTO schema recon\n\n**Decision:** {decision}\n")
        notes.append(f"\n## Summary payload\n```json\n{json.dumps({k: v for k, v in payload.items() if k != 'raw'}, indent=2)}\n```")

    finally:
        await craft.close()

    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "schema_notes.md").write_text("\n\n".join(notes), encoding="utf-8")
    (docs / "schema_recon.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    # Write Python snippet for schema_context update helper
    print("\nWrote docs/schema_notes.md and docs/schema_recon.json")
    print("recon_complete:", payload["recon_complete"])
    print("has_balance_table:", payload["has_balance_table"])
    print("has_usd_price_column:", payload["has_usd_price_column"])
    print("chains:", payload["chain_schemas"])
    print("tables:", [t["fqn"] for t in payload["tables"]])
    return 0 if payload["recon_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
