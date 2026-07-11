# Fetch CRAFT access token + resource URI

Guide based on CRAFT MCP OAuth discovery and [Data Connections](https://docs.emergence.ai/platform/data-connections) / [MCP Server](https://docs.emergence.ai/platform/mcp-server) docs.

## What you need

| Value | Where it comes from |
|---|---|
| `CRAFT_PROJECT_ID` | CRAFT console → **Settings → Project → ID** (UUID) |
| `CRAFT_ACCESS_TOKEN` | OAuth PKCE against Keycloak `hub` realm (`em-runtime-mcp`) |
| `CRAFT_RESOURCE_URI` | Data connection id: `data:{org_id}:{project_id}:{connection_name}` |
| `CRAFT_DATABASE_UUID` | Connection / database id returned by Assets API or `list_databases` |

## Discovered endpoints (Nebius / CRAFT hackathon)

```
MCP:              https://nebius.emergence.ai/mcp
Protected resource metadata:
  https://nebius.emergence.ai/.well-known/oauth-protected-resource/mcp
Authorization server:
  https://runtime.prod.emergence.ai/keycloak/realms/hub
Client ID:        em-runtime-mcp
Scopes:           openid profile email organization
Assets API:       https://nebius.emergence.ai/api/assets/data
                  (also try https://runtime.prod.emergence.ai/api/assets/data)
```

## Fast path (recommended)

1. Put your project UUID in [`.env`](../.env):

```env
CRAFT_PROJECT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Also set the same value as a **Windows user environment variable** so Cursor can expand `${env:CRAFT_PROJECT_ID}` in [`.cursor/mcp.json`](../.cursor/mcp.json).

2. Run the helper (opens browser login):

```bash
cd backend
.\.venv\Scripts\activate
pip install httpx python-dotenv   # already in project deps
python ../scripts/fetch_craft_creds.py
```

The script will:

1. Complete **Authorization Code + PKCE** with `CLIENT_ID=em-runtime-mcp`
2. Write `CRAFT_ACCESS_TOKEN` (+ refresh if returned) into `.env`
3. Call `GET /assets/data` with `Authorization` + `X-Project-ID` to list connections
4. Prefer a connection mentioning **CRYPTO** and write `CRAFT_RESOURCE_URI` / `CRAFT_DATABASE_UUID`
5. Smoke-test MCP `search_schema` with query `CRYPTO`

3. Then run schema recon:

```bash
python ../scripts/schema_recon.py
```

## Manual fallback (CRAFT UI)

### Access token (interactive)

1. Ensure [`.cursor/mcp.json`](../.cursor/mcp.json) has the Craft server + `auth.CLIENT_ID`.
2. Reload MCP in Cursor and invoke any Craft tool → browser OAuth.
3. Cursor stores the token for MCP tools automatically.
4. For the **FastAPI backend**, you still need a bearer in `.env` — use `fetch_craft_creds.py` (Cursor does not expose its stored token to your app).

Tokens expire quickly (~5 minutes for interactive). Re-run the script when you see `invalid_token` / `missing_authorization`.

### Resource URI (console)

1. Open https://nebius.emergence.ai → your project.
2. Go to **Data Connections** (Assets).
3. Open the CRYPTO connection.
4. Copy `resource_uri` — must be four segments:

```text
data:{org_id}:{project_id}:{connection_name}
```

Example shape: `data:acme:proj-uuid:CRYPTO`  
Simplified `data:CRYPTO` is **rejected**.

Paste into `.env`:

```env
CRAFT_RESOURCE_URI=data:your-org:your-project:CRYPTO
```

## Using the values

```env
CRAFT_PROJECT_ID=...
CRAFT_ACCESS_TOKEN=...
CRAFT_RESOURCE_URI=data:...:...:...
CRAFT_DATABASE_UUID=...   # optional until recon fills it
```

Restart uvicorn after updating `.env`. `/api/health` should show `craft_configured: true`.

## Cursor header bug reminder

If Cursor MCP tools connect but every call fails on **project scope** (not auth), Cursor may be dropping `X-Project-ID` after OAuth discovery. Use this script / VS Code / Claude Code for recon — they send the header explicitly.
