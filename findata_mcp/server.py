"""FinData MCP — Thin client that proxies to hosted backend with x402 auto-payment."""

import os
from typing import Any

from fastmcp import FastMCP

from findata_mcp.client import FinDataClient

mcp = FastMCP(
    name="findata-mcp",
    version="0.3.0",
    instructions=(
        "Financial data via hosted backend. 5 tools: stock_quote, company_fundamentals, "
        "economic_indicator, sec_filing, crypto_price. Requires EVM_PRIVATE_KEY for x402 "
        "payments ($0.01/call USDC on Base mainnet)."
    ),
)

_client = None


def _get_client() -> FinDataClient:
    global _client
    if _client is None:
        _client = FinDataClient(
            backend_url=os.environ.get(
                "FINDATA_BACKEND_URL",
                "https://findata-mcp-production-1cd3.up.railway.app",
            ),
            private_key=os.environ.get("EVM_PRIVATE_KEY", ""),
        )
    return _client


@mcp.tool()
def stock_quote(ticker: str) -> dict[str, Any]:
    """Real-time (15-min delayed) stock price, volume, and change % for any NYSE/NASDAQ/global ticker.

    Args:
        ticker: Stock ticker symbol (e.g. AAPL, TSLA, MSFT, NVDA)
    """
    return _get_client().call("stock_quote", ticker=ticker)


@mcp.tool()
def company_fundamentals(ticker: str) -> dict[str, Any]:
    """Full fundamental data: revenue, earnings, P/E ratio, market cap, sector, beta, dividend yield, and company description.

    Args:
        ticker: Stock ticker symbol (e.g. AAPL, TSLA, MSFT)
    """
    return _get_client().call("company_fundamentals", ticker=ticker)


@mcp.tool()
def economic_indicator(series_id: str) -> dict[str, Any]:
    """US macroeconomic data from the Federal Reserve FRED database: GDP, CPI, unemployment, interest rates, yield curves, and 800,000+ economic series.

    Args:
        series_id: FRED series ID (e.g. GDP, CPIAUCSL, UNRATE, FEDFUNDS, DGS10)
    """
    return _get_client().call("economic_indicator", series_id=series_id)


@mcp.tool()
def sec_filing(ticker_or_cik: str, form_type: str = "10-K") -> dict[str, Any]:
    """Full text of SEC filings from EDGAR: 10-K annual reports, 10-Q quarterlies, 8-K material events, proxy statements.

    Args:
        ticker_or_cik: Stock ticker (AAPL) or SEC CIK number (320193)
        form_type: SEC form type (10-K, 10-Q, 8-K, DEF 14A, S-1)
    """
    return _get_client().call("sec_filing", ticker_or_cik=ticker_or_cik, form_type=form_type)


@mcp.tool()
def crypto_price(coin_id: str) -> dict[str, Any]:
    """Cryptocurrency price, market cap, 24h volume, and 7-day sparkline via CoinGecko.

    Args:
        coin_id: CoinGecko coin ID in lowercase-hyphenated format (e.g. bitcoin, ethereum, solana, chainlink)
    """
    return _get_client().call("crypto_price", coin_id=coin_id)
