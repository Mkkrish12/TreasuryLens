# TreasuryLens

Corporate crypto treasury risk dashboard for the Emergence / Nebius **CRAFT** hackathon.

Point it at CRYPTO wallets (or run a population-level scan) and get a structured risk report across:

1. **Concentration** — top-wallet share of scanned value
2. **Chain diversification** — distribution across CRYPTO chain schemas
3. **Liquidity / activity** — recency, frequency, dormant wallets

Values are reported in **native token units** unless the dataset exposes a price column.

## Stack

- **Backend:** FastAPI + CRAFT MCP client (`fastmcp`) + Nebius Token Factory (`nvidia/nemotron-3-super-120b-a12b`)
- **Frontend:** React + Vite + Plotly
- **Data:** CRAFT MCP at `https://nebius.emergence.ai/mcp`

## Prerequisites

1. CRAFT account + `CRAFT_PROJECT_ID` (Settings → Project → ID)
2. CRAFT access token (OAuth in Cursor, or service-account bearer for headless)
3. Nebius Token Factory API key

Copy `.env.example` → `.env` and fill in values. Also set `CRAFT_PROJECT_ID` as a Windows user environment variable so Cursor expands it in [`.cursor/mcp.json`](.cursor/mcp.json).

### Cursor MCP note

Configured in [`.cursor/mcp.json`](.cursor/mcp.json) with CRAFT OAuth (`CLIENT_ID: em-runtime-mcp`). Set `CRAFT_PROJECT_ID` as a **Windows user environment variable** (Cursor expands `${env:CRAFT_PROJECT_ID}` into `X-Project-ID`), then reload MCP / use a tool once to complete browser OAuth (PKCE).

**Known Cursor bug:** after OAuth discovery, Cursor may silently drop the `headers` block — tools connect but every call fails with a project-scoping error (not auth). If that happens, flag it in `#hack` and fall back to VS Code ([`.vscode/mcp.json`](.vscode/mcp.json)) or Claude Code.

## Quick start

```bash
# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\activate   # Windows
pip install -e .
uvicorn app.main:app --reload --port 8001

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — click **Run population-level scan**.

> Note: Vite proxies `/api` → `http://127.0.0.1:8001`. Change both if you prefer another port.

Without CRAFT credentials the API runs in **labeled demo mode** so the UI and synthesis path can be rehearsed.

## Schema recon (Step 0)

```bash
cd backend
.\.venv\Scripts\activate
python ../scripts/schema_recon.py
```

Writes `docs/schema_notes.md` and `docs/schema_recon.json`. The backend loads recon JSON on startup.

## API

- `GET /api/health`
- `GET /api/schema-status`
- `GET /api/demo-wallets`
- `POST /api/report` `{ "mode": "population" | "wallets", "addresses": [] }`

Response: `{ report_json, charts[], sql_used[], demo_mode }`

## Rate limits

`execute_query` is capped at **10/min** on CRAFT. The backend spaces calls ≥6s apart.
