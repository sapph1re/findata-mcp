# FinData MCP — Registry Submission Guide

**Status**: READY TO SUBMIT — waiting on 3 human actions only.
**Updated**: 2026-03-11 (T31 Signal — Railway live, E2E 16/16 PASS, PyPI whl built)

---

## Prerequisites Status

- [x] Task 28 complete — MCP server built, all 5 tools working
- [x] Task 29 complete — x402 v2 micropayments on Base mainnet (49/49 tests pass)
- [x] Task 87/88 complete — E2E 16/16 PASS, registry_ready=1
- [x] **DONE: Cloud deployment — Railway live at https://findata-mcp-production-1cd3.up.railway.app**
- [x] **DONE: PyPI package built — dist/findata_mcp-0.1.0-py3-none-any.whl + .tar.gz (twine PASS)**
- [ ] **NEEDED: GitHub repo `sapph1re/findata-mcp` made **public** (Settings → Danger Zone → Change visibility)**
- [ ] **NEEDED: PyPI account + token to upload (`twine upload dist/*`)**
- [ ] **NEEDED: Human accounts on Smithery / Glama / mcp.so to submit**
- [ ] **OPTIONAL: Domain `findata-mcp.io` (can submit with Railway URL until domain is ready)**

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
     - GitHub repo URL: `https://github.com/sapph1re/findata-mcp`
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
   - Ensure `github.com/sapph1re/findata-mcp` is public

2. **Submit via Glama web form**:
   - URL: https://glama.ai/mcp/servers/submit (or check https://glama.ai/mcp)
   - Upload or link `server.json` from the repo
   - Alternative: Glama may auto-index from GitHub — check if `github.com/sapph1re/findata-mcp` appears automatically after making public

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

**GitHub**: https://github.com/sapph1re/findata-mcp

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
  - [findata-mcp](https://github.com/sapph1re/findata-mcp) - Real-time stocks, fundamentals, FRED economics, SEC filings, and crypto. x402 pay-per-call or free API key.
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

**Already done (by agents):**
- ~~Deploy to cloud~~ — Live at https://findata-mcp-production-1cd3.up.railway.app (Railway, mainnet, 16/16 E2E PASS)
- ~~Build PyPI package~~ — `dist/findata_mcp-0.1.0-py3-none-any.whl` ready, twine PASS

**Human actions needed:**
1. **Make GitHub repo public** — Go to https://github.com/sapph1re/findata-mcp → Settings → Danger Zone → Change visibility → Public
2. **Publish to PyPI** — `cd /opt/cortex/services/findata-mcp && twine upload dist/*` (needs PyPI account + token at pypi.org/manage/account/token/)
3. **Submit to Smithery** — https://smithery.ai/new, paste `https://github.com/sapph1re/findata-mcp`, `smithery.yaml` is in repo root
4. **Submit to Glama** — https://glama.ai/mcp/servers/submit, `server.json` is in repo root
5. **Submit to mcp.so** — Use copy from "mcp.so submission copy" section above
6. **Test install** — `smithery install findata-mcp` from clean terminal
7. **(Optional) Register domain** `findata-mcp.io` (Namecheap/Cloudflare, ~$12/yr) and point DNS A record to Railway

ETA after human actions complete: ~2-3 days (registry review times).

---

*Prepared by Signal (Task 31) — 2026-03-01*
*Updated 2026-03-01: Tasks 29 and 30 complete, blockers cleared, external setup required*
