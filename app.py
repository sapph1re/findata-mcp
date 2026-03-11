"""FinData MCP — HTTP API server with x402 micropayments.

All tool endpoints require x402 payment at $0.01 USDC per call.
No API keys, no subscription tiers — just pay-per-call.

Run: uvicorn app:app --host 0.0.0.0 --port 8080
"""

import os
import time
import logging
import asyncio
import base64
import json as _json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
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
# USDC contract address (Base mainnet default)
X402_ASSET = os.environ.get(
    "X402_ASSET_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
)
X402_AMOUNT = os.environ.get("X402_AMOUNT", "10000")  # $0.01 USDC (6 decimals)
X402_VERIFY = os.environ.get("X402_VERIFY", "true").lower() == "true"
# EIP-712 domain params for USDC on Base mainnet
X402_TOKEN_NAME = os.environ.get("X402_TOKEN_NAME", "USD Coin")
X402_TOKEN_VERSION = os.environ.get("X402_TOKEN_VERSION", "2")

# ── On-chain settlement via x402 SDK ──
# When FINDATA_X402_PRIVATE_KEY and BASE_MAINNET_RPC are set, the server acts as
# its own facilitator: it submits transferWithAuthorization on-chain after verifying
# the EIP-3009 signature, then returns the real tx hash in PAYMENT-RESPONSE.
_X402_PRIVATE_KEY = os.environ.get("FINDATA_X402_PRIVATE_KEY", "")
_X402_RPC_URL = os.environ.get("BASE_MAINNET_RPC", "")
_settle_scheme = None  # Initialized at startup if credentials are available

def _init_settlement():
    """Initialize on-chain settlement if private key + RPC are available."""
    global _settle_scheme
    if not _X402_PRIVATE_KEY or not _X402_RPC_URL:
        logger.warning("On-chain settlement disabled: FINDATA_X402_PRIVATE_KEY or BASE_MAINNET_RPC not set")
        return
    try:
        from x402.mechanisms.evm.signers import FacilitatorWeb3Signer
        from x402.mechanisms.evm.exact.facilitator import ExactEvmScheme
        signer = FacilitatorWeb3Signer(
            private_key=_X402_PRIVATE_KEY,
            rpc_url=_X402_RPC_URL,
        )
        _settle_scheme = ExactEvmScheme(signer)
        logger.info("On-chain settlement enabled via FacilitatorWeb3Signer (address=%s)", signer.address)
    except Exception as e:
        logger.error("Failed to initialize on-chain settlement: %s", e)

# Routes that require payment — both canonical /api/v1/ and legacy root paths.
# Legacy root paths are registered as direct handlers (NOT redirects) because the
# x402 Python SDK's httpx client breaks on 307 redirects with streaming body errors.
PAID_PREFIXES = ("/api/v1/stock_quote", "/api/v1/company_fundamentals",
                 "/api/v1/economic_indicator", "/api/v1/sec_filing",
                 "/api/v1/crypto_price",
                 "/stock_quote", "/company_fundamentals",
                 "/economic_indicator", "/sec_filing",
                 "/crypto_price")

# In-memory replay protection — belt-and-suspenders alongside SQLite.
# Catches replays even if SQLite file doesn't persist (e.g. ephemeral Railway storage).
# Bounded to prevent unbounded growth; oldest entries evicted via dict ordering (Python 3.7+).
_USED_SIGS_MEM: dict[str, float] = {}  # sig_hash → timestamp
_USED_SIGS_MEM_MAX = 10000

# Serialize on-chain settlements so nonces don't collide when requests arrive
# faster than Base block time (~2s).  The lock is asyncio-based; the blocking
# settle() call runs in a thread via asyncio.to_thread so the event loop stays
# responsive for health checks and other non-paid routes.
_settlement_lock = asyncio.Lock()

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
    if "temporarily unavailable" in err:
        return JSONResponse(status_code=503, content=result)
    return JSONResponse(status_code=502, content=result)


# ── App ──

@asynccontextmanager
async def lifespan(application: FastAPI):
    init_metering_db()
    purge_expired_signatures()
    _init_settlement()
    settle_mode = "on-chain" if _settle_scheme else ("local-eip712" if X402_VERIFY else "none")
    logger.info("FinData MCP started — x402 network=%s, settle=%s", X402_NETWORK, settle_mode)
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
    # x402 JS SDK expects "maxAmountRequired" but Python SDK serializes as "amount"
    for entry in body.get("accepts", []):
        if "amount" in entry:
            entry["maxAmountRequired"] = entry.pop("amount")
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
    # x402 JS SDK expects "maxAmountRequired" but Python SDK serializes as "amount"
    for entry in body.get("accepts", []):
        if "amount" in entry:
            entry["maxAmountRequired"] = entry.pop("amount")
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
        # Two layers: (1) SHA-256 of raw header bytes, (2) EIP-3009 authorization
        # nonce extracted from the payload. Layer 2 catches replays even when the
        # same authorization is re-encoded with different JSON formatting.
        import hashlib
        sig_hash = hashlib.sha256(payment_header.encode()).hexdigest()

        # Extract EIP-3009 nonce for content-based dedup (best-effort).
        eip3009_nonce_key = None
        try:
            _raw_replay = base64.b64decode(payment_header) if not payment_header.strip().startswith("{") else payment_header.encode()
            _rdata = _json.loads(_raw_replay)
            _payload_data = _rdata.get("payload", {})
            _auth_data = _payload_data.get("authorization", {})
            _eip_from = _auth_data.get("from", _auth_data.get("from_address", ""))
            _eip_nonce = _auth_data.get("nonce", "")
            if _eip_from and _eip_nonce:
                eip3009_nonce_key = f"eip3009:{_eip_from.lower()}:{_eip_nonce}"
        except Exception:
            pass  # Payload parsing is best-effort; hash-based check is the primary guard

        # Fast-path: in-memory check (per-worker, no I/O)
        if sig_hash in _USED_SIGS_MEM or (eip3009_nonce_key and eip3009_nonce_key in _USED_SIGS_MEM):
            logger.warning("x402 replay rejected (mem): sig_hash=%s", sig_hash[:16])
            log_call(tool_name, "x402:replay", status_code=402, client_ip=client_ip)
            return JSONResponse(
                status_code=402,
                content={"error": "Payment signature already used (replay rejected)"},
                headers={"Cache-Control": "no-store", "PAYMENT-REQUIRED": _payment_required_header(path)},
            )

        # Atomic claim in SQLite — INSERT OR IGNORE + rowcount.
        # Claim happens BEFORE verification to eliminate the TOCTOU gap.
        # 24-hour expiry: EIP-3009 authorizations can be valid for hours.
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        expires_at = (_dt.now(_tz.utc) + _td(hours=24)).isoformat()
        if not try_claim_signature(sig_hash, expires_at):
            logger.warning("x402 replay rejected (db): sig_hash=%s", sig_hash[:16])
            log_call(tool_name, "x402:replay", status_code=402, client_ip=client_ip)
            return JSONResponse(
                status_code=402,
                content={"error": "Payment signature already used (replay rejected)"},
                headers={"Cache-Control": "no-store", "PAYMENT-REQUIRED": _payment_required_header(path)},
            )
        # Also claim the EIP-3009 nonce key if extracted (catches re-encoded replays)
        if eip3009_nonce_key:
            try_claim_signature(eip3009_nonce_key, expires_at)

        # Signature claimed — record in memory for fast-path on this worker
        _USED_SIGS_MEM[sig_hash] = time.monotonic()
        if eip3009_nonce_key:
            _USED_SIGS_MEM[eip3009_nonce_key] = time.monotonic()
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
        settle_result = None  # Will hold SettleResponse if on-chain settlement succeeds

        if _settle_scheme:
            # On-chain settlement: verify + submit transferWithAuthorization.
            # Serialized via _settlement_lock so two rapid requests don't race
            # on the facilitator nonce (Base blocks are ~2s).
            # Retries up to 3 times with exponential backoff for transient nonce
            # errors ("nonce too low", "replacement transaction underpriced")
            # that occur when the previous tx hasn't been mined yet.
            _NONCE_ERROR_PATTERNS = ("nonce too low", "replacement transaction underpriced", "already known")
            _MAX_SETTLE_RETRIES = 3
            try:
                from x402.schemas import PaymentRequirements
                from x402.schemas.helpers import parse_payment_payload

                _raw_pay = base64.b64decode(payment_header) if not payment_header.strip().startswith("{") else payment_header.encode()
                pay_payload = parse_payment_payload(_raw_pay)
                pay_requirements = PaymentRequirements(
                    scheme="exact",
                    network=X402_NETWORK,
                    asset=X402_ASSET,
                    amount=X402_AMOUNT,
                    pay_to=X402_WALLET,
                    max_timeout_seconds=300,
                    extra={"name": X402_TOKEN_NAME, "version": X402_TOKEN_VERSION},
                )

                last_error_reason = ""
                for _attempt in range(_MAX_SETTLE_RETRIES):
                    async with _settlement_lock:
                        settle_result = await asyncio.to_thread(
                            _settle_scheme.settle, pay_payload, pay_requirements
                        )
                        if settle_result.success:
                            # Hold the lock an extra 2s so the next request's
                            # nonce query sees the mined tx.
                            await asyncio.sleep(2)
                            break
                        # Check if the failure is a transient nonce error worth retrying
                        reason = settle_result.error_reason or ""
                        msg = settle_result.error_message or ""
                        combined = f"{reason} {msg}".lower()
                        last_error_reason = reason or "unknown"
                        if any(pat in combined for pat in _NONCE_ERROR_PATTERNS):
                            logger.warning("x402 settlement nonce error (attempt %d/%d): %s (%s)",
                                           _attempt + 1, _MAX_SETTLE_RETRIES, reason, msg)
                            if _attempt < _MAX_SETTLE_RETRIES - 1:
                                await asyncio.sleep(2 ** (_attempt + 1))  # 2s, 4s backoff
                                continue
                        # Non-nonce failure or final retry exhausted
                        break

                if not settle_result.success:
                    logger.warning("x402 settlement failed: %s", last_error_reason)
                    log_call(tool_name, "x402:failed", status_code=402, client_ip=client_ip)
                    # Sanitize: never expose raw RPC/node error details to clients
                    return JSONResponse(
                        status_code=402,
                        content={"error": "Payment settlement failed: please retry with a new payment"},
                        headers={"Cache-Control": "no-store", "PAYMENT-REQUIRED": _payment_required_header(path)},
                    )
                payer = settle_result.payer or "unknown"
                logger.info("x402 settled on-chain: tx=%s payer=%s", settle_result.transaction, payer)
            except Exception as e:
                logger.error("x402 settlement error: %s", e)
                log_call(tool_name, "x402:failed", status_code=402, client_ip=client_ip)
                return JSONResponse(
                    status_code=402,
                    content={"error": "Payment settlement error: please retry"},
                    headers={"Cache-Control": "no-store", "PAYMENT-REQUIRED": _payment_required_header(path)},
                )
        elif X402_VERIFY:
            # Fallback: local EIP-712 verification only (no on-chain settlement)
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
    if 200 <= response.status_code < 300:
        if settle_result and settle_result.success:
            # On-chain settlement: real tx hash, verifiable on Base
            tx_hash = settle_result.transaction
            if not tx_hash.startswith("0x"):
                tx_hash = "0x" + tx_hash
            settlement = {
                "success": True,
                "transaction": tx_hash,
                "transactionType": "transfer",
                "network": X402_NETWORK,
                "x402Version": 2,
                "scheme": "exact",
                "asset": X402_ASSET,
                "amount": X402_AMOUNT,
                "payTo": X402_WALLET,
                "payer": payer,
                "verification": "on-chain",
            }
        else:
            # Fallback: local verification only (no on-chain proof)
            verification_mode = "local-eip712" if X402_VERIFY else "none"
            settlement = {
                "success": True,
                "transaction": sig_hash,
                "transactionType": "receipt" if verification_mode == "local-eip712" else "none",
                "network": X402_NETWORK,
                "x402Version": 2,
                "scheme": "exact",
                "asset": X402_ASSET,
                "amount": X402_AMOUNT,
                "payTo": X402_WALLET,
                "payer": payer,
                "verification": verification_mode,
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


# ── Legacy root paths ──
# Registered as direct handlers (NOT 307 redirects) because the x402 Python SDK's
# httpx client breaks on redirects with: "Attempted to access streaming request
# content, without having called read()". These delegate to the canonical handlers.

@app.get("/stock_quote", include_in_schema=False)
def legacy_stock_quote(
    ticker: str = Query(None), symbol: str = Query(None),
):
    return api_stock_quote(ticker=ticker, symbol=symbol)

@app.get("/company_fundamentals", include_in_schema=False)
def legacy_company_fundamentals(
    ticker: str = Query(None), symbol: str = Query(None),
):
    return api_company_fundamentals(ticker=ticker, symbol=symbol)

@app.get("/economic_indicator", include_in_schema=False)
def legacy_economic_indicator(
    series_id: str = Query(None), indicator: str = Query(None),
):
    return api_economic_indicator(series_id=series_id, indicator=indicator)

@app.get("/sec_filing", include_in_schema=False)
def legacy_sec_filing(
    ticker_or_cik: str = Query(None), ticker: str = Query(None),
    form_type: str = Query("10-K"),
):
    return api_sec_filing(ticker_or_cik=ticker_or_cik, ticker=ticker, form_type=form_type)

@app.get("/crypto_price", include_in_schema=False)
def legacy_crypto_price(
    coin_id: str = Query(None), symbol: str = Query(None),
):
    return api_crypto_price(coin_id=coin_id, symbol=symbol)
