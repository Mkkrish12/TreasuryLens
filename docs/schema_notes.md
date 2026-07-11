# CRYPTO schema recon (live)

**Status: complete** via Craft MCP (`user-Craft`), project `70a8f494-bf79-477d-8999-23d5a7d6e331`.

## IDs for `.env`

| Key | Value |
|---|---|
| `CRAFT_CONNECTION_SLUG` | `crypto-70a8f494` |
| `CRAFT_DATABASE_UUID` | `59930fbf-9f35-4e39-b41d-c8a71873b1bf` |
| `CRAFT_DATABASE_FQN` | `crypto-70a8f494.CRYPTO` |
| `CRAFT_RESOURCE_URI` | `data:b732e1b7-49b1-404c-b02f-2d131dc756b9:70a8f494-bf79-477d-8999-23d5a7d6e331:crypto-70a8f494` |

Craft tools take **`connection` = slug** (`crypto-70a8f494`), not the project UUID.

## Decision gate

| Question | Answer |
|---|---|
| Balance table? | **Yes** — `CRYPTO_ETHEREUM_CLASSIC.BALANCES` (`address`, `eth_balance`) |
| USD/price column? | **No** — report native token units |
| Concentration approach | Prefer `BALANCES` where present; else tx/outputs with `LIMIT` |

## 7 chain schemas

1. `CRYPTO_BAND`
2. `CRYPTO_BITCOIN`
3. `CRYPTO_BITCOIN_CASH`
4. `CRYPTO_DASH`
5. `CRYPTO_ETHEREUM`
6. `CRYPTO_ETHEREUM_CLASSIC`
7. `CRYPTO_ZILLIQA`

## Note on Cursor MCP

Global `~/.cursor/mcp.json` must use the real project UUID in `X-Project-ID`. A placeholder (`<your project UUID>`) causes permission errors even when OAuth succeeds.
