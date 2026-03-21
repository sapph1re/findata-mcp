"""Tests for the thin MCP adapter client."""

import base64
import json
import os
import unittest
from unittest.mock import MagicMock, patch

import requests

from findata_mcp.client import FinDataClient


class TestFinDataClientNoKey(unittest.TestCase):
    """Test client behavior without a wallet key."""

    def setUp(self):
        self.client = FinDataClient(
            backend_url="https://findata-mcp-production-1cd3.up.railway.app",
            private_key="",
        )

    @patch("findata_mcp.client.requests.Session")
    def test_successful_call(self, mock_session_cls):
        """Tool call succeeds when backend returns 200."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ticker": "AAPL", "price": 150.0}
        mock_session.get.return_value = mock_resp
        self.client._session = mock_session

        result = self.client.call("stock_quote", ticker="AAPL")

        self.assertEqual(result["ticker"], "AAPL")
        mock_session.get.assert_called_once_with(
            "https://findata-mcp-production-1cd3.up.railway.app/api/v1/stock_quote",
            params={"ticker": "AAPL"},
            timeout=30,
        )

    @patch("findata_mcp.client.requests.Session")
    def test_402_without_key(self, mock_session_cls):
        """402 response without wallet key returns clear error."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_session.get.return_value = mock_resp
        self.client._session = mock_session

        result = self.client.call("stock_quote", ticker="AAPL")

        self.assertIn("error", result)
        self.assertIn("EVM_PRIVATE_KEY", result["error"])

    @patch("findata_mcp.client.requests.Session")
    def test_backend_error(self, mock_session_cls):
        """Non-402 error returns error dict."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_session.get.return_value = mock_resp
        self.client._session = mock_session

        result = self.client.call("stock_quote", ticker="AAPL")

        self.assertIn("error", result)
        self.assertIn("500", result["error"])

    def test_url_construction(self):
        """Backend URL is properly joined with tool name."""
        client = FinDataClient(
            backend_url="https://example.com/",  # trailing slash
            private_key="",
        )
        self.assertEqual(client.backend_url, "https://example.com")


class TestFinDataClientErrorHandling(unittest.TestCase):
    """Test error handling for connection errors and invalid keys."""

    @patch("findata_mcp.client.requests.Session")
    def test_connection_error_returns_dict(self, mock_session_cls):
        """ConnectionError in call() returns error dict instead of raising."""
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.ConnectionError("Connection refused")
        client = FinDataClient(backend_url="https://example.com", private_key="")
        client._session = mock_session

        result = client.call("stock_quote", ticker="AAPL")

        self.assertIn("error", result)
        self.assertIn("Cannot reach backend", result["error"])

    @patch("findata_mcp.client.requests.Session")
    def test_invalid_private_key_returns_dict(self, mock_session_cls):
        """Invalid private key during 402 handling returns error dict."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.headers = {"payment-required": "dGVzdA=="}
        mock_session.get.return_value = mock_resp

        client = FinDataClient(backend_url="https://example.com", private_key="0xdeadbeef")
        client._session = mock_session

        # Mock _get_x402_client to raise PaymentError (as it would with invalid key)
        from findata_mcp.client import PaymentError
        with patch.object(client, '_get_x402_client', side_effect=PaymentError("Invalid wallet key: bad key")):
            result = client.call("stock_quote", ticker="AAPL")

        self.assertIn("error", result)
        self.assertIn("Invalid wallet key", result["error"])

    @patch("findata_mcp.client.requests.Session")
    def test_timeout_error_returns_dict(self, mock_session_cls):
        """Timeout in call() returns error dict instead of raising."""
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.Timeout("Request timed out")
        client = FinDataClient(backend_url="https://example.com", private_key="")
        client._session = mock_session

        result = client.call("stock_quote", ticker="AAPL")

        self.assertIn("error", result)
        self.assertIn("Request failed", result["error"])


class TestFinDataClientWithKey(unittest.TestCase):
    """Test client behavior with a wallet key (mocked x402)."""

    @patch("findata_mcp.client.requests.Session")
    def test_402_with_key_creates_payment(self, mock_session_cls):
        """402 response with wallet key attempts x402 payment and retries."""
        # Create a fake payment required header
        payment_required = {
            "x402Version": 2,
            "accepts": [{
                "scheme": "exact",
                "network": "eip155:8453",
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "amount": "10000",
                "payTo": "0x1234567890123456789012345678901234567890",
                "maxTimeoutSeconds": 300,
                "extra": {"name": "USD Coin", "version": "2"},
            }],
            "resource": {"url": "/api/v1/stock_quote"},
            "error": "Payment required",
        }
        pr_b64 = base64.b64encode(json.dumps(payment_required).encode()).decode()

        mock_session = MagicMock()

        # First call returns 402
        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {"payment-required": pr_b64}

        # Second call (with payment) returns 200
        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.json.return_value = {"ticker": "AAPL", "price": 150.0}

        mock_session.get.side_effect = [mock_resp_402, mock_resp_200]

        # Mock the x402 client
        mock_x402 = MagicMock()
        mock_payload = MagicMock()
        mock_payload.model_dump_json.return_value = '{"payload": "signed"}'
        mock_x402.create_payment_payload.return_value = mock_payload

        client = FinDataClient(
            backend_url="https://example.com",
            private_key="0x" + "ab" * 32,  # fake key
        )
        client._session = mock_session
        client._x402_client = mock_x402  # skip real init

        result = client.call("stock_quote", ticker="AAPL")

        self.assertEqual(result["ticker"], "AAPL")
        self.assertEqual(mock_session.get.call_count, 2)
        # Verify the retry included Payment-Signature header
        retry_call = mock_session.get.call_args_list[1]
        self.assertIn("Payment-Signature", retry_call.kwargs.get("headers", {}))


class TestMCPServerToolDefinitions(unittest.TestCase):
    """Verify the thin MCP server registers all 5 tools."""

    def test_all_tools_registered(self):
        import asyncio
        from findata_mcp.server import mcp

        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}

        expected = {"stock_quote", "company_fundamentals", "economic_indicator", "sec_filing", "crypto_price"}
        self.assertEqual(tool_names, expected)

    def test_version(self):
        from findata_mcp.server import mcp
        self.assertEqual(mcp.version, "0.3.0")


class TestParamAliases(unittest.TestCase):
    """Verify MCP tools accept common parameter aliases (Task 196)."""

    @patch("findata_mcp.client.requests.Session")
    def test_stock_quote_symbol_alias(self, mock_session_cls):
        """stock_quote(symbol='AAPL') works like stock_quote(ticker='AAPL')."""
        from findata_mcp.server import stock_quote, _get_client

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ticker": "AAPL", "price": 150.0}
        mock_session.get.return_value = mock_resp

        client = FinDataClient(backend_url="https://example.com", private_key="")
        client._session = mock_session

        with patch("findata_mcp.server._get_client", return_value=client):
            result = stock_quote(symbol="AAPL")

        self.assertEqual(result["ticker"], "AAPL")
        mock_session.get.assert_called_once_with(
            "https://example.com/api/v1/stock_quote",
            params={"ticker": "AAPL"},
            timeout=30,
        )

    @patch("findata_mcp.client.requests.Session")
    def test_company_fundamentals_symbol_alias(self, mock_session_cls):
        """company_fundamentals(symbol='MSFT') works."""
        from findata_mcp.server import company_fundamentals

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ticker": "MSFT", "pe_ratio": 30.0}
        mock_session.get.return_value = mock_resp

        client = FinDataClient(backend_url="https://example.com", private_key="")
        client._session = mock_session

        with patch("findata_mcp.server._get_client", return_value=client):
            result = company_fundamentals(symbol="MSFT")

        self.assertEqual(result["ticker"], "MSFT")

    @patch("findata_mcp.client.requests.Session")
    def test_crypto_price_symbol_alias(self, mock_session_cls):
        """crypto_price(symbol='bitcoin') works like crypto_price(coin_id='bitcoin')."""
        from findata_mcp.server import crypto_price

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "bitcoin", "price": 65000}
        mock_session.get.return_value = mock_resp

        client = FinDataClient(backend_url="https://example.com", private_key="")
        client._session = mock_session

        with patch("findata_mcp.server._get_client", return_value=client):
            result = crypto_price(symbol="bitcoin")

        self.assertEqual(result["id"], "bitcoin")
        mock_session.get.assert_called_once_with(
            "https://example.com/api/v1/crypto_price",
            params={"coin_id": "bitcoin"},
            timeout=30,
        )

    @patch("findata_mcp.client.requests.Session")
    def test_crypto_price_coin_alias(self, mock_session_cls):
        """crypto_price(coin='ethereum') works."""
        from findata_mcp.server import crypto_price

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "ethereum", "price": 3500}
        mock_session.get.return_value = mock_resp

        client = FinDataClient(backend_url="https://example.com", private_key="")
        client._session = mock_session

        with patch("findata_mcp.server._get_client", return_value=client):
            result = crypto_price(coin="ethereum")

        self.assertEqual(result["id"], "ethereum")

    @patch("findata_mcp.client.requests.Session")
    def test_economic_indicator_alias(self, mock_session_cls):
        """economic_indicator(indicator='GDP') works like economic_indicator(series_id='GDP')."""
        from findata_mcp.server import economic_indicator

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"series_id": "GDP", "value": 28000}
        mock_session.get.return_value = mock_resp

        client = FinDataClient(backend_url="https://example.com", private_key="")
        client._session = mock_session

        with patch("findata_mcp.server._get_client", return_value=client):
            result = economic_indicator(indicator="GDP")

        self.assertEqual(result["series_id"], "GDP")
        mock_session.get.assert_called_once_with(
            "https://example.com/api/v1/economic_indicator",
            params={"series_id": "GDP"},
            timeout=30,
        )

    @patch("findata_mcp.client.requests.Session")
    def test_sec_filing_symbol_alias(self, mock_session_cls):
        """sec_filing(symbol='AAPL') works like sec_filing(ticker_or_cik='AAPL')."""
        from findata_mcp.server import sec_filing

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ticker": "AAPL", "form": "10-K"}
        mock_session.get.return_value = mock_resp

        client = FinDataClient(backend_url="https://example.com", private_key="")
        client._session = mock_session

        with patch("findata_mcp.server._get_client", return_value=client):
            result = sec_filing(symbol="AAPL")

        self.assertEqual(result["ticker"], "AAPL")

    @patch("findata_mcp.client.requests.Session")
    def test_sec_filing_ticker_alias(self, mock_session_cls):
        """sec_filing(ticker='AAPL') works."""
        from findata_mcp.server import sec_filing

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ticker": "AAPL", "form": "10-Q"}
        mock_session.get.return_value = mock_resp

        client = FinDataClient(backend_url="https://example.com", private_key="")
        client._session = mock_session

        with patch("findata_mcp.server._get_client", return_value=client):
            result = sec_filing(ticker="AAPL", form_type="10-Q")

        self.assertEqual(result["ticker"], "AAPL")

    def test_stock_quote_missing_param(self):
        """stock_quote with no params returns helpful error."""
        from findata_mcp.server import stock_quote
        result = stock_quote()
        self.assertIn("error", result)
        self.assertIn("ticker", result["error"])

    def test_crypto_price_missing_param(self):
        """crypto_price with no params returns helpful error."""
        from findata_mcp.server import crypto_price
        result = crypto_price()
        self.assertIn("error", result)
        self.assertIn("coin_id", result["error"])

    def test_economic_indicator_missing_param(self):
        """economic_indicator with no params returns helpful error."""
        from findata_mcp.server import economic_indicator
        result = economic_indicator()
        self.assertIn("error", result)
        self.assertIn("series_id", result["error"])

    def test_canonical_param_takes_precedence(self):
        """When both ticker and symbol are provided, ticker wins."""
        from findata_mcp.server import stock_quote

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ticker": "AAPL", "price": 150}
        mock_session.get.return_value = mock_resp

        client = FinDataClient(backend_url="https://example.com", private_key="")
        client._session = mock_session

        with patch("findata_mcp.server._get_client", return_value=client):
            result = stock_quote(ticker="AAPL", symbol="MSFT")

        # ticker takes precedence
        mock_session.get.assert_called_once_with(
            "https://example.com/api/v1/stock_quote",
            params={"ticker": "AAPL"},
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
