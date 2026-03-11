"""FinData MCP — HTTP API server with x402 micropayments.

All tool endpoints require x402 payment at $0.01 USDC per call.
No API keys, no subscription tiers — just pay-per-call.

Run: uvicorn app:app --host 0.0.0.0 --port 8080
"""

import os
import time
import logging
import base64
import json as _json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.responses import Response

from metering import init_metering_db, log_call, is_signature_used, record_signature, purge_expired_signatures, try_claim_signature
from cache import TTLCache
from tools.stock_quote import get_stock_quote
from tools.company_fundamentals import get_company_fundamentals
from tools.economic_indicator import get_economic_indicator, resolve_series_id
from tools.sec_filing import get_sec_filing
from tools.crypto_price import get_crypto_price, resolve_coin_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("findata-mcp")

# ── x402 configuration ──
X402_WALLET = os.environ.get(
    "X402_WALLET_ADDRESS", "0x0000000000000000000000000000000000000000"
)
X402_NETWORK = os.environ.get("X402_NETWORK", "eip155:8453")  # Base mainnet
# Note: x402.org facilitator does not support Base mainnet "exact" scheme as of 2026-03.
# When enabling verification, use a CDP facilitator or self-hosted one.
X402_FACILITATOR = os.environ.get(
    "X402_FACILITATOR_URL", "https://x402.org/facilitator"
)
# USDC contract address (Base mainnet default)
X402_ASSET = os.environ.get(
    "X402_ASSET_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
)
X402_AMOUNT = os.environ.get("X402_AMOUNT", "10000")  # $0.01 USDC (6 decimals)
X402_VERIFY = os.environ.get("X402_VERIFY", "true").lower() == "true"
# EIP-712 domain params for USDC on Base mainnet
X402_TOKEN_NAME = os.environ.get("X402_TOKEN_NAME", "USD Coin")
X402_TOKEN_VERSION = os.environ.get("X402_TOKEN_VERSION", "2")

# Routes that require payment
PAID_PREFIXES = ("/api/v1/stock_quote", "/api/v1/company_fundamentals",
                 "/api/v1/economic_indicator", "/api/v1/sec_filing",
                 "/api/v1/crypto_price")

# In-memory replay protection — belt-and-suspenders alongside SQLite.
# Catches replays even if SQLite file doesn't persist (e.g. ephemeral Railway storage).
# Bounded to prevent unbounded growth; oldest entries evicted via dict ordering (Python 3.7+).
_USED_SIGS_MEM: dict[str, float] = {}  # sig_hash → timestamp
_USED_SIGS_MEM_MAX = 10000

# ── Caches ──
stock_cache = TTLCache(ttl_seconds=60)
fundamentals_cache = TTLCache(ttl_seconds=3600)
economic_cache = TTLCache(ttl_seconds=21600)
sec_cache = TTLCache(ttl_seconds=86400)
crypto_cache = TTLCache(ttl_seconds=60)

def _error_response(result: dict) -> JSONResponse | None:
    """If result contains an error, return a JSONResponse with proper status code."""
    if "error" not in result:
        return None
    err = result["error"].lower()
    if "not found" in err or "could not resolve" in err:
        return JSONResponse(status_code=404, content=result)
    if "rate limit" in err:
        return JSONResponse(status_code=429, content=result)
    if "not set" in err or "api_key" in err:
        return JSONResponse(status_code=503, content=result)
    return JSONResponse(status_code=502, content=result)


# ── App ──

@asynccontextmanager
async def lifespan(application: FastAPI):
    init_metering_db()
    purge_expired_signatures()
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


def _payment_required_header(path: str) -> str:
    """Return the base64-encoded PAYMENT-REQUIRED header value for a path."""
    from x402.schemas import PaymentRequired, PaymentRequirements, ResourceInfo
    payment_required = PaymentRequired(
        x402_version=2,
        accepts=[
            PaymentRequirements(
                scheme="exact",
                network=X402_NETWORK,
                asset=X402_ASSET,
                amount=X402_AMOUNT,
                pay_to=X402_WALLET,
                max_timeout_seconds=300,
                extra={"name": X402_TOKEN_NAME, "version": X402_TOKEN_VERSION},
            )
        ],
        resource=ResourceInfo(
            url=path,
            description=f"FinData API: {_extract_tool_name(path)}",
            mime_type="application/json",
        ),
        error="Payment required",
    )
    body = payment_required.model_dump(by_alias=True, exclude_none=True)
    return base64.b64encode(_json.dumps(body).encode()).decode()


def _build_402_response(path: str) -> JSONResponse:
    """Build HTTP 402 Payment Required response per x402 v2 spec."""
    from x402.schemas import PaymentRequired, PaymentRequirements, ResourceInfo
    payment_required = PaymentRequired(
        x402_version=2,
        accepts=[
            PaymentRequirements(
                scheme="exact",
                network=X402_NETWORK,
                asset=X402_ASSET,
                amount=X402_AMOUNT,
                pay_to=X402_WALLET,
                max_timeout_seconds=300,
                extra={"name": X402_TOKEN_NAME, "version": X402_TOKEN_VERSION},
            )
        ],
        resource=ResourceInfo(
            url=path,
            description=f"FinData API: {_extract_tool_name(path)}",
            mime_type="application/json",
        ),
        error="Payment required",
    )
    body = payment_required.model_dump(by_alias=True, exclude_none=True)
    encoded = base64.b64encode(_json.dumps(body).encode()).decode()
    return JSONResponse(
        status_code=402,
        content=body,
        headers={"PAYMENT-REQUIRED": encoded},
    )


def _verify_payment_locally(payment_header: str) -> dict:
    """Verify x402 EIP-3009 payment signature locally (no external facilitator).

    Validates:
    - Payment payload is well-formed x402 v2
    - Authorization recipient matches our wallet
    - Authorization amount >= our required amount
    - Validity window is correct (validAfter <= now, validBefore > now)
    - EIP-712 signature is cryptographically valid for the claimed sender

    Returns dict with 'valid' (bool) and 'reason' (str) on failure.
    """
    import json as _json
    try:
        from x402.schemas.helpers import parse_payment_payload
        from x402.mechanisms.evm.types import ExactEIP3009Payload
        from x402.mechanisms.evm.eip712 import hash_eip3009_authorization
        from x402.mechanisms.evm.verify import verify_eoa_signature
        from x402.mechanisms.evm.utils import get_evm_chain_id, hex_to_bytes
    except ImportError as e:
        logger.error("x402 EVM packages not available: %s", e)
        return {"valid": False, "reason": "Server missing EVM verification packages"}

    # Parse the payment header (may be base64 or JSON)
    try:
        import base64
        try:
            raw = base64.b64decode(payment_header)
        except Exception:
            raw = payment_header.encode() if isinstance(payment_header, str) else payment_header
        payload = parse_payment_payload(raw)
    except Exception as e:
        return {"valid": False, "reason": f"Malformed payment payload: {e}"}

    # Must be v2
    if not hasattr(payload, 'accepted') or not hasattr(payload, 'payload'):
        return {"valid": False, "reason": "Not a valid x402 v2 payment payload"}

    # Extract EIP-3009 authorization
    try:
        evm_payload = ExactEIP3009Payload.from_dict(payload.payload)
    except Exception as e:
        return {"valid": False, "reason": f"Invalid EVM payload: {e}"}

    auth = evm_payload.authorization

    # Validate recipient matches our wallet
    if auth.to.lower() != X402_WALLET.lower():
        return {"valid": False, "reason": "Recipient mismatch"}

    # Validate amount
    if int(auth.value) < int(X402_AMOUNT):
        return {"valid": False, "reason": f"Insufficient amount: {auth.value} < {X402_AMOUNT}"}

    # Validate timing
    import time as _time
    now = int(_time.time())
    if int(auth.valid_before) < now + 6:
        return {"valid": False, "reason": "Authorization expired"}
    if int(auth.valid_after) > now:
        return {"valid": False, "reason": "Authorization not yet valid"}

    # Verify EIP-712 signature
    if not evm_payload.signature:
        return {"valid": False, "reason": "Missing signature"}

    try:
        chain_id = get_evm_chain_id(X402_NETWORK)
        hash_bytes = hash_eip3009_authorization(
            auth, chain_id, X402_ASSET, X402_TOKEN_NAME, X402_TOKEN_VERSION
        )
        sig_bytes = hex_to_bytes(evm_payload.signature)
        valid = verify_eoa_signature(hash_bytes, sig_bytes, auth.from_address)
        if not valid:
            return {"valid": False, "reason": "Invalid signature"}
    except Exception as e:
        return {"valid": False, "reason": f"Signature verification error: {e}"}

    return {"valid": True, "payer": auth.from_address}


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

    # Check x402 payment — accept both v2 (PAYMENT-SIGNATURE) and v1 (X-PAYMENT)
    payment_header = (
        request.headers.get("payment-signature")
        or request.headers.get("X-PAYMENT")
    )
    if payment_header:
        payment_method = "x402"

        # Replay protection FIRST — always runs regardless of X402_VERIFY.
        # Hash the raw header so even unverified payments can't be replayed.
        import hashlib
        sig_hash = hashlib.sha256(payment_header.encode()).hexdigest()

        # Fast-path: in-memory check (per-worker, no I/O)
        if sig_hash in _USED_SIGS_MEM:
            logger.warning("x402 replay rejected (mem): sig_hash=%s", sig_hash[:16])
            log_call(tool_name, "x402:replay", status_code=402, client_ip=client_ip)
            return JSONResponse(
                status_code=402,
                content={"error": "Payment signature already used (replay rejected)"},
                headers={"Cache-Control": "no-store", "PAYMENT-REQUIRED": _payment_required_header(path)},
            )

        # Atomic claim in SQLite — INSERT OR IGNORE + rowcount.
        # With --workers 2, two workers racing on the same signature will have
        # exactly one succeed (rowcount=1) and the other get rowcount=0.
        # Claim happens BEFORE verification to eliminate the TOCTOU gap.
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        expires_at = (_dt.now(_tz.utc) + _td(minutes=10)).isoformat()
        if not try_claim_signature(sig_hash, expires_at):
            logger.warning("x402 replay rejected (db): sig_hash=%s", sig_hash[:16])
            log_call(tool_name, "x402:replay", status_code=402, client_ip=client_ip)
            return JSONResponse(
                status_code=402,
                content={"error": "Payment signature already used (replay rejected)"},
                headers={"Cache-Control": "no-store", "PAYMENT-REQUIRED": _payment_required_header(path)},
            )

        # Signature claimed — record in memory for fast-path on this worker
        _USED_SIGS_MEM[sig_hash] = time.monotonic()
        if len(_USED_SIGS_MEM) > _USED_SIGS_MEM_MAX:
            oldest = next(iter(_USED_SIGS_MEM))
            del _USED_SIGS_MEM[oldest]

        # Network tampering check — always runs regardless of X402_VERIFY.
        # Reject if the payment payload claims a different network than our config.
        try:
            _raw = base64.b64decode(payment_header) if not payment_header.strip().startswith("{") else payment_header.encode()
            _pdata = _json.loads(_raw)
            # x402 v2: accepted.network must match
            _accepted = _pdata.get("accepted", {})
            _payload_network = _accepted.get("network", "")
            if _payload_network and _payload_network != X402_NETWORK:
                logger.warning("x402 network mismatch: payload=%s expected=%s", _payload_network, X402_NETWORK)
                log_call(tool_name, "x402:network-mismatch", status_code=402, client_ip=client_ip)
                return JSONResponse(
                    status_code=402,
                    content={"error": f"Network mismatch: payment is for {_payload_network}, server requires {X402_NETWORK}"},
                    headers={"Cache-Control": "no-store", "PAYMENT-REQUIRED": _payment_required_header(path)},
                )
        except Exception:
            pass  # Parsing failures will be caught by _verify_payment_locally if verify is on

        payer = "unverified"
        if X402_VERIFY:
            verify_result = _verify_payment_locally(payment_header)
            if not verify_result["valid"]:
                logger.warning("x402 verification failed: %s", verify_result["reason"])
                log_call(tool_name, "x402:failed", status_code=402, client_ip=client_ip)
                return JSONResponse(
                    status_code=402,
                    content={"error": f"Payment verification failed: {verify_result['reason']}"},
                    headers={"Cache-Control": "no-store", "PAYMENT-REQUIRED": _payment_required_header(path)},
                )
            payer = verify_result.get("payer", "unknown")

        # Update the claimed signature with actual payer identity
        if payer not in ("pending", "unverified"):
            from metering import _get_db
            conn = _get_db()
            conn.execute("UPDATE used_signatures SET payer = ? WHERE signature_hash = ?", (payer, sig_hash))
            conn.commit()
            conn.close()
    else:
        # No payment — return 402
        log_call(tool_name, "none", status_code=402, client_ip=client_ip)
        return _build_402_response(path)
    response = await call_next(request)

    # Read the streaming response body so we can build a new Response with extra headers.
    # Starlette's call_next returns a StreamingResponse whose headers may already be sealed;
    # adding headers after the fact doesn't reliably propagate them.
    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    new_headers = dict(response.headers)
    # Prevent proxy/CDN caching of paid responses — each request must hit the app
    # so replay protection can check the signature against the used_signatures table.
    new_headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    new_headers["Vary"] = "Payment-Signature"

    # Attach PAYMENT-RESPONSE header on successful paid responses (x402 v2 spec).
    # Must include 'success', 'transaction', and 'network' fields for SettleResponse
    # compatibility with the x402 Python SDK's get_payment_settle_response().
    if 200 <= response.status_code < 300:
        settlement = {
            "success": True,
            "transaction": sig_hash,
            "network": X402_NETWORK,
            "x402Version": 2,
            "scheme": "exact",
            "asset": X402_ASSET,
            "amount": X402_AMOUNT,
            "payTo": X402_WALLET,
            "payer": payer,
            "verification": "local-eip712" if X402_VERIFY else "none",
        }
        encoded = base64.b64encode(_json.dumps(settlement).encode()).decode()
        new_headers["PAYMENT-RESPONSE"] = encoded

    elapsed_ms = (time.monotonic() - start) * 1000
    log_call(
        tool_name=tool_name,
        payment_method=payment_method,
        response_time_ms=elapsed_ms,
        status_code=response.status_code,
        client_ip=client_ip,
    )
    return Response(
        content=body,
        status_code=response.status_code,
        headers=new_headers,
        media_type=response.media_type,
    )


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


# ── Legacy path redirects (backwards compatibility) ──
# Routes were moved to /api/v1/ prefix; redirect old paths so existing
# clients, docs, and registry submissions keep working.

_LEGACY_TOOLS = ("stock_quote", "company_fundamentals", "economic_indicator",
                 "sec_filing", "crypto_price")

for _tool in _LEGACY_TOOLS:
    def _make_redirect(tool_name: str):
        async def _redirect(request: Request):
            qs = str(request.url.query)
            target = f"/api/v1/{tool_name}" + (f"?{qs}" if qs else "")
            return RedirectResponse(url=target, status_code=307)
        _redirect.__name__ = f"legacy_redirect_{tool_name}"
        return _redirect
    app.add_api_route(f"/{_tool}", _make_redirect(_tool), methods=["GET"])

# ── Paid tool endpoints ──

@app.get("/api/v1/stock_quote")
def api_stock_quote(
    ticker: str = Query(None, description="Stock ticker (e.g. AAPL, TSLA)"),
    symbol: str = Query(None, description="Alias for ticker"),
):
    """Real-time stock price, volume, and change %."""
    ticker = ticker or symbol
    if not ticker:
        return JSONResponse(status_code=422, content={"error": "Missing required parameter: ticker (or symbol)"})
    ticker = ticker.upper().strip()
    cached = stock_cache.get(f"stock:{ticker}")
    if cached is not None:
        return cached
    result = get_stock_quote(ticker)
    err = _error_response(result)
    if err:
        return err
    stock_cache.set(f"stock:{ticker}", result)
    return result


@app.get("/api/v1/company_fundamentals")
def api_company_fundamentals(
    ticker: str = Query(None, description="Stock ticker (e.g. AAPL)"),
    symbol: str = Query(None, description="Alias for ticker"),
):
    """Revenue, P/E, market cap, sector, beta, dividends, and company description."""
    ticker = ticker or symbol
    if not ticker:
        return JSONResponse(status_code=422, content={"error": "Missing required parameter: ticker (or symbol)"})
    ticker = ticker.upper().strip()
    cached = fundamentals_cache.get(f"fundamentals:{ticker}")
    if cached is not None:
        return cached
    result = get_company_fundamentals(ticker)
    err = _error_response(result)
    if err:
        return err
    fundamentals_cache.set(f"fundamentals:{ticker}", result)
    return result


@app.get("/api/v1/economic_indicator")
def api_economic_indicator(
    series_id: str = Query(None, description="FRED series ID (e.g. GDP, CPIAUCSL, UNRATE)"),
    indicator: str = Query(None, description="Alias for series_id"),
):
    """US macroeconomic data from the Federal Reserve FRED database."""
    series_id = series_id or indicator
    if not series_id:
        return JSONResponse(status_code=422, content={"error": "Missing required parameter: series_id (or indicator)"})
    series_id = resolve_series_id(series_id)
    cached = economic_cache.get(f"econ:{series_id}")
    if cached is not None:
        return cached
    result = get_economic_indicator(series_id)
    err = _error_response(result)
    if err:
        return err
    economic_cache.set(f"econ:{series_id}", result)
    return result


@app.get("/api/v1/sec_filing")
def api_sec_filing(
    ticker_or_cik: str = Query(None, description="Ticker (AAPL) or CIK (320193)"),
    ticker: str = Query(None, description="Alias for ticker_or_cik"),
    form_type: str = Query("10-K", description="Form type (10-K, 10-Q, 8-K, DEF 14A, S-1)"),
):
    """Full text of SEC filings from EDGAR."""
    ticker_or_cik = ticker_or_cik or ticker
    if not ticker_or_cik:
        return JSONResponse(status_code=422, content={"error": "Missing required parameter: ticker_or_cik (or ticker)"})
    ticker_or_cik = ticker_or_cik.strip().upper()
    form_type = form_type.strip().upper()
    cache_key = f"sec:{ticker_or_cik}:{form_type}"
    cached = sec_cache.get(cache_key)
    if cached is not None:
        return cached
    result = get_sec_filing(ticker_or_cik, form_type)
    err = _error_response(result)
    if err:
        return err
    sec_cache.set(cache_key, result)
    return result


@app.get("/api/v1/crypto_price")
def api_crypto_price(
    coin_id: str = Query(None, description="CoinGecko ID (e.g. bitcoin, ethereum, solana)"),
    symbol: str = Query(None, description="Alias for coin_id"),
):
    """Cryptocurrency price, market cap, volume, and 7-day sparkline."""
    coin_id = coin_id or symbol
    if not coin_id:
        return JSONResponse(status_code=422, content={"error": "Missing required parameter: coin_id (or symbol)"})
    coin_id = resolve_coin_id(coin_id)
    cached = crypto_cache.get(f"crypto:{coin_id}")
    if cached is not None:
        return cached
    result = get_crypto_price(coin_id)
    err = _error_response(result)
    if err:
        return err
    crypto_cache.set(f"crypto:{coin_id}", result)
    return result
