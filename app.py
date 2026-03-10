"""FinData MCP — HTTP API server with x402 micropayments.

All tool endpoints require x402 payment at $0.01 USDC per call.
No API keys, no subscription tiers — just pay-per-call.

Run: uvicorn app:app --host 0.0.0.0 --port 8080
"""

import os
import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from metering import init_metering_db, log_call
from cache import TTLCache
from tools.stock_quote import get_stock_quote
from tools.company_fundamentals import get_company_fundamentals
from tools.economic_indicator import get_economic_indicator
from tools.sec_filing import get_sec_filing
from tools.crypto_price import get_crypto_price

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("findata-mcp")

# ── x402 configuration ──
X402_WALLET = os.environ.get(
    "X402_WALLET_ADDRESS", "0x0000000000000000000000000000000000000000"
)
X402_NETWORK = os.environ.get("X402_NETWORK", "eip155:84532")  # Base Sepolia testnet
X402_FACILITATOR = os.environ.get(
    "X402_FACILITATOR_URL", "https://x402.org/facilitator"
)
X402_PRICE = "$0.01"
X402_VERIFY = os.environ.get("X402_VERIFY", "false").lower() == "true"

# Routes that require payment
PAID_PREFIXES = ("/api/v1/stock_quote", "/api/v1/company_fundamentals",
                 "/api/v1/economic_indicator", "/api/v1/sec_filing",
                 "/api/v1/crypto_price")

# ── Caches ──
stock_cache = TTLCache(ttl_seconds=60)
fundamentals_cache = TTLCache(ttl_seconds=3600)
economic_cache = TTLCache(ttl_seconds=21600)
sec_cache = TTLCache(ttl_seconds=86400)
crypto_cache = TTLCache(ttl_seconds=60)

# ── App ──

@asynccontextmanager
async def lifespan(application: FastAPI):
    init_metering_db()
    logger.info("FinData MCP started — x402 network=%s, verify=%s", X402_NETWORK, X402_VERIFY)
    yield


app = FastAPI(
    title="FinData MCP",
    version="0.2.0",
    description="Financial data API with x402 micropayments. $0.01 per call.",
    lifespan=lifespan,
)


# ── Middleware: x402 auth + metering ──

def _extract_tool_name(path: str) -> str:
    """Extract tool name from API path like /api/v1/stock_quote."""
    parts = path.rstrip("/").split("/")
    return parts[-1] if parts else "unknown"


def _is_paid_route(path: str) -> bool:
    return any(path.startswith(p) for p in PAID_PREFIXES)


def _build_402_response(path: str) -> JSONResponse:
    """Build HTTP 402 Payment Required response with x402 payment instructions."""
    return JSONResponse(
        status_code=402,
        content={
            "error": "Payment Required",
            "message": "This endpoint requires payment via x402 protocol ($0.01 per call).",
            "x402": {
                "version": "2",
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": X402_NETWORK,
                        "pay_to": X402_WALLET,
                        "price": X402_PRICE,
                        "description": f"FinData API: {_extract_tool_name(path)}",
                        "mime_type": "application/json",
                    }
                ],
                "facilitator": X402_FACILITATOR,
            },
        },
        headers={"X-Payment-Required": "x402"},
    )


@app.middleware("http")
async def auth_and_metering(request: Request, call_next):
    """x402 payment middleware. Meters all calls."""
    path = request.url.path
    start = time.monotonic()
    client_ip = request.client.host if request.client else None

    # Free routes — no auth required
    if not _is_paid_route(path):
        return await call_next(request)

    tool_name = _extract_tool_name(path)

    # Check x402 payment
    if request.headers.get("X-PAYMENT"):
        payment_method = "x402"
        if X402_VERIFY:
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{X402_FACILITATOR}/verify",
                        json={
                            "payment": request.headers["X-PAYMENT"],
                            "payTo": X402_WALLET,
                            "network": X402_NETWORK,
                        },
                    )
                    if resp.status_code != 200:
                        log_call(tool_name, "x402:failed", status_code=402, client_ip=client_ip)
                        return JSONResponse(
                            status_code=402,
                            content={"error": "Payment verification failed"},
                        )
            except Exception as e:
                logger.error("x402 verification error: %s", e)
                log_call(tool_name, "x402:error", status_code=500, client_ip=client_ip)
                return JSONResponse(
                    status_code=500,
                    content={"error": "Payment verification service unavailable"},
                )
    else:
        # No payment — return 402
        log_call(tool_name, "none", status_code=402, client_ip=client_ip)
        return _build_402_response(path)

    # Authorized — call endpoint
    response = await call_next(request)

    elapsed_ms = (time.monotonic() - start) * 1000
    log_call(
        tool_name=tool_name,
        payment_method=payment_method,
        response_time_ms=elapsed_ms,
        status_code=response.status_code,
        client_ip=client_ip,
    )
    return response


# ── Free endpoints ──

@app.get("/")
def root():
    return {
        "service": "FinData MCP",
        "version": "0.2.0",
        "tools": [
            "stock_quote", "company_fundamentals", "economic_indicator",
            "sec_filing", "crypto_price",
        ],
        "pricing": {
            "method": "x402 micropayments",
            "price": "$0.01 USDC per call",
            "signup_required": False,
        },
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/stats")
def api_stats():
    """Usage statistics (admin endpoint, no auth for now)."""
    from metering import get_usage_stats
    return get_usage_stats()


# ── Paid tool endpoints ──

@app.get("/api/v1/stock_quote")
def api_stock_quote(ticker: str = Query(..., description="Stock ticker (e.g. AAPL, TSLA)")):
    """Real-time stock price, volume, and change %."""
    ticker = ticker.upper().strip()
    cached = stock_cache.get(f"stock:{ticker}")
    if cached is not None:
        return cached
    result = get_stock_quote(ticker)
    stock_cache.set(f"stock:{ticker}", result)
    return result


@app.get("/api/v1/company_fundamentals")
def api_company_fundamentals(ticker: str = Query(..., description="Stock ticker (e.g. AAPL)")):
    """Revenue, P/E, market cap, sector, beta, dividends, and company description."""
    ticker = ticker.upper().strip()
    cached = fundamentals_cache.get(f"fundamentals:{ticker}")
    if cached is not None:
        return cached
    result = get_company_fundamentals(ticker)
    fundamentals_cache.set(f"fundamentals:{ticker}", result)
    return result


@app.get("/api/v1/economic_indicator")
def api_economic_indicator(series_id: str = Query(..., description="FRED series ID (e.g. GDP, CPIAUCSL, UNRATE)")):
    """US macroeconomic data from the Federal Reserve FRED database."""
    series_id = series_id.upper().strip()
    cached = economic_cache.get(f"econ:{series_id}")
    if cached is not None:
        return cached
    result = get_economic_indicator(series_id)
    economic_cache.set(f"econ:{series_id}", result)
    return result


@app.get("/api/v1/sec_filing")
def api_sec_filing(
    ticker_or_cik: str = Query(..., description="Ticker (AAPL) or CIK (320193)"),
    form_type: str = Query("10-K", description="Form type (10-K, 10-Q, 8-K, DEF 14A, S-1)"),
):
    """Full text of SEC filings from EDGAR."""
    ticker_or_cik = ticker_or_cik.strip().upper()
    form_type = form_type.strip().upper()
    cache_key = f"sec:{ticker_or_cik}:{form_type}"
    cached = sec_cache.get(cache_key)
    if cached is not None:
        return cached
    result = get_sec_filing(ticker_or_cik, form_type)
    sec_cache.set(cache_key, result)
    return result


@app.get("/api/v1/crypto_price")
def api_crypto_price(coin_id: str = Query(..., description="CoinGecko ID (e.g. bitcoin, ethereum, solana)")):
    """Cryptocurrency price, market cap, volume, and 7-day sparkline."""
    coin_id = coin_id.strip().lower()
    cached = crypto_cache.get(f"crypto:{coin_id}")
    if cached is not None:
        return cached
    result = get_crypto_price(coin_id)
    crypto_cache.set(f"crypto:{coin_id}", result)
    return result
