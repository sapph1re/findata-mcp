"""company_fundamentals tool — revenue, earnings, P/E, market cap via yfinance."""

import time
from typing import Any

import yfinance as yf


def get_company_fundamentals(ticker: str) -> dict[str, Any]:
    """Fetch company fundamental data."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or not info.get("shortName"):
            return {"error": f"Ticker '{ticker}' not found", "ticker": ticker}

        return {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "description": info.get("longBusinessSummary"),
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "revenue": info.get("totalRevenue"),
            "revenue_growth": info.get("revenueGrowth"),
            "gross_margins": info.get("grossMargins"),
            "ebitda": info.get("ebitda"),
            "net_income": info.get("netIncomeToCommon"),
            "earnings_per_share": info.get("trailingEps"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "employees": info.get("fullTimeEmployees"),
            "country": info.get("country"),
            "website": info.get("website"),
            "currency": info.get("currency", "USD"),
            "timestamp": int(time.time()),
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}
