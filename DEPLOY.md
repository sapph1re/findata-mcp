# FinData MCP — Deployment Guide

**Target**: findata-mcp.io (VPS or cloud VM)
**Stack**: Docker Compose + nginx + Let's Encrypt SSL

---

## Prerequisites

- Ubuntu 22.04+ VPS (2 vCPU, 2GB RAM minimum)
- Domain `findata-mcp.io` DNS A record → server IP
- Docker + Docker Compose installed
- A crypto wallet address to receive x402 payments

---

## Step 1: Server Setup

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# Install Docker Compose
sudo apt-get install -y docker-compose-plugin

# Install certbot for SSL
sudo apt-get install -y certbot
```

---

## Step 2: Clone and Configure

```bash
git clone https://github.com/cortex-labs/findata-mcp
cd findata-mcp

# Configure environment
cp .env.example .env
nano .env
# Fill in: X402_WALLET_ADDRESS, FRED_API_KEY (optional)
```

---

## Step 3: SSL Certificate

```bash
# Stop any existing web server on port 80
sudo systemctl stop nginx 2>/dev/null || true

# Issue certificate
sudo certbot certonly --standalone \
  -d findata-mcp.io \
  -d www.findata-mcp.io \
  --email hello@findata-mcp.io \
  --agree-tos --non-interactive
```

---

## Step 4: Build and Launch

```bash
# Build image
docker compose build

# Start services (detached)
docker compose up -d

# Verify health
curl https://findata-mcp.io/health
# Expected: {"status": "ok", "version": "0.1.0", "tools": 5}
```

---

## Step 5: Smoke Test

```bash
# Test with free API key (no payment required)
curl -H "X-API-Key: fd_test_demo" \
  https://findata-mcp.io/api/v1/stock_quote?ticker=AAPL

# Register a test API key
curl -X POST https://findata-mcp.io/api/v1/keys/register \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "tier": "free"}'
```

---

## Step 6: PyPI Publish (for uvx support)

```bash
pip install build twine

# Build distribution
python -m build

# Upload to PyPI (requires PyPI account + API token)
twine upload dist/*

# Verify install works
uvx findata-mcp --version
```

---

## Step 7: GitHub Repository

```bash
# Create GitHub repo at github.com/cortex-labs/findata-mcp
# Then push:
git init
git add .
git commit -m "Initial release v0.1.0"
git remote add origin https://github.com/cortex-labs/findata-mcp.git
git push -u origin main
```

After pushing, Signal will submit to registries (Task 31 completion).

---

## Monitoring

```bash
# View logs
docker compose logs -f findata-mcp

# Check usage stats
docker compose exec findata-mcp \
  sqlite3 /data/findata.db "SELECT tier, COUNT(*) FROM api_keys GROUP BY tier;"
```

---

## Rollback

```bash
# Roll back to previous image
docker compose down
docker pull cortexlabs/findata-mcp:previous
docker compose up -d
```

---

## Acceptance Criteria (Task 30)

- [ ] `curl https://findata-mcp.io/health` returns HTTP 200
- [ ] `/api/v1/stock_quote?ticker=AAPL` returns price data
- [ ] x402 payment flow tested (at least on testnet)
- [ ] API key registration working
- [ ] GitHub repo public at github.com/cortex-labs/findata-mcp
- [ ] PyPI package published (`pip install findata-mcp` works)
- [ ] Domain findata-mcp.io resolving with valid SSL

Signal is standing by to submit to Smithery, Glama, and mcp.so immediately after these boxes are checked.
