"""crypto_price tool — price, market cap, volume, sparkline via CoinGecko API."""

import time
import threading
from typing import Any

import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Map common ticker symbols to CoinGecko coin IDs
SYMBOL_TO_COINGECKO_ID: dict[str, str] = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "ada": "cardano",
    "doge": "dogecoin",
    "dot": "polkadot",
    "matic": "matic-network",
    "shib": "shiba-inu",
    "avax": "avalanche-2",
    "link": "chainlink",
    "uni": "uniswap",
    "atom": "cosmos",
    "ltc": "litecoin",
    "etc": "ethereum-classic",
    "xlm": "stellar",
    "near": "near",
    "apt": "aptos",
    "arb": "arbitrum",
    "op": "optimism",
    "sui": "sui",
    "usdt": "tether",
    "usdc": "usd-coin",
    "dai": "dai",
    "wbtc": "wrapped-bitcoin",
    "weth": "weth",
    "pepe": "pepe",
    "fil": "filecoin",
    "hbar": "hedera-hashgraph",
    "icp": "internet-computer",
    "vet": "vechain",
    "aave": "aave",
    "mkr": "maker",
    "crv": "curve-dao-token",
    "ldo": "lido-dao",
    "render": "render-token",
    "ftm": "fantom",
    "algo": "algorand",
    "sei": "sei-network",
    "inj": "injective-protocol",
    "stx": "blockstack",
    "trx": "tron",
}


def resolve_coin_id(raw: str) -> str:
    """Resolve a symbol or coin_id to a CoinGecko coin ID."""
    normalized = raw.strip().lower()
    return SYMBOL_TO_COINGECKO_ID.get(normalized, normalized)


# Simple rate limiter: max 25 requests per 60 seconds (CoinGecko free tier = 30/min)
_rate_lock = threading.Lock()
_request_times: list[float] = []
_RATE_LIMIT = 25
_RATE_WINDOW = 60.0


def _check_rate_limit() -> bool:
    """Return True if request is allowed, False if rate limited."""
    now = time.time()
    with _rate_lock:
        _request_times[:] = [t for t in _request_times if now - t < _RATE_WINDOW]
        if len(_request_times) >= _RATE_LIMIT:
            return False
        _request_times.append(now)
        return True


def get_crypto_price(coin_id: str) -> dict[str, Any]:
    """Fetch cryptocurrency price data from CoinGecko."""
    if not _check_rate_limit():
        return {
            "error": "CoinGecko rate limit exceeded (30 req/min). Try again shortly.",
            "coin_id": coin_id,
        }
    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "true",
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )

        if resp.status_code == 404:
            return {"error": f"Coin '{coin_id}' not found on CoinGecko", "coin_id": coin_id}

        if resp.status_code == 429:
            return {
                "error": "CoinGecko rate limit exceeded (30 req/min). Try again shortly.",
                "coin_id": coin_id,
            }

        resp.raise_for_status()
        data = resp.json()

        market = data.get("market_data", {})
        sparkline_data = market.get("sparkline_7d", {}).get("price", [])

        # Downsample sparkline to ~24 points (one per ~7 hours)
        if len(sparkline_data) > 24:
            step = len(sparkline_data) // 24
            sparkline_data = [round(sparkline_data[i], 2) for i in range(0, len(sparkline_data), step)][:24]

        return {
            "coin_id": coin_id,
            "name": data.get("name"),
            "symbol": data.get("symbol", "").upper(),
            "price_usd": market.get("current_price", {}).get("usd"),
            "market_cap_usd": market.get("market_cap", {}).get("usd"),
            "total_volume_24h_usd": market.get("total_volume", {}).get("usd"),
            "price_change_24h_pct": market.get("price_change_percentage_24h"),
            "price_change_7d_pct": market.get("price_change_percentage_7d"),
            "price_change_30d_pct": market.get("price_change_percentage_30d"),
            "ath_usd": market.get("ath", {}).get("usd"),
            "ath_date": market.get("ath_date", {}).get("usd"),
            "circulating_supply": market.get("circulating_supply"),
            "max_supply": market.get("max_supply"),
            "sparkline_7d": sparkline_data,
            "last_updated": data.get("last_updated"),
            "source": "CoinGecko",
            "timestamp": int(time.time()),
        }

    except requests.exceptions.HTTPError as e:
        return {"error": f"CoinGecko API error: {str(e)}", "coin_id": coin_id}
    except Exception as e:
        return {"error": str(e), "coin_id": coin_id}
