from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agent.recon_loader import load_recon_if_present
from agent.schema_context import DEMO_WALLETS, SCHEMA
from agent.treasury_agent import generate_treasury_report
from app.settings import get_settings
from craft.craft_client import CraftClient
from models.report import ReportRequest, ReportResponse

load_dotenv()
load_dotenv("../.env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("treasurylens")

craft_client: CraftClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global craft_client
    settings = get_settings()
    if load_recon_if_present():
        logger.info("Loaded schema recon (complete=%s)", SCHEMA.recon_complete)
    if settings.craft_headless_ready:
        craft_client = CraftClient(settings)
        logger.info("CRAFT headless client ready (url=%s)", settings.craft_mcp_url)
    else:
        logger.warning(
            "CRAFT headless token not set — demo fallback enabled=%s "
            "(Cursor MCP OAuth still works for interactive recon)",
            settings.allow_demo_fallback,
        )
    yield
    if craft_client is not None:
        await craft_client.close()


app = FastAPI(title="TreasuryLens", version="0.1.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    s = get_settings()
    return {
        "ok": True,
        "craft_project_id_set": bool(s.craft_project_id),
        "craft_configured": s.craft_configured,
        "craft_headless_ready": s.craft_headless_ready,
        "nebius_configured": s.nebius_configured,
        "schema_recon_complete": SCHEMA.recon_complete,
        "demo_fallback": s.allow_demo_fallback,
        "resource_uri": s.craft_resource_uri or SCHEMA.resource_uri or None,
        "database_uuid": s.craft_database_uuid or SCHEMA.database_uuid or None,
    }


@app.get("/api/demo-wallets")
async def demo_wallets():
    return {"addresses": DEMO_WALLETS, "recon_complete": SCHEMA.recon_complete}


@app.get("/api/schema-status")
async def schema_status():
    return {
        "database_name": SCHEMA.database_name,
        "database_uuid": SCHEMA.database_uuid,
        "chain_schemas": SCHEMA.chain_schemas,
        "has_balance_table": SCHEMA.has_balance_table,
        "has_usd_price_column": SCHEMA.has_usd_price_column,
        "value_unit": SCHEMA.value_unit,
        "recon_complete": SCHEMA.recon_complete,
        "recon_notes": SCHEMA.recon_notes,
        "tables": [
            {
                "fqn": t.fqn,
                "role": t.role,
                "schema_name": t.schema_name,
                "table_name": t.table_name,
                "key_columns": t.key_columns,
                "notes": t.notes,
            }
            for t in SCHEMA.tables
        ],
    }


@app.post("/api/report", response_model=ReportResponse)
async def create_report(request: ReportRequest) -> ReportResponse:
    s = get_settings()
    try:
        return await generate_treasury_report(s, request, craft_client)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Report generation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
