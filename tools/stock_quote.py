"""stock_quote tool — real-time/delayed stock price via yfinance."""

import time
from typing import Any

import yfinance as yf


def get_stock_quote(ticker: str) -> dict[str, Any]:
    """Fetch real-time (15-min delayed) stock quote."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or info.get("trailingPegRatio") is None and info.get("regularMarketPrice") is None:
            # Try fast_info as fallback
            fi = stock.fast_info
            if fi is None:
                return {"error": f"Ticker '{ticker}' not found", "ticker": ticker}

        price = info.get("regularMarketPrice") or info.get("currentPrice")
        prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")

        if price is None:
            return {"error": f"No price data available for '{ticker}'", "ticker": ticker}

        change = None
        change_pct = None
        if price is not None and prev_close is not None and prev_close != 0:
            change = round(price - prev_close, 4)
            change_pct = round((change / prev_close) * 100, 4)

        return {
            "ticker": ticker,
            "price": price,
            "currency": info.get("currency", "USD"),
            "change": change,
            "change_percent": change_pct,
            "volume": info.get("regularMarketVolume") or info.get("volume"),
            "market_cap": info.get("marketCap"),
            "day_high": info.get("regularMarketDayHigh") or info.get("dayHigh"),
            "day_low": info.get("regularMarketDayLow") or info.get("dayLow"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "exchange": info.get("exchange"),
            "timestamp": int(time.time()),
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}
