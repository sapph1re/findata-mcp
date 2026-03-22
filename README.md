# FinData MCP

<!-- mcp-name: io.github.sapph1re/findata-mcp -->

Financial data for AI agents. Five tools — stocks, fundamentals, economics, SEC filings, crypto — accessible from any MCP client. Pay $0.01 per call, no signup.

## Quick Start

**Install:**

```bash
pip install findata-mcp
```

**Set your wallet key** (any EVM wallet with USDC on Base):

```bash
export EVM_PRIVATE_KEY=your_private_key_here
```

**Add to Claude Desktop** — edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "findata-mcp": {
      "command": "findata-mcp",
      "env": {
        "EVM_PRIVATE_KEY": "your_private_key_here"
      }
    }
  }
}
```

**Add to Cursor** — edit `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "findata-mcp": {
      "command": "findata-mcp",
      "env": {
        "EVM_PRIVATE_KEY": "your_private_key_here"
      }
    }
  }
}
```

Restart your client. You now have five financial data tools available.

---

## Tools

| Tool | What it returns | Cache |
|------|----------------|-------|
| `stock_quote(ticker)` | Price, volume, change %, market cap | 1 min |
| `company_fundamentals(ticker)` | Revenue, P/E, sector, beta, dividend yield, description | 1 hr |
| `economic_indicator(series_id)` | 800,000+ FRED series (GDP, CPI, rates, yield curves) | 6 hr |
| `sec_filing(ticker_or_cik, form_type)` | Full text of 10-K, 10-Q, 8-K from SEC EDGAR | 24 hr |
| `crypto_price(coin_id)` | Price, market cap, 24h volume, 7-day sparkline | 1 min |

---

## Examples

### Get a stock quote

```
stock_quote(ticker="NVDA")
```

```json
{
  "ticker": "NVDA",
  "price": 878.35,
  "change": 12.40,
  "change_pct": 1.43,
  "volume": 41200000,
  "market_cap": 2150000000000,
  "currency": "USD"
}
```

### Look up company fundamentals

```
company_fundamentals(ticker="AAPL")
```

```json
{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "sector": "Technology",
  "market_cap": 3280000000000,
  "pe_ratio": 33.2,
  "revenue": 383285000000,
  "beta": 1.24,
  "dividend_yield": 0.0044
}
```

### Check an economic indicator

```
economic_indicator(series_id="FEDFUNDS")
```

```json
{
  "series_id": "FEDFUNDS",
  "title": "Federal Funds Effective Rate",
  "units": "Percent",
  "frequency": "Monthly",
  "latest_value": 4.33,
  "latest_date": "2026-02-01"
}
```

Common FRED series: `GDP`, `CPIAUCSL` (inflation), `UNRATE` (unemployment), `DGS10` (10-year Treasury), `FEDFUNDS`.

---

## Pricing

**$0.01 per call.** No signup, no API keys, no monthly fees.

Payment happens automatically via [x402](https://www.x402.org/) — an open micropayment protocol. Your MCP client signs a USDC transfer on Base mainnet for each call. You need:

1. An EVM wallet private key (set as `EVM_PRIVATE_KEY`)
2. A small USDC balance on Base mainnet (~$1 covers 100 calls)

That's it. No accounts, no rate limits, no billing pages.

---

## How It Works

The `pip install` package is a thin MCP stdio server. It proxies your tool calls to a hosted backend, automatically handling x402 payment signing. Data comes from Yahoo Finance, FRED, SEC EDGAR, and CoinGecko.

```
Your AI agent  →  findata-mcp (local stdio)  →  Backend (Railway)  →  Data providers
                  signs x402 payment              verifies payment
```

---

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EVM_PRIVATE_KEY` | Yes | — | Wallet private key with USDC on Base |
| `FINDATA_BACKEND_URL` | No | Production URL | Override for self-hosted backend |

---

## Alternative Install Methods

**uvx** (no install needed):

```bash
uvx findata-mcp
```

---

## Distribution Status

- PyPI: live
- Glama: submission in progress
- Smithery: not supported yet (current package uses stdio transport; Smithery support will require an HTTP MCP endpoint or a compatible submission path)

## License

MIT
