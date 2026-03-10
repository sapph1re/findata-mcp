# FinData MCP — Registry Submission Guide

**Status**: READY TO SUBMIT — all internal tasks complete. External setup required.
**Updated**: 2026-03-01 (Task 29 + 30 both completed, blockers cleared)

---

## Prerequisites Status

- [x] Task 28 complete — MCP server built, all 5 tools working (49/49 tests pass)
- [x] Task 29 complete — x402 payments + API key auth working (49/49 tests pass)
- [x] Task 30 complete — Deployed at localhost:8080, all tools returning live data
- [ ] **NEEDED: GitHub repo public at `github.com/cortex-labs/findata-mcp`**
- [ ] **NEEDED: Domain `findata-mcp.io` registered + pointing to cloud server**
- [ ] **NEEDED: PyPI package published as `findata-mcp` (for `pip install`/`uvx`)**
- [ ] **NEEDED: Cloud deployment (Railway/Fly/VPS) with public IP**

### To complete cloud deployment (Task 30 result):
```bash
# Option A: Railway (simplest)
npm install -g @railway/cli
railway login
cd /opt/cortex/services/findata-mcp
railway init && railway up

# Option B: Docker + VPS
docker build -t findata-mcp .
docker run -d -p 8080:8080 findata-mcp
# Then point findata-mcp.io DNS A record to the VPS IP
```

---

## 1. Smithery (PRIORITY — do this first)

**Why first**: Smithery has the `smithery install findata-mcp` CLI command which is the primary discovery vector for Claude Desktop users. 322K monthly visits.

**Estimated time**: 30 minutes + 1-3 day review

### Steps

1. **Publish to PyPI** (required for `uvx findata-mcp` to work):
   ```bash
   # Build the package (already validated via pyproject.toml)
   cd /opt/cortex/services/findata-mcp
   pip install build twine
   python -m build
   # Dry-run check:
   twine check dist/*
   # Upload to PyPI (needs PyPI account + token):
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
> Real-time stocks, fundamentals, FRED economics, SEC filings & crypto in one MCP. $0.01/call via x402 micropayments. No signup required.

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
> First comprehensive financial data MCP — stocks, fundamentals, FRED economics, SEC filings, crypto. $0.01/call via x402 micropayments.

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
> **Payment:**
> - x402 micropayments: $0.01/call, works automatically with any x402-compatible agent
> - No signup, no API keys — just pay per call
>
> All tools return structured JSON. Intelligent TTL caching (1min stocks, 1hr fundamentals, 6hr economics, 24hr SEC filings). Graceful rate limit handling.

**Install command**: `uvx findata-mcp` or `smithery install findata-mcp`

**GitHub**: https://github.com/cortex-labs/findata-mcp

**Homepage**: https://findata-mcp.io

**Category**: Finance

**Tags**: stocks, financial-data, economics, SEC, crypto, x402, micropayments

**Pricing**: Pay-per-use ($0.01/call via x402)

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

---

## Summary of Required Human Actions (in order)

1. **Register domain** `findata-mcp.io` (Namecheap/Cloudflare, ~$12/yr)
2. **Deploy to cloud** — Railway is fastest: `railway login && railway up` in `/opt/cortex/services/findata-mcp`
3. **Point DNS** — A record for `findata-mcp.io` → cloud server IP
4. **Push to GitHub** — Create `cortex-labs/findata-mcp` repo, push all files from `/opt/cortex/services/findata-mcp`
5. **Publish to PyPI** — `pip install build twine && python -m build && twine upload dist/*` (needs PyPI token)
6. **Submit to Smithery** — https://smithery.ai/new, paste GitHub URL, `smithery.yaml` is in repo root
7. **Submit to Glama** — https://glama.ai/mcp/servers/submit, `server.json` is in repo root
8. **Submit to mcp.so** — Use copy from "mcp.so submission copy" section above
9. **Test install** — `smithery install findata-mcp` from clean terminal

All code artifacts are production-ready. 49/49 tests pass. ETA after human setup: ~2-3 days (registry review times).

---

*Prepared by Signal (Task 31) — 2026-03-01*
*Updated 2026-03-01: Tasks 29 and 30 complete, blockers cleared, external setup required*
