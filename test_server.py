"""Test suite for FinData MCP server — all 5 tools with mocked API responses."""

import json
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from cache import TTLCache
from tools.stock_quote import get_stock_quote
from tools.company_fundamentals import get_company_fundamentals
from tools.economic_indicator import get_economic_indicator
from tools.sec_filing import get_sec_filing, _resolve_cik
from tools.crypto_price import get_crypto_price


# ──────────────────────────────────────────────────────────────────
# Cache tests
# ──────────────────────────────────────────────────────────────────

class TestTTLCache(unittest.TestCase):
    def test_set_and_get(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("key1", {"price": 150.0})
        result = cache.get("key1")
        self.assertEqual(result, {"price": 150.0})

    def test_expired_key_returns_none(self):
        cache = TTLCache(ttl_seconds=0)  # Expires immediately
        cache.set("key1", {"price": 150.0})
        time.sleep(0.01)
        result = cache.get("key1")
        self.assertIsNone(result)

    def test_missing_key_returns_none(self):
        cache = TTLCache(ttl_seconds=60)
        self.assertIsNone(cache.get("nonexistent"))

    def test_clear(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        self.assertIsNone(cache.get("a"))
        self.assertIsNone(cache.get("b"))

    def test_evict_expired(self):
        cache = TTLCache(ttl_seconds=0)
        cache.set("a", 1)
        cache.set("b", 2)
        time.sleep(0.01)
        evicted = cache.evict_expired()
        self.assertEqual(evicted, 2)


# ──────────────────────────────────────────────────────────────────
# stock_quote tests
# ──────────────────────────────────────────────────────────────────

MOCK_STOCK_INFO = {
    "regularMarketPrice": 185.50,
    "regularMarketPreviousClose": 183.20,
    "regularMarketVolume": 52_000_000,
    "marketCap": 2_850_000_000_000,
    "regularMarketDayHigh": 186.10,
    "regularMarketDayLow": 183.00,
    "fiftyTwoWeekHigh": 199.62,
    "fiftyTwoWeekLow": 164.08,
    "currency": "USD",
    "exchange": "NMS",
}


class TestStockQuote(unittest.TestCase):
    @patch("tools.stock_quote.yf.Ticker")
    def test_successful_quote(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = MOCK_STOCK_INFO
        mock_ticker_cls.return_value = mock_ticker

        result = get_stock_quote("AAPL")
        self.assertEqual(result["ticker"], "AAPL")
        self.assertEqual(result["price"], 185.50)
        self.assertEqual(result["currency"], "USD")
        self.assertAlmostEqual(result["change"], 2.30, places=2)
        self.assertIsNotNone(result["change_percent"])
        self.assertEqual(result["volume"], 52_000_000)
        self.assertIn("timestamp", result)

    @patch("tools.stock_quote.yf.Ticker")
    def test_ticker_not_found(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {"regularMarketPrice": None}
        mock_ticker_cls.return_value = mock_ticker

        result = get_stock_quote("ZZZZZZ")
        self.assertIn("error", result)

    @patch("tools.stock_quote.yf.Ticker")
    def test_exception_handling(self, mock_ticker_cls):
        mock_ticker_cls.side_effect = Exception("Network error")
        result = get_stock_quote("AAPL")
        self.assertIn("error", result)
        self.assertEqual(result["ticker"], "AAPL")


# ──────────────────────────────────────────────────────────────────
# company_fundamentals tests
# ──────────────────────────────────────────────────────────────────

MOCK_FUNDAMENTALS_INFO = {
    "shortName": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "longBusinessSummary": "Apple Inc. designs, manufactures...",
    "marketCap": 2_850_000_000_000,
    "trailingPE": 28.5,
    "forwardPE": 26.1,
    "totalRevenue": 394_000_000_000,
    "revenueGrowth": 0.089,
    "grossMargins": 0.462,
    "ebitda": 130_000_000_000,
    "trailingEps": 6.57,
    "dividendYield": 0.0053,
    "beta": 1.24,
    "currency": "USD",
    "fiftyTwoWeekHigh": 199.62,
    "fiftyTwoWeekLow": 164.08,
    "fullTimeEmployees": 161000,
    "country": "United States",
    "website": "https://www.apple.com",
}


class TestCompanyFundamentals(unittest.TestCase):
    @patch("tools.company_fundamentals.yf.Ticker")
    def test_successful_fundamentals(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = MOCK_FUNDAMENTALS_INFO
        mock_ticker_cls.return_value = mock_ticker

        result = get_company_fundamentals("AAPL")
        self.assertEqual(result["ticker"], "AAPL")
        self.assertEqual(result["name"], "Apple Inc.")
        self.assertEqual(result["sector"], "Technology")
        self.assertEqual(result["pe_ratio"], 28.5)
        self.assertEqual(result["revenue"], 394_000_000_000)
        self.assertIn("timestamp", result)

    @patch("tools.company_fundamentals.yf.Ticker")
    def test_ticker_not_found(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        mock_ticker_cls.return_value = mock_ticker

        result = get_company_fundamentals("ZZZZZZ")
        self.assertIn("error", result)


# ──────────────────────────────────────────────────────────────────
# economic_indicator tests
# ──────────────────────────────────────────────────────────────────

MOCK_FRED_META = {
    "seriess": [{
        "title": "Gross Domestic Product",
        "units": "Billions of Dollars",
        "frequency": "Quarterly",
        "seasonal_adjustment": "Seasonally Adjusted Annual Rate",
    }]
}

MOCK_FRED_OBS = {
    "observations": [
        {"date": "2025-10-01", "value": "28500.5"},
        {"date": "2025-07-01", "value": "28100.2"},
        {"date": "2025-04-01", "value": "27800.0"},
    ]
}


class TestEconomicIndicator(unittest.TestCase):
    @patch("tools.economic_indicator.FRED_API_KEY", "test_key_123")
    @patch("tools.economic_indicator.requests.get")
    def test_successful_indicator(self, mock_get):
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            if "/series/observations" in url:
                resp.json.return_value = MOCK_FRED_OBS
            else:
                resp.json.return_value = MOCK_FRED_META
            return resp

        mock_get.side_effect = side_effect

        result = get_economic_indicator("GDP")
        self.assertEqual(result["series_id"], "GDP")
        self.assertEqual(result["title"], "Gross Domestic Product")
        self.assertEqual(result["latest_value"], 28500.5)
        self.assertEqual(len(result["observations"]), 3)
        self.assertIn("timestamp", result)

    @patch("tools.economic_indicator.FRED_API_KEY", "")
    def test_missing_api_key(self):
        result = get_economic_indicator("GDP")
        self.assertIn("error", result)
        self.assertIn("FRED_API_KEY", result["error"])

    @patch("tools.economic_indicator.FRED_API_KEY", "test_key_123")
    @patch("tools.economic_indicator.requests.get")
    def test_rate_limit(self, mock_get):
        resp = MagicMock()
        resp.status_code = 429
        resp.raise_for_status.side_effect = __import__("requests").exceptions.HTTPError(response=resp)
        mock_get.return_value = resp

        result = get_economic_indicator("GDP")
        self.assertIn("error", result)
        self.assertIn("rate limit", result["error"].lower())


# ──────────────────────────────────────────────────────────────────
# sec_filing tests
# ──────────────────────────────────────────────────────────────────

MOCK_TICKERS_JSON = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corporation"},
}

MOCK_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["10-K", "10-Q", "8-K", "10-Q"],
            "accessionNumber": ["0000320193-24-000123", "0000320193-24-000100", "0000320193-24-000090", "0000320193-24-000080"],
            "filingDate": ["2024-11-01", "2024-08-01", "2024-07-15", "2024-05-01"],
            "primaryDocument": ["aapl-20240928.htm", "aapl-20240629.htm", "aapl-8k.htm", "aapl-20240330.htm"],
        }
    }
}


class TestSecFiling(unittest.TestCase):
    @patch("tools.sec_filing.requests.get")
    def test_resolve_cik_from_ticker(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = MOCK_TICKERS_JSON
        mock_get.return_value = resp

        cik = _resolve_cik("AAPL")
        self.assertEqual(cik, "0000320193")

    def test_resolve_cik_numeric(self):
        cik = _resolve_cik("320193")
        self.assertEqual(cik, "0000320193")

    @patch("tools.sec_filing.requests.get")
    def test_successful_filing(self, mock_get):
        call_count = [0]

        def side_effect(url, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()

            if "company_tickers.json" in url:
                resp.json.return_value = MOCK_TICKERS_JSON
            elif "submissions" in url:
                resp.json.return_value = MOCK_SUBMISSIONS
            else:
                resp.text = "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\nFORM 10-K\nAnnual Report..."
            return resp

        mock_get.side_effect = side_effect

        result = get_sec_filing("AAPL", "10-K")
        self.assertEqual(result["ticker_or_cik"], "AAPL")
        self.assertEqual(result["form_type"], "10-K")
        self.assertEqual(result["filing_date"], "2024-11-01")
        self.assertIn("content", result)
        self.assertIn("FORM 10-K", result["content"])

    @patch("tools.sec_filing.requests.get")
    def test_ticker_not_found(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {}
        mock_get.return_value = resp

        result = get_sec_filing("ZZZZZZ")
        self.assertIn("error", result)


# ──────────────────────────────────────────────────────────────────
# crypto_price tests
# ──────────────────────────────────────────────────────────────────

MOCK_COINGECKO = {
    "name": "Bitcoin",
    "symbol": "btc",
    "last_updated": "2026-03-01T06:00:00.000Z",
    "market_data": {
        "current_price": {"usd": 85000.0},
        "market_cap": {"usd": 1_670_000_000_000},
        "total_volume": {"usd": 32_000_000_000},
        "price_change_percentage_24h": 2.5,
        "price_change_percentage_7d": -1.2,
        "price_change_percentage_30d": 8.3,
        "ath": {"usd": 109000.0},
        "ath_date": {"usd": "2025-01-20"},
        "circulating_supply": 19_600_000,
        "max_supply": 21_000_000,
        "sparkline_7d": {"price": [83000 + i * 50 for i in range(168)]},
    },
}


class TestCryptoPrice(unittest.TestCase):
    @patch("tools.crypto_price.requests.get")
    def test_successful_price(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = MOCK_COINGECKO
        mock_get.return_value = resp

        result = get_crypto_price("bitcoin")
        self.assertEqual(result["coin_id"], "bitcoin")
        self.assertEqual(result["name"], "Bitcoin")
        self.assertEqual(result["symbol"], "BTC")
        self.assertEqual(result["price_usd"], 85000.0)
        self.assertEqual(result["market_cap_usd"], 1_670_000_000_000)
        self.assertIsNotNone(result["sparkline_7d"])
        self.assertLessEqual(len(result["sparkline_7d"]), 24)
        self.assertIn("timestamp", result)

    @patch("tools.crypto_price.requests.get")
    def test_coin_not_found(self, mock_get):
        resp = MagicMock()
        resp.status_code = 404
        mock_get.return_value = resp

        result = get_crypto_price("fakecoin123")
        self.assertIn("error", result)

    @patch("tools.crypto_price.requests.get")
    def test_rate_limit(self, mock_get):
        resp = MagicMock()
        resp.status_code = 429
        mock_get.return_value = resp

        result = get_crypto_price("bitcoin")
        self.assertIn("error", result)
        self.assertIn("rate limit", result["error"].lower())


# ──────────────────────────────────────────────────────────────────
# Integration: server tool registration
# ──────────────────────────────────────────────────────────────────

class TestServerRegistration(unittest.TestCase):
    def test_all_tools_registered(self):
        """Verify all 5 tools are registered with the MCP server."""
        import asyncio
        from server import mcp
        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        expected = {"stock_quote", "company_fundamentals", "economic_indicator", "sec_filing", "crypto_price"}
        self.assertEqual(tool_names, expected)


if __name__ == "__main__":
    unittest.main()
