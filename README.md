# FinData MCP

The first comprehensive financial data MCP server. Five tools covering real-time stocks, company fundamentals, US economic indicators (FRED), SEC filings, and cryptocurrency — all in one server.

Pay per call via x402 micropayments ($0.01/call) or register a free API key (1,000 calls/day). **No signup required to start.**

---

## Tools

| Tool | Description | Cache |
|------|-------------|-------|
| `stock_quote(ticker)` | Real-time (15-min delayed) price, volume, and change % | 1 min |
| `company_fundamentals(ticker)` | Revenue, P/E, market cap, sector, beta, dividend yield | 1 hr |
| `economic_indicator(series_id)` | 800,000+ FRED series: GDP, CPI, fed funds rate, yield curves | 6 hr |
| `sec_filing(ticker_or_cik, form_type)` | Full text of 10-K, 10-Q, 8-K from SEC EDGAR | 24 hr |
| `crypto_price(coin_id)` | Price, market cap, 24h volume, 7-day sparkline via CoinGecko | 1 min |

---

## Installation

### Claude Desktop (Smithery)

```bash
smithery install findata-mcp
```

### uvx (any MCP client)

```bash
uvx findata-mcp
```

### pip

```bash
pip install findata-mcp
findata-mcp
```

### Docker

```bash
docker run -p 8080:8080 \
  -e FINDATA_API_KEY=fd_live_your_key \
  cortexlabs/findata-mcp
```

---

## Configuration

All environment variables are optional. The server works out of the box via x402 micropayments.

| Variable | Description | Default |
|----------|-------------|---------|
| `FINDATA_API_KEY` | API key for rate-limited access | — |
| `FRED_API_KEY` | FRED API key for higher rate limits | — |
| `X402_WALLET_ADDRESS` | Wallet address to receive x402 payments | placeholder |
| `X402_NETWORK` | Payment network (`eip155:84532` = Base Sepolia) | Base Sepolia |
| `X402_VERIFY` | Verify x402 payments on-chain (`true`/`false`) | `false` |
| `FINDATA_DB_PATH` | Path for API key SQLite database | `./findata.db` |

---

## Pricing

| Tier | Price | Limit |
|------|-------|-------|
| x402 pay-per-call | $0.01 / call | Unlimited |
| Free API key | $0 | 1,000 calls/day |
| Pro API key | $9/month | 10,000 calls/day |

Register at [findata-mcp.io/keys](https://findata-mcp.io/keys).

---

## Usage Examples

### Stock quote

```python
# MCP tool call
stock_quote(ticker="AAPL")

# Returns:
{
  "ticker": "AAPL",
  "price": 213.49,
  "change": 1.23,
  "change_pct": 0.58,
  "volume": 54321000,
  "market_cap": 3280000000000,
  "currency": "USD",
  "timestamp": "2026-03-01T15:30:00Z"
}
```

### Economic indicator (FRED)

```python
economic_indicator(series_id="FEDFUNDS")

# Returns:
{
  "series_id": "FEDFUNDS",
  "title": "Federal Funds Effective Rate",
  "units": "Percent",
  "frequency": "Monthly",
  "latest_value": 4.33,
  "latest_date": "2026-02-01",
  "observations": [...]
}
```

### SEC filing

```python
sec_filing(ticker_or_cik="AAPL", form_type="10-K")

# Returns:
{
  "ticker": "AAPL",
  "cik": "320193",
  "form_type": "10-K",
  "filed_at": "2025-10-31",
  "period": "2025-09-27",
  "filing_url": "https://www.sec.gov/...",
  "text_excerpt": "..."
}
```

---

## Architecture

FinData MCP has two components: a **thin client** (what you install) and a **hosted backend** (what runs on Railway).

### Thin Client (`findata_mcp/`) — shipped via PyPI

The `pip install` / `uvx` package is a lightweight MCP stdio server that proxies requests to the hosted backend. It handles x402 micropayment signing automatically. No API keys, no local data providers needed.

```
findata_mcp/
├── __init__.py        # Entry point (findata-mcp CLI)
├── server.py          # FastMCP thin server (5 tool stubs)
└── client.py          # HTTP client with x402 auto-payment
```

**Requires:** `EVM_PRIVATE_KEY` env var — a wallet funded with USDC on Base mainnet ($0.01/call).

### Hosted Backend (`backend/`) — deployed on Railway

The full implementation with data providers (Yahoo Finance, FRED, SEC EDGAR, CoinGecko), caching, metering, and x402 payment verification. Not included in the PyPI package.

```
backend/
├── app.py             # FastAPI HTTP server (x402 payments + metering)
├── cache.py           # In-memory TTL cache
├── metering.py        # Call logging + usage tracking
├── server.py          # Legacy full local MCP server (not used in production)
└── tools/
    ├── stock_quote.py
    ├── company_fundamentals.py
    ├── economic_indicator.py
    ├── sec_filing.py
    └── crypto_price.py
```

**Live at:** `https://findata-mcp-production-1cd3.up.railway.app`

---

## Development

```bash
git clone https://github.com/sapph1re/findata-mcp
cd findata-mcp

# Install thin client in dev mode
pip install -e .

# Run thin client (connects to hosted backend)
findata-mcp

# Run backend locally
pip install -r requirements.txt
cd backend && uvicorn app:app --host 0.0.0.0 --port 8080

# Run tests
python -m pytest test_thin_client.py -v
```

---

## License

MIT — see [LICENSE](LICENSE)

Built by [Cortex Labs](https://findata-mcp.io)
