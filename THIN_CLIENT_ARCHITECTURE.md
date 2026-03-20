# FinData MCP — Thin Client Architecture Plan

## Overview

Redesign the PyPI package (`findata-mcp`) from a full local server shipping all tool logic to a **thin MCP adapter** that proxies requests to the hosted Railway backend with automatic x402 payment.

**Current state**: `pip install findata-mcp` / `uvx findata-mcp` installs the full server (yfinance, fredapi, requests, SEC scraping, CoinGecko client, metering DB, caching) — ~15 heavy dependencies, runs everything locally for free.

**Target state**: PyPI ships a lightweight MCP stdio adapter (~3 dependencies) that forwards tool calls to `FINDATA_BACKEND_URL` via HTTP, auto-pays x402 on 402 responses using the caller's wallet key.

---

## File-by-File Separation Plan

### CLIENT (ships in PyPI package)

| File | Status | Description |
|------|--------|-------------|
| `findata_mcp/__init__.py` | **REWRITE** | Entry point. Starts thin MCP stdio server. |
| `findata_mcp/server.py` | **NEW** | FastMCP server with 5 tool stubs. Each tool calls backend HTTP, not local logic. |
| `findata_mcp/client.py` | **NEW** | HTTP client with x402 auto-payment. Wraps `requests` with `x402HTTPAdapter`. |
| `pyproject.toml` | **REWRITE** | Strip heavy deps. New deps: `fastmcp>=3.0.0`, `x402>=2.3.0`, `requests>=2.31.0`, `eth-account>=0.13.0`. Remove: yfinance, fredapi, fastapi, uvicorn, httpx. |

**NOT shipped in client:**
- `tools/` (all 5 modules) — execution logic stays on server
- `app.py` — FastAPI HTTP server with x402 middleware
- `cache.py` — server-side caching
- `metering.py` — server-side call logging + replay protection
- `findata.db` — metering database
- `Dockerfile`, `Procfile`, `railway.json`, `nginx.conf` — deployment infra
- `requirements.txt` — server-only deps

### SERVER (Railway backend only, NOT in PyPI)

| File | Status | Description |
|------|--------|-------------|
| `app.py` | **KEEP AS-IS** | FastAPI + x402 middleware. Already serves HTTP endpoints. No changes needed. |
| `tools/*.py` | **KEEP AS-IS** | All 5 tool modules stay server-side. |
| `cache.py` | **KEEP AS-IS** | Server-side TTL caching. |
| `metering.py` | **KEEP AS-IS** | Call logging + replay protection. |
| `Dockerfile` | **KEEP AS-IS** | Railway deployment. |
| `requirements.txt` | **KEEP AS-IS** | Server deps (yfinance, fredapi, fastapi, etc.). |

---

## New Client Architecture

### `findata_mcp/server.py` (thin MCP adapter)

```python
"""FinData MCP — Thin client that proxies to hosted backend with x402 auto-payment."""

import os
from typing import Any
from fastmcp import FastMCP
from findata_mcp.client import FinDataClient

mcp = FastMCP(
    name="findata-mcp",
    version="0.3.0",
    instructions="Financial data via hosted backend. 5 tools: stock_quote, company_fundamentals, economic_indicator, sec_filing, crypto_price. Requires EVM_PRIVATE_KEY for x402 payments ($0.01/call).",
)

_client = None

def _get_client() -> FinDataClient:
    global _client
    if _client is None:
        _client = FinDataClient(
            backend_url=os.environ.get("FINDATA_BACKEND_URL", "https://findata-mcp-production-1cd3.up.railway.app"),
            private_key=os.environ.get("EVM_PRIVATE_KEY", ""),
        )
    return _client

@mcp.tool()
def stock_quote(ticker: str) -> dict[str, Any]:
    """Real-time (15-min delayed) stock price, volume, and change % for any NYSE/NASDAQ/global ticker.

    Args:
        ticker: Stock ticker symbol (e.g. AAPL, TSLA, MSFT, NVDA)
    """
    return _get_client().call("stock_quote", ticker=ticker)

@mcp.tool()
def company_fundamentals(ticker: str) -> dict[str, Any]:
    """Full fundamental data: revenue, earnings, P/E ratio, market cap, sector, beta, dividend yield, and company description.

    Args:
        ticker: Stock ticker symbol (e.g. AAPL, TSLA, MSFT)
    """
    return _get_client().call("company_fundamentals", ticker=ticker)

@mcp.tool()
def economic_indicator(series_id: str) -> dict[str, Any]:
    """US macroeconomic data from the Federal Reserve FRED database: GDP, CPI, unemployment, interest rates, yield curves, and 800,000+ economic series.

    Args:
        series_id: FRED series ID (e.g. GDP, CPIAUCSL, UNRATE, FEDFUNDS, DGS10)
    """
    return _get_client().call("economic_indicator", series_id=series_id)

@mcp.tool()
def sec_filing(ticker_or_cik: str, form_type: str = "10-K") -> dict[str, Any]:
    """Full text of SEC filings from EDGAR: 10-K annual reports, 10-Q quarterlies, 8-K material events, proxy statements.

    Args:
        ticker_or_cik: Stock ticker (AAPL) or SEC CIK number (320193)
        form_type: SEC form type (10-K, 10-Q, 8-K, DEF 14A, S-1)
    """
    return _get_client().call("sec_filing", ticker_or_cik=ticker_or_cik, form_type=form_type)

@mcp.tool()
def crypto_price(coin_id: str) -> dict[str, Any]:
    """Cryptocurrency price, market cap, 24h volume, and 7-day sparkline via CoinGecko.

    Args:
        coin_id: CoinGecko coin ID in lowercase-hyphenated format (e.g. bitcoin, ethereum, solana, chainlink)
    """
    return _get_client().call("crypto_price", coin_id=coin_id)
```

### `findata_mcp/client.py` (HTTP + x402 payment client)

```python
"""HTTP client with automatic x402 payment for FinData backend."""

import requests
from typing import Any

class FinDataClient:
    """Thin HTTP client that calls the FinData backend and auto-pays x402."""

    def __init__(self, backend_url: str, private_key: str = ""):
        self.backend_url = backend_url.rstrip("/")
        self._session = self._build_session(private_key)

    def _build_session(self, private_key: str) -> requests.Session:
        """Build a requests.Session with x402 auto-payment if key is provided."""
        if not private_key:
            # No wallet key — requests will get 402 errors.
            # Still useful for free endpoints (health, root).
            return requests.Session()

        from eth_account import Account
        from x402 import x402ClientSync
        from x402.client_base import x402ClientConfig, SchemeRegistration
        from x402.mechanisms.evm.exact.client import ExactEvmScheme
        from x402.http.clients.requests import x402_requests

        account = Account.from_key(private_key)
        config = x402ClientConfig(
            schemes=[
                SchemeRegistration(
                    network="eip155:8453",  # Base mainnet
                    client=ExactEvmScheme(signer=account),
                ),
            ],
        )
        client = x402ClientSync.from_config(config)
        return x402_requests(client)

    def call(self, tool_name: str, **params: Any) -> dict[str, Any]:
        """Call a backend tool endpoint with auto x402 payment."""
        resp = self._session.get(
            f"{self.backend_url}/api/v1/{tool_name}",
            params=params,
            timeout=30,
        )
        if resp.status_code == 402:
            return {
                "error": "Payment required. Set EVM_PRIVATE_KEY env var with a wallet funded with USDC on Base mainnet.",
                "tool": tool_name,
            }
        resp.raise_for_status()
        return resp.json()
```

### `findata_mcp/__init__.py` (entry point)

```python
"""FinData MCP — Financial data for AI agents via hosted backend with x402 payments."""

def main() -> None:
    """Start the FinData MCP thin client (stdio transport)."""
    from findata_mcp.server import mcp
    mcp.run()
```

### `pyproject.toml` (client-only deps)

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "findata-mcp"
version = "0.3.0"
description = "Financial data MCP server — stocks, fundamentals, FRED economics, SEC filings, crypto via x402 micropayments"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Cortex Labs", email = "hello@findata-mcp.io" }]
keywords = ["mcp", "finance", "stocks", "financial-data", "x402", "micropayments"]
dependencies = [
  "fastmcp>=3.0.0",
  "requests>=2.31.0",
  "x402>=2.3.0",
  "eth-account>=0.13.0",
]

[project.scripts]
findata-mcp = "findata_mcp:main"

[tool.hatch.build.targets.wheel]
packages = ["findata_mcp"]
# NO force-include — only findata_mcp/ package ships
# tools/, app.py, cache.py, metering.py are NOT included

[tool.hatch.build.targets.sdist]
include = ["findata_mcp/", "README.md", "pyproject.toml"]
```

---

## x402 Payment Flow

```
┌────────────┐     stdio      ┌──────────────────┐    HTTP GET     ┌──────────────────┐
│ MCP Client │ ◄────────────► │ Thin MCP Adapter  │ ──────────────► │ Railway Backend  │
│ (Claude,   │   tool_call    │ (findata_mcp)     │                 │ (app.py)         │
│  Cursor,   │   + result     │                   │                 │                  │
│  etc.)     │                │ server.py         │  ◄── HTTP 402 ──│ x402 middleware   │
└────────────┘                │ client.py         │  PAYMENT-REQUIRED│                  │
                              │                   │                 │                  │
                              │ x402HTTPAdapter   │  ── auto-retry ─►│ Verify + settle  │
                              │ signs EIP-3009    │  + Payment-Sig  │ Return data      │
                              │ with wallet key   │                 │                  │
                              │                   │  ◄── HTTP 200 ──│ + PAYMENT-RESPONSE│
                              └──────────────────┘   JSON data      └──────────────────┘
```

### Step-by-step:

1. MCP client (Claude Desktop, Cursor, etc.) sends `stock_quote(ticker="AAPL")` via stdio
2. Thin adapter calls `GET {FINDATA_BACKEND_URL}/api/v1/stock_quote?ticker=AAPL`
3. Backend returns **HTTP 402** with `PAYMENT-REQUIRED` header (base64 JSON with x402 v2 payment requirements: $0.01 USDC on Base mainnet)
4. `x402HTTPAdapter` (from x402 SDK) intercepts the 402:
   - Parses `PAYMENT-REQUIRED` into `PaymentRequired` schema
   - Creates `ExactEvmScheme` payment: EIP-3009 `transferWithAuthorization` signed by `EVM_PRIVATE_KEY`
   - Retries the same request with `Payment-Signature` header
5. Backend verifies/settles the payment on-chain, returns **HTTP 200** with JSON data + `PAYMENT-RESPONSE` header
6. Thin adapter returns the JSON to MCP client

**Key x402 note from Civic**: x402 headers conflict with SSE streaming. Our backend uses JSON responses (not SSE), so this is not an issue. The thin client uses `requests.get()` (not streaming), which is correct.

---

## Environment Variables

### Client-side (user configures in MCP client settings)

| Env Var | Required | Default | Description |
|---------|----------|---------|-------------|
| `EVM_PRIVATE_KEY` | Yes (for paid tools) | — | Private key of wallet with USDC on Base mainnet |
| `FINDATA_BACKEND_URL` | No | `https://findata-mcp-production-1cd3.up.railway.app` | Backend URL (for self-hosting or dev) |

### Server-side (Railway, unchanged)

All existing env vars remain (`X402_WALLET_ADDRESS`, `FINDATA_X402_PRIVATE_KEY`, `BASE_MAINNET_RPC`, `FRED_API_KEY`, etc.)

---

## Repo Structure After Redesign

```
findata-mcp/
├── findata_mcp/              # PyPI PACKAGE (thin client)
│   ├── __init__.py           # Entry point → mcp.run()
│   ├── server.py             # FastMCP with 5 tool stubs → HTTP calls
│   └── client.py             # requests session + x402 auto-payment
├── server/                   # BACKEND (Railway only, not in PyPI)
│   ├── app.py                # FastAPI + x402 middleware (moved from root)
│   ├── cache.py              # TTL cache
│   ├── metering.py           # Call logging + replay protection
│   └── tools/                # Tool execution logic
│       ├── __init__.py
│       ├── stock_quote.py
│       ├── company_fundamentals.py
│       ├── economic_indicator.py
│       ├── sec_filing.py
│       └── crypto_price.py
├── pyproject.toml            # Client-only deps (fastmcp, x402, requests, eth-account)
├── Dockerfile                # Builds from server/ directory
├── requirements.txt          # Server deps (yfinance, fredapi, fastapi, etc.)
├── README.md
├── smithery.yaml
└── server.json
```

The `server/` directory is excluded from the wheel via `[tool.hatch.build.targets.wheel]` — only `findata_mcp/` ships to PyPI.

---

## Migration Checklist

### Phase 1: Restructure repo (T169)
- [ ] Move `app.py`, `cache.py`, `metering.py`, `tools/` into `server/` directory
- [ ] Update `Dockerfile` to build from `server/`
- [ ] Update Railway config (`Procfile`, `railway.json`) for new paths
- [ ] Verify backend still works after restructure

### Phase 2: Implement thin client (T168)
- [ ] Write `findata_mcp/client.py` — HTTP + x402 payment client
- [ ] Write `findata_mcp/server.py` — FastMCP tool stubs calling client
- [ ] Rewrite `findata_mcp/__init__.py` — new entry point
- [ ] Update `pyproject.toml` — strip server deps, add x402 + eth-account
- [ ] Remove `force-include` directives (no more bundling server code)

### Phase 3: Test (T170)
- [ ] E2E: `uvx findata-mcp` connects to Railway backend
- [ ] E2E: x402 payment flow works (402 → sign → retry → 200)
- [ ] E2E: All 5 tools return correct data
- [ ] Error: Missing `EVM_PRIVATE_KEY` returns clear error message
- [ ] Error: Invalid key returns clear error
- [ ] Error: Backend down returns clear error

### Phase 4: Publish (T171)
- [ ] Bump version to 0.3.0
- [ ] Publish to PyPI
- [ ] Verify `pip install findata-mcp` gets thin client
- [ ] Verify Railway backend unchanged and healthy
- [ ] Update registry submissions (Smithery, Glama) with new config

---

## Design Decisions

1. **Sync `requests` over async `httpx`**: FastMCP tool handlers are sync. Using `requests` + `x402HTTPAdapter` (sync) avoids async complexity. The x402 SDK's requests integration is battle-tested.

2. **No local caching in client**: Backend already caches (1min stocks, 1hr fundamentals, 6hr economics, 24hr SEC, 1min crypto). Adding client cache would stale data and complicate invalidation.

3. **Default backend URL hardcoded**: Users who just `pip install` get the production backend automatically. Self-hosters override via `FINDATA_BACKEND_URL`.

4. **`EVM_PRIVATE_KEY` not `FINDATA_WALLET_KEY`**: Standard name used across x402 ecosystem (Coinbase MCP, Civic MCP). Users with existing x402-funded wallets can reuse the same env var.

5. **No graceful fallback to local execution**: The whole point is that tool logic does NOT ship to clients. If backend is down, tools fail clearly rather than silently switching to local mode.

6. **Move server code to `server/` subdirectory**: Clean separation. Hatch wheel build only includes `findata_mcp/`. No risk of accidentally shipping server code.
