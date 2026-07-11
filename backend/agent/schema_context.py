"""
CRYPTO schema context — filled from live Craft MCP recon (2026-07-11).

Connection slug: crypto-70a8f494
Database FQN:    crypto-70a8f494.CRYPTO
Resource URI:    data:b732e1b7-49b1-404c-b02f-2d131dc756b9:70a8f494-bf79-477d-8999-23d5a7d6e331:crypto-70a8f494
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TableRef:
    fqn: str
    schema_name: str
    table_name: str
    role: str
    key_columns: dict[str, str] = field(default_factory=dict)
    notes: str = ""


CHAIN_SCHEMAS = [
    "CRYPTO_BAND",
    "CRYPTO_BITCOIN",
    "CRYPTO_BITCOIN_CASH",
    "CRYPTO_DASH",
    "CRYPTO_ETHEREUM",
    "CRYPTO_ETHEREUM_CLASSIC",
    "CRYPTO_ZILLIQA",
]


def _live_tables() -> list[TableRef]:
    conn = "crypto-70a8f494"
    db = "CRYPTO"
    tables: list[TableRef] = [
        TableRef(
            fqn=f"{conn}.{db}.CRYPTO_ETHEREUM_CLASSIC.BALANCES",
            schema_name="CRYPTO_ETHEREUM_CLASSIC",
            table_name="BALANCES",
            role="balances",
            key_columns={"address": "STRING", "eth_balance": "NUMERIC"},
            notes="Confirmed balances table — eth_balance in smallest unit.",
        ),
        TableRef(
            fqn=f"{conn}.{db}.CRYPTO_ETHEREUM.TRANSACTIONS",
            schema_name="CRYPTO_ETHEREUM",
            table_name="TRANSACTIONS",
            role="transactions",
            key_columns={
                "hash": "STRING",
                "from_address": "STRING",
                "to_address": "STRING",
                "value": "NUMERIC",
                "block_timestamp": "TIMESTAMP",
            },
            notes="Ethereum txs — value typically wei.",
        ),
        TableRef(
            fqn=f"{conn}.{db}.CRYPTO_ETHEREUM.TOKEN_TRANSFERS",
            schema_name="CRYPTO_ETHEREUM",
            table_name="TOKEN_TRANSFERS",
            role="transfers",
            key_columns={
                "token_address": "STRING",
                "from_address": "STRING",
                "to_address": "STRING",
                "value": "NUMERIC",
                "block_timestamp": "TIMESTAMP",
            },
            notes="",
        ),
        TableRef(
            fqn=f"{conn}.{db}.CRYPTO_BITCOIN.TRANSACTIONS",
            schema_name="CRYPTO_BITCOIN",
            table_name="TRANSACTIONS",
            role="transactions",
            key_columns={"hash": "STRING", "block_timestamp": "TIMESTAMP", "output_value": "NUMERIC"},
            notes="UTXO-style; pair with INPUTS/OUTPUTS for address holdings.",
        ),
        TableRef(
            fqn=f"{conn}.{db}.CRYPTO_BITCOIN.OUTPUTS",
            schema_name="CRYPTO_BITCOIN",
            table_name="OUTPUTS",
            role="outputs",
            key_columns={
                "transaction_hash": "STRING",
                "value": "NUMERIC",
                "addresses": "ARRAY",
                "block_timestamp": "TIMESTAMP",
            },
            notes="",
        ),
    ]
    return tables


@dataclass
class SchemaContext:
    database_name: str = "CRYPTO"
    database_uuid: str = "59930fbf-9f35-4e39-b41d-c8a71873b1bf"
    database_fqn: str = "crypto-70a8f494.CRYPTO"
    connection_slug: str = "crypto-70a8f494"
    resource_uri: str = (
        "data:b732e1b7-49b1-404c-b02f-2d131dc756b9:"
        "70a8f494-bf79-477d-8999-23d5a7d6e331:crypto-70a8f494"
    )
    chain_schemas: list[str] = field(default_factory=lambda: list(CHAIN_SCHEMAS))
    tables: list[TableRef] = field(default_factory=_live_tables)
    has_balance_table: bool = True
    has_usd_price_column: bool = False
    value_unit: str = "native_token"
    timestamp_column_hint: str = "block_timestamp"
    recon_complete: bool = True
    recon_notes: str = (
        "Live recon via Craft MCP. Connection slug crypto-70a8f494; "
        "BALANCES confirmed on CRYPTO_ETHEREUM_CLASSIC; 7 chain schemas; "
        "no USD price column assumed — report native units."
    )

    def grounding_prompt(self) -> str:
        chains = ", ".join(self.chain_schemas)
        table_lines = []
        for t in self.tables[:12]:
            cols = ", ".join(f"{k}={v}" for k, v in list(t.key_columns.items())[:6]) or "columns TBD"
            table_lines.append(f"- {t.fqn} ({t.role}): {cols}. {t.notes}".strip())
        tables_block = "\n".join(table_lines)
        balance_note = (
            "BALANCES table exists (at least CRYPTO_ETHEREUM_CLASSIC.BALANCES) — "
            "prefer SUM(eth_balance)/balance columns per address where available."
            if self.has_balance_table
            else "No balances table — derive from transactions/outputs."
        )
        return f"""CRYPTO dataset grounding (Craft MCP):
- Connection slug: {self.connection_slug}
- Database: {self.database_name} (FQN {self.database_fqn}, id {self.database_uuid})
- Resource URI: {self.resource_uri}
- Chain schemas (7): {chains}
- Value unit: {self.value_unit} (ETH-like: wei; UTXO: satoshi) — never invent USD
- Timestamp hint: {self.timestamp_column_hint}
- {balance_note}
Known tables:
{tables_block}
Recon: complete — {self.recon_notes}
"""


SCHEMA = SchemaContext()

DEMO_WALLETS: list[str] = []


def update_from_recon(payload: dict) -> SchemaContext:
    global SCHEMA, DEMO_WALLETS
    SCHEMA.database_name = payload.get("database_name", SCHEMA.database_name)
    SCHEMA.database_uuid = payload.get("database_uuid", SCHEMA.database_uuid)
    SCHEMA.database_fqn = payload.get("database_fqn", SCHEMA.database_fqn)
    SCHEMA.connection_slug = payload.get("connection_slug", SCHEMA.connection_slug)
    SCHEMA.resource_uri = payload.get("resource_uri", SCHEMA.resource_uri)
    if payload.get("chain_schemas"):
        SCHEMA.chain_schemas = payload["chain_schemas"]
    SCHEMA.has_balance_table = bool(payload.get("has_balance_table", SCHEMA.has_balance_table))
    SCHEMA.has_usd_price_column = bool(payload.get("has_usd_price_column", False))
    SCHEMA.value_unit = payload.get("value_unit", SCHEMA.value_unit)
    SCHEMA.timestamp_column_hint = payload.get(
        "timestamp_column_hint", SCHEMA.timestamp_column_hint
    )
    SCHEMA.recon_complete = bool(payload.get("recon_complete", True))
    SCHEMA.recon_notes = payload.get("recon_notes", SCHEMA.recon_notes)
    if payload.get("tables"):
        SCHEMA.tables = [
            TableRef(**t) if isinstance(t, dict) else t for t in payload["tables"]
        ]
    if payload.get("demo_wallets"):
        DEMO_WALLETS = list(payload["demo_wallets"])
    return SCHEMA
