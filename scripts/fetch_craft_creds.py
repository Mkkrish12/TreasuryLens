#!/usr/bin/env python3
"""
Fetch CRAFT access token (OAuth PKCE) and discover CRYPTO resource_uri.

Based on CRAFT MCP OAuth discovery:
  resource_metadata → authorization_servers: hub realm
  client_id: em-runtime-mcp
  scopes: openid profile email organization

Usage:
  1. Set CRAFT_PROJECT_ID in .env (Settings → Project → ID in CRAFT console)
  2. python scripts/fetch_craft_creds.py
  3. Browser opens → sign in → script writes CRAFT_ACCESS_TOKEN + CRAFT_RESOURCE_URI to .env
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

MCP_URL = os.getenv("CRAFT_MCP_URL", "https://nebius.emergence.ai/mcp")
CLIENT_ID = "em-runtime-mcp"
SCOPES = "openid profile email organization"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"

# Discovered from https://nebius.emergence.ai/.well-known/oauth-protected-resource/mcp
AUTH_SERVER = "https://runtime.prod.emergence.ai/keycloak/realms/hub"
TOKEN_URL = f"{AUTH_SERVER}/protocol/openid-connect/token"
AUTH_URL = f"{AUTH_SERVER}/protocol/openid-connect/auth"

# Assets API hosts to try for listing data connections
ASSETS_BASES = [
    "https://nebius.emergence.ai/api",
    "https://runtime.prod.emergence.ai/api",
]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.code = (qs.get("code") or [None])[0]
        _CallbackHandler.error = (qs.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        body = (
            "<html><body style='font-family:sans-serif;padding:2rem'>"
            "<h2>CRAFT login complete</h2>"
            "<p>You can close this tab and return to the terminal.</p>"
            "</body></html>"
        )
        self.wfile.write(body.encode())

    def log_message(self, format, *args):  # noqa: A003
        return


def oauth_pkce() -> dict:
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print("Opening browser for CRAFT OAuth…")
    print(f"If it does not open, visit:\n  {url}\n")
    webbrowser.open(url)

    deadline = time.time() + 300
    while _CallbackHandler.code is None and _CallbackHandler.error is None and time.time() < deadline:
        time.sleep(0.2)
    server.server_close()

    if _CallbackHandler.error:
        raise RuntimeError(f"OAuth error: {_CallbackHandler.error}")
    if not _CallbackHandler.code:
        raise RuntimeError("Timed out waiting for OAuth callback (5 minutes).")

    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": _CallbackHandler.code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Token exchange failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"No access_token in response: {data}")
    return data


def list_data_connections(token: str, project_id: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Project-ID": project_id,
        "Accept": "application/json",
    }
    errors = []
    for base in ASSETS_BASES:
        url = f"{base}/assets/data"
        try:
            r = httpx.get(url, headers=headers, params={"limit": 100}, timeout=30)
            print(f"GET {url} → {r.status_code}")
            if r.status_code == 200:
                payload = r.json()
                if isinstance(payload, list):
                    return payload
                for key in ("items", "data", "results", "connections"):
                    if isinstance(payload.get(key), list):
                        return payload[key]
                return [payload] if isinstance(payload, dict) else []
            errors.append(f"{url}: {r.status_code} {r.text[:200]}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Could not list data connections:\n" + "\n".join(errors))


def pick_crypto_resource(connections: list[dict]) -> tuple[str | None, str | None]:
    """Return (resource_uri, database_uuid_or_id)."""
    best_uri = None
    best_id = None
    for item in connections:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("connection_name") or "").upper()
        uri = item.get("resource_uri") or item.get("uri") or item.get("id")
        db_id = (
            item.get("database")
            or item.get("database_id")
            or item.get("connection_id")
            or item.get("uuid")
            or item.get("id")
        )
        blob = json.dumps(item, default=str).upper()
        if "CRYPTO" in name or "CRYPTO" in blob:
            return (str(uri) if uri else None, str(db_id) if db_id else None)
        if uri and not best_uri:
            best_uri, best_id = str(uri), str(db_id) if db_id else None
    return best_uri, best_id


def mcp_search_schema(token: str, project_id: str, query: str = "CRYPTO") -> dict | list | str:
    """Optional: call search_schema via raw MCP JSON-RPC to confirm catalog access."""
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Project-ID": project_id,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "treasurylens-fetch-creds", "version": "1.0"},
        },
    }
    with httpx.Client(timeout=60) as client:
        r = client.post(MCP_URL, headers=headers, json=init)
        print(f"MCP initialize → {r.status_code}")
        session = r.headers.get("mcp-session-id") or r.headers.get("MCP-Session-Id")
        if session:
            headers["MCP-Session-Id"] = session
        # notifications/initialized
        client.post(
            MCP_URL,
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        r2 = client.post(
            MCP_URL,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "search_schema", "arguments": {"query": query}},
            },
        )
        print(f"MCP search_schema({query!r}) → {r2.status_code}")
        text = r2.text
        # SSE or JSON
        if "data:" in text:
            for line in text.splitlines():
                if line.startswith("data:"):
                    try:
                        return json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
        try:
            return r2.json()
        except Exception:  # noqa: BLE001
            return text[:2000]


def upsert_env(updates: dict[str, str]) -> None:
    env_path = ROOT / ".env"
    existing: dict[str, str] = {}
    lines: list[str] = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                lines.append(line)
                continue
            key, _, val = line.partition("=")
            existing[key.strip()] = val
            lines.append(line)

    for key, value in updates.items():
        existing[key] = value
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Updated {env_path}")


def main() -> int:
    project_id = os.getenv("CRAFT_PROJECT_ID", "").strip()
    if not project_id or project_id.startswith("your-"):
        print(
            "Set CRAFT_PROJECT_ID first.\n"
            "  CRAFT console → Settings → Project → ID\n"
            "  Then: put CRAFT_PROJECT_ID=<uuid> in .env (and as a Windows user env var for Cursor)."
        )
        return 1

    print(f"Project ID: {project_id}")
    print(f"MCP URL:    {MCP_URL}")
    print(f"Auth:       {AUTH_SERVER}")
    print(f"Client:     {CLIENT_ID}")

    tokens = oauth_pkce()
    access = tokens["access_token"]
    refresh = tokens.get("refresh_token", "")
    expires = tokens.get("expires_in")
    print(f"Got access_token (expires_in={expires}s, len={len(access)})")

    updates = {
        "CRAFT_PROJECT_ID": project_id,
        "CRAFT_ACCESS_TOKEN": access,
        "CRAFT_MCP_URL": MCP_URL,
    }
    if refresh:
        updates["CRAFT_REFRESH_TOKEN"] = refresh

    try:
        connections = list_data_connections(access, project_id)
        print(f"Found {len(connections)} data connection(s)")
        out = ROOT / "docs" / "data_connections.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(connections, indent=2, default=str), encoding="utf-8")
        print(f"Wrote {out}")

        resource_uri, db_id = pick_crypto_resource(connections)
        if resource_uri:
            updates["CRAFT_RESOURCE_URI"] = resource_uri
            print(f"CRAFT_RESOURCE_URI = {resource_uri}")
        else:
            print(
                "No CRYPTO connection auto-detected. Open docs/data_connections.json "
                "and copy the resource_uri (format: data:{org_id}:{project_id}:{name})."
            )
        if db_id:
            updates["CRAFT_DATABASE_UUID"] = db_id
            print(f"CRAFT_DATABASE_UUID = {db_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: assets list failed: {exc}")
        print("Token is still valid — you can set CRAFT_RESOURCE_URI manually from the CRAFT UI.")

    try:
        result = mcp_search_schema(access, project_id, "CRYPTO")
        preview = json.dumps(result, default=str)[:1500]
        print("search_schema preview:", preview)
        (ROOT / "docs" / "search_schema_crypto.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: MCP search_schema failed: {exc}")
        print(
            "If this is a project-scoping error with a valid token, Cursor's header-drop "
            "bug may apply — this script sends X-Project-ID explicitly so retry here."
        )

    upsert_env(updates)
    print("\nDone. Next:")
    print("  cd backend && .\\.venv\\Scripts\\python.exe ..\\scripts\\schema_recon.py")
    print("  Restart uvicorn so it reloads .env")
    print("\nNote: access tokens expire (~5 min for interactive). Re-run this script or use refresh.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        raise SystemExit(130)
