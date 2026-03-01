"""
FinData MCP — Financial Data Server
Five tools covering stocks, fundamentals, economic indicators, SEC filings, and crypto.
"""

import time
import logging
from typing import Any

from fastmcp import FastMCP

from cache import TTLCache
from tools.stock_quote import get_stock_quote
from tools.company_fundamentals import get_company_fundamentals
from tools.economic_indicator import get_economic_indicator
from tools.sec_filing import get_sec_filing
from tools.crypto_price import get_crypto_price

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("findata-mcp")

# Cache instances with different TTLs
stock_cache = TTLCache(ttl_seconds=60)         # 1 min
fundamentals_cache = TTLCache(ttl_seconds=3600) # 1 hr
economic_cache = TTLCache(ttl_seconds=21600)    # 6 hr
sec_cache = TTLCache(ttl_seconds=86400)         # 24 hr
crypto_cache = TTLCache(ttl_seconds=60)         # 1 min

mcp = FastMCP(
    name="findata-mcp",
    version="0.1.0",
    instructions="Financial data server with 5 tools: stock_quote, company_fundamentals, economic_indicator, sec_filing, crypto_price. All return structured JSON.",
)


@mcp.tool()
def stock_quote(ticker: str) -> dict[str, Any]:
    """Real-time (15-min delayed) stock price, volume, and change % for any NYSE/NASDAQ/global ticker.

    Args:
        ticker: Stock ticker symbol (e.g. AAPL, TSLA, MSFT, NVDA)
    """
    ticker = ticker.upper().strip()
    cached = stock_cache.get(f"stock:{ticker}")
    if cached is not None:
        return cached
    result = get_stock_quote(ticker)
    stock_cache.set(f"stock:{ticker}", result)
    return result


@mcp.tool()
def company_fundamentals(ticker: str) -> dict[str, Any]:
    """Full fundamental data: revenue, earnings, P/E ratio, market cap, sector, beta, dividend yield, and company description.

    Args:
        ticker: Stock ticker symbol (e.g. AAPL, TSLA, MSFT)
    """
    ticker = ticker.upper().strip()
    cached = fundamentals_cache.get(f"fundamentals:{ticker}")
    if cached is not None:
        return cached
    result = get_company_fundamentals(ticker)
    fundamentals_cache.set(f"fundamentals:{ticker}", result)
    return result


@mcp.tool()
def economic_indicator(series_id: str) -> dict[str, Any]:
    """US macroeconomic data from the Federal Reserve FRED database: GDP, CPI, unemployment, interest rates, yield curves, and 800,000+ economic series.

    Args:
        series_id: FRED series ID (e.g. GDP, CPIAUCSL, UNRATE, FEDFUNDS, DGS10)
    """
    series_id = series_id.upper().strip()
    cached = economic_cache.get(f"econ:{series_id}")
    if cached is not None:
        return cached
    result = get_economic_indicator(series_id)
    economic_cache.set(f"econ:{series_id}", result)
    return result


@mcp.tool()
def sec_filing(ticker_or_cik: str, form_type: str = "10-K") -> dict[str, Any]:
    """Full text of SEC filings from EDGAR: 10-K annual reports, 10-Q quarterlies, 8-K material events, proxy statements.

    Args:
        ticker_or_cik: Stock ticker (AAPL) or SEC CIK number (320193)
        form_type: SEC form type (10-K, 10-Q, 8-K, DEF 14A, S-1)
    """
    ticker_or_cik = ticker_or_cik.strip().upper()
    form_type = form_type.strip().upper()
    cache_key = f"sec:{ticker_or_cik}:{form_type}"
    cached = sec_cache.get(cache_key)
    if cached is not None:
        return cached
    result = get_sec_filing(ticker_or_cik, form_type)
    sec_cache.set(cache_key, result)
    return result


@mcp.tool()
def crypto_price(coin_id: str) -> dict[str, Any]:
    """Cryptocurrency price, market cap, 24h volume, and 7-day sparkline via CoinGecko.

    Args:
        coin_id: CoinGecko coin ID in lowercase-hyphenated format (e.g. bitcoin, ethereum, solana, chainlink)
    """
    coin_id = coin_id.strip().lower()
    cached = crypto_cache.get(f"crypto:{coin_id}")
    if cached is not None:
        return cached
    result = get_crypto_price(coin_id)
    crypto_cache.set(f"crypto:{coin_id}", result)
    return result


if __name__ == "__main__":
    mcp.run()
