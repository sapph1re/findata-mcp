# FinData MCP — Registry Submission Guide

**Status**: Artifacts ready. Submit after Task 30 (deployment) completes.
**Blocker**: Needs live URL (findata-mcp.io) before submission.

---

## Prerequisites (all must be true before submitting)

- [ ] Task 28 complete — MCP server built, all 5 tools working
- [ ] Task 29 complete — x402 payments + API key auth working
- [ ] Task 30 complete — Deployed to production, health check passing
- [ ] GitHub repo public at `github.com/cortex-labs/findata-mcp`
- [ ] Domain `findata-mcp.io` resolving to production server
- [ ] PyPI package published as `findata-mcp` (for `pip install`/`uvx`)

---

## 1. Smithery (PRIORITY — do this first)

**Why first**: Smithery has the `smithery install findata-mcp` CLI command which is the primary discovery vector for Claude Desktop users. 322K monthly visits.

**Estimated time**: 30 minutes + 1-3 day review

### Steps

1. **Publish to PyPI** (required for `uvx findata-mcp` to work):
   ```bash
   cd /opt/cortex/services/findata-mcp
   python -m build
   twine upload dist/*
   ```

2. **Push `smithery.yaml` to repo root**:
   ```bash
   # smithery.yaml is already prepared at /opt/cortex/services/findata-mcp/smithery.yaml
   # Copy to your GitHub repo root before pushing
   ```

3. **Submit via Smithery web form**:
   - URL: https://smithery.ai/new
   - Required fields:
     - GitHub repo URL: `https://github.com/cortex-labs/findata-mcp`
     - Smithery will auto-detect `smithery.yaml` from the repo root
   - Alternative: Submit a PR to `smithery-ai/registry` GitHub repo

4. **Verify after approval**:
   ```bash
   smithery install findata-mcp
   ```
   Then test in Claude Desktop.

### Smithery-specific copy (use in submission form)

**Short description** (140 chars):
> Real-time stocks, fundamentals, FRED economics, SEC filings & crypto in one MCP. Pay-per-call via x402 or free API key. No signup required.

**Category**: Finance

---

## 2. Glama (18,000+ servers — largest directory)

**Why**: Largest MCP directory, finance category has only 74 servers — we stand out.

**Estimated time**: 15 minutes + 24-48hr review

### Steps

1. **GitHub namespace verification**:
   - Glama verifies you own the GitHub repo
   - Ensure `github.com/cortex-labs/findata-mcp` is public

2. **Submit via Glama web form**:
   - URL: https://glama.ai/mcp/servers/submit (or check https://glama.ai/mcp)
   - Upload or link `server.json` from the repo
   - Alternative: Glama may auto-index from GitHub — check if `github.com/cortex-labs/findata-mcp` appears automatically after making public

3. **Verify**:
   - Search `https://glama.ai/mcp/servers` for "findata"
   - Should appear under Finance category

### Glama-specific copy

**Short description**:
> First comprehensive financial data MCP — stocks, fundamentals, FRED economics, SEC filings, crypto. x402 pay-per-call or free API key.

**Category**: Finance > Market Data

---

## 3. mcp.so (most granular listing, 17,977 servers)

**Why**: High SEO value, detailed tool listings, developer community.

**Estimated time**: 20 minutes submission + 24-48hr review

### Steps

1. **Submit via mcp.so listing form**:
   - URL: https://mcp.so/submit (check current URL on site)

2. **Fill in the form** with the content below

3. **Verify**:
   - Search https://mcp.so for "findata"
   - Check Finance category

### mcp.so submission copy

**Server Name**: FinData MCP

**Tagline**:
> The first comprehensive financial data MCP — 5 tools, zero-friction payments

**Full Description**:
> FinData MCP fills a real gap: finance is one of the most important use cases for AI agents, but the MCP ecosystem has barely any financial data servers. We built the tool we wanted to exist.
>
> **5 tools in one server:**
> - `stock_quote(ticker)` — Real-time delayed price, volume, change % for any NYSE/NASDAQ ticker
> - `company_fundamentals(ticker)` — Revenue, P/E, market cap, sector, beta, dividend yield
> - `economic_indicator(series_id)` — 800,000+ FRED series: GDP, CPI, fed funds rate, yield curves
> - `sec_filing(ticker, form_type)` — Full text of 10-K, 10-Q, 8-K from SEC EDGAR
> - `crypto_price(coin_id)` — Price, market cap, volume, 7-day sparkline via CoinGecko
>
> **Payment options:**
> - x402 micropayments: $0.01/call, works automatically with any x402-compatible agent
> - Free API key: 1,000 calls/day (register at findata-mcp.io/keys)
> - Pro: 10,000 calls/day at $9/month
>
> All tools return structured JSON. Intelligent TTL caching (1min stocks, 1hr fundamentals, 6hr economics, 24hr SEC filings). Graceful rate limit handling.

**Install command**: `uvx findata-mcp` or `smithery install findata-mcp`

**GitHub**: https://github.com/cortex-labs/findata-mcp

**Homepage**: https://findata-mcp.io

**Category**: Finance

**Tags**: stocks, financial-data, economics, SEC, crypto, x402, micropayments

**Pricing**: Freemium / Pay-per-use

---

## 4. Bonus Registries (submit after the big 3)

### MCPize.com
- URL: https://mcpize.com/submit
- **Note**: MCPize offers 85% revenue share — could be interesting for additional discovery
- Category: Finance

### AWS Marketplace (MCP Beta)
- URL: https://aws.amazon.com/marketplace/
- 97% revenue share, requires AWS account verification
- Longer process, do this in week 2

### Awesome MCP Servers (GitHub)
- PR to: https://github.com/punkpeye/awesome-mcp-servers
- Add under `Finance` section:
  ```markdown
  - [findata-mcp](https://github.com/cortex-labs/findata-mcp) - Real-time stocks, fundamentals, FRED economics, SEC filings, and crypto. x402 pay-per-call or free API key.
  ```

---

## Post-Submission Checklist

- [ ] Smithery: `smithery install findata-mcp` works in terminal
- [ ] Glama: Appears in Finance category search
- [ ] mcp.so: Listing live with all 5 tools described
- [ ] All 3 listings link to correct GitHub + homepage
- [ ] Test install from each registry independently
- [ ] Monitor for first x402 payment (confirms end-to-end works)

---

## Files in this directory

| File | Purpose |
|------|---------|
| `smithery.yaml` | Smithery registry manifest — place in GitHub repo root |
| `server.json` | Glama registry spec — place in GitHub repo root |
| `REGISTRY_SUBMISSIONS.md` | This guide |

---

*Prepared by Signal (Task 31) — 2026-03-01*
*Submit when Task 30 (deployment) is complete*
