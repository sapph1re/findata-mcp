"""Tests for x402 payment flow, metering, and API middleware."""

import os
import sys
import sqlite3
import tempfile
import unittest

# Use a temp database for tests
_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB_PATH = _test_db.name
_test_db.close()
os.environ["FINDATA_DB_PATH"] = TEST_DB_PATH

sys.path.insert(0, os.path.dirname(__file__))

from metering import init_metering_db, log_call, get_usage_stats


# ──────────────────────────────────────────────────────────────────
# Metering tests
# ──────────────────────────────────────────────────────────────────

class TestMetering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_metering_db()

    def test_log_call(self):
        log_call("stock_quote", "x402", response_time_ms=45.2, status_code=200)
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM metering WHERE tool_name = 'stock_quote' ORDER BY id DESC LIMIT 1"
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payment_method"], "x402")
        self.assertAlmostEqual(rows[0]["response_time_ms"], 45.2, places=1)

    def test_log_with_client_ip(self):
        log_call("crypto_price", "x402",
                 response_time_ms=12.0, client_ip="127.0.0.1")
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM metering WHERE client_ip = '127.0.0.1' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["tool_name"], "crypto_price")
        self.assertEqual(row["payment_method"], "x402")

    def test_log_rejected_call(self):
        log_call("sec_filing", "none", status_code=402)
        conn = sqlite3.connect(TEST_DB_PATH)
        row = conn.execute(
            "SELECT status_code FROM metering WHERE payment_method = 'none' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 402)

    def test_usage_stats(self):
        # Clear and add known data
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.execute("DELETE FROM metering")
        conn.commit()
        conn.close()

        log_call("stock_quote", "x402", response_time_ms=10.0)
        log_call("stock_quote", "x402", response_time_ms=20.0)
        log_call("crypto_price", "x402", response_time_ms=30.0)

        stats = get_usage_stats()
        self.assertEqual(stats["total_calls"], 3)
        self.assertEqual(stats["by_tool"]["stock_quote"], 2)
        self.assertEqual(stats["by_tool"]["crypto_price"], 1)
        self.assertEqual(stats["by_payment_method"]["x402"], 3)
        self.assertEqual(stats["avg_response_time_ms"], 20.0)


# ──────────────────────────────────────────────────────────────────
# FastAPI middleware integration tests
# ──────────────────────────────────────────────────────────────────

class TestAPIMiddleware(unittest.TestCase):
    """Integration tests for the FastAPI middleware using TestClient."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app import app
        cls.client = TestClient(app)

    def test_root_no_auth(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["service"], "FinData MCP")
        self.assertIn("pricing", data)
        self.assertEqual(data["pricing"]["price"], "$0.01 USDC per call")

    def test_health_no_auth(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_402_without_payment(self):
        """Paid endpoint returns 402 with x402 v2 payment instructions when no payment."""
        resp = self.client.get("/api/v1/stock_quote?ticker=AAPL")
        self.assertEqual(resp.status_code, 402)
        data = resp.json()
        self.assertEqual(data["x402Version"], 2)
        self.assertEqual(data["error"], "Payment required")
        accepts = data["accepts"]
        self.assertEqual(len(accepts), 1)
        self.assertEqual(accepts[0]["scheme"], "exact")
        self.assertEqual(accepts[0]["amount"], "10000")
        self.assertIn("asset", accepts[0])
        self.assertIn("payTo", accepts[0])
        self.assertIn("maxTimeoutSeconds", accepts[0])
        self.assertIn("resource", data)
        # No api_key section anymore
        self.assertNotIn("api_key", data)

    def test_x402_payment_accepted_v1_header(self):
        """x402 v1 X-PAYMENT header is accepted when X402_VERIFY=false."""
        from unittest.mock import patch
        import app as app_mod
        original = app_mod.X402_VERIFY
        app_mod.X402_VERIFY = False
        try:
            with patch("app.get_stock_quote") as mock_fn:
                mock_fn.return_value = {"ticker": "AAPL", "price": 185.50}
                from app import stock_cache
                stock_cache.clear()

                resp = self.client.get(
                    "/api/v1/stock_quote?ticker=AAPL",
                    headers={"X-PAYMENT": "test-payment-signature-abc123"},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["ticker"], "AAPL")
        finally:
            app_mod.X402_VERIFY = original

    def test_x402_payment_accepted_v2_header(self):
        """x402 v2 PAYMENT-SIGNATURE header is accepted when X402_VERIFY=false."""
        from unittest.mock import patch
        import app as app_mod
        original = app_mod.X402_VERIFY
        app_mod.X402_VERIFY = False
        try:
            with patch("app.get_stock_quote") as mock_fn:
                mock_fn.return_value = {"ticker": "MSFT", "price": 420.00}
                from app import stock_cache
                stock_cache.clear()

                resp = self.client.get(
                    "/api/v1/stock_quote?ticker=MSFT",
                    headers={"PAYMENT-SIGNATURE": "test-payment-v2-sig"},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["ticker"], "MSFT")
        finally:
            app_mod.X402_VERIFY = original

    def test_metering_logs_calls(self):
        """Verify metering table gets populated from middleware."""
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.execute("DELETE FROM metering")
        conn.commit()
        conn.close()

        # Make a 402 call
        self.client.get("/api/v1/stock_quote?ticker=AAPL")

        conn = sqlite3.connect(TEST_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM metering").fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)
        self.assertEqual(rows[0]["tool_name"], "stock_quote")
        self.assertEqual(rows[0]["status_code"], 402)

    def test_stats_endpoint(self):
        resp = self.client.get("/api/v1/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("total_calls", data)
        self.assertIn("by_tool", data)

    def test_all_paid_routes_return_402(self):
        """All 5 tool endpoints return 402 without payment."""
        routes = [
            "/api/v1/stock_quote?ticker=AAPL",
            "/api/v1/company_fundamentals?ticker=AAPL",
            "/api/v1/economic_indicator?series_id=GDP",
            "/api/v1/sec_filing?ticker_or_cik=AAPL",
            "/api/v1/crypto_price?coin_id=bitcoin",
        ]
        for route in routes:
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 402, f"Expected 402 for {route}, got {resp.status_code}")

    def test_no_register_endpoint(self):
        """Verify /register endpoint has been removed."""
        resp = self.client.post("/api/v1/register?email=test@test.com")
        self.assertIn(resp.status_code, [404, 405])

    def test_api_key_header_ignored(self):
        """API key headers should not grant access — only x402 works."""
        resp = self.client.get(
            "/api/v1/stock_quote?ticker=AAPL",
            headers={"X-API-Key": "fd_live_some_key_here"},
        )
        self.assertEqual(resp.status_code, 402)

    # ── Parameter alias tests (Task 90) ──

    def test_economic_indicator_alias(self):
        """economic_indicator accepts ?indicator= as alias for ?series_id=."""
        resp = self.client.get("/api/v1/economic_indicator?indicator=GDP")
        self.assertEqual(resp.status_code, 402)
        # Confirm it didn't 422 — the alias was accepted
        self.assertIn("x402Version", resp.json())

    def test_sec_filing_alias(self):
        """sec_filing accepts ?ticker= as alias for ?ticker_or_cik=."""
        resp = self.client.get("/api/v1/sec_filing?ticker=TSLA")
        self.assertEqual(resp.status_code, 402)
        self.assertIn("x402Version", resp.json())

    def test_crypto_price_alias(self):
        """crypto_price accepts ?symbol= as alias for ?coin_id=."""
        resp = self.client.get("/api/v1/crypto_price?symbol=BTC")
        self.assertEqual(resp.status_code, 402)
        self.assertIn("x402Version", resp.json())

    def test_economic_indicator_no_params(self):
        """economic_indicator with no params returns 402 (payment gate comes first)."""
        resp = self.client.get("/api/v1/economic_indicator")
        self.assertEqual(resp.status_code, 402)

    def test_sec_filing_no_params(self):
        """sec_filing with no params returns 402 (payment gate comes first)."""
        resp = self.client.get("/api/v1/sec_filing")
        self.assertEqual(resp.status_code, 402)

    def test_crypto_price_no_params(self):
        """crypto_price with no params returns 402 (payment gate comes first)."""
        resp = self.client.get("/api/v1/crypto_price")
        self.assertEqual(resp.status_code, 402)

    # ── Signature verification tests (Task 91) ──

    def test_garbage_payment_header_rejected(self):
        """Garbage payment header is rejected when X402_VERIFY=true."""
        import app as app_mod
        original = app_mod.X402_VERIFY
        app_mod.X402_VERIFY = True
        try:
            resp = self.client.get(
                "/api/v1/stock_quote?ticker=AAPL",
                headers={"X-PAYMENT": "garbage-not-a-real-signature"},
            )
            self.assertIn(resp.status_code, [402, 500])
            self.assertNotEqual(resp.status_code, 200)
        finally:
            app_mod.X402_VERIFY = original

    def test_garbage_v2_header_rejected(self):
        """Garbage PAYMENT-SIGNATURE header is rejected when X402_VERIFY=true."""
        import app as app_mod
        original = app_mod.X402_VERIFY
        app_mod.X402_VERIFY = True
        try:
            resp = self.client.get(
                "/api/v1/stock_quote?ticker=AAPL",
                headers={"PAYMENT-SIGNATURE": "not-valid-base64-or-json"},
            )
            self.assertIn(resp.status_code, [402, 500])
            self.assertNotEqual(resp.status_code, 200)
        finally:
            app_mod.X402_VERIFY = original

    def test_verify_false_accepts_any_header(self):
        """When X402_VERIFY=false, any payment header is accepted (dev mode)."""
        from unittest.mock import patch
        import app as app_mod
        original = app_mod.X402_VERIFY
        app_mod.X402_VERIFY = False
        try:
            with patch("app.get_stock_quote") as mock_fn:
                mock_fn.return_value = {"ticker": "AAPL", "price": 185.50}
                from app import stock_cache
                stock_cache.clear()
                resp = self.client.get(
                    "/api/v1/stock_quote?ticker=AAPL",
                    headers={"X-PAYMENT": "any-garbage-header"},
                )
                self.assertEqual(resp.status_code, 200)
        finally:
            app_mod.X402_VERIFY = original

    # ── PAYMENT-RESPONSE header tests (Task 99) ──

    def test_payment_response_header_present_on_200(self):
        """Successful paid response includes PAYMENT-RESPONSE header (x402 v2)."""
        from unittest.mock import patch
        import app as app_mod
        original = app_mod.X402_VERIFY
        app_mod.X402_VERIFY = False
        try:
            with patch("app.get_stock_quote") as mock_fn:
                mock_fn.return_value = {"ticker": "AAPL", "price": 185.50}
                from app import stock_cache
                stock_cache.clear()
                resp = self.client.get(
                    "/api/v1/stock_quote?ticker=AAPL",
                    headers={"PAYMENT-SIGNATURE": "test-sig"},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertIn("payment-response", resp.headers)
                import base64, json
                decoded = json.loads(base64.b64decode(resp.headers["payment-response"]))
                self.assertEqual(decoded["x402Version"], 2)
                self.assertEqual(decoded["scheme"], "exact")
                self.assertIn("network", decoded)
                self.assertIn("payTo", decoded)
                self.assertIn("payer", decoded)
        finally:
            app_mod.X402_VERIFY = original

    def test_payment_response_header_absent_on_402(self):
        """402 responses should NOT include PAYMENT-RESPONSE header."""
        resp = self.client.get("/api/v1/stock_quote?ticker=AAPL")
        self.assertEqual(resp.status_code, 402)
        self.assertNotIn("payment-response", resp.headers)

    def test_payment_response_header_valid_base64_json(self):
        """PAYMENT-RESPONSE header value is valid base64-encoded JSON."""
        from unittest.mock import patch
        import app as app_mod
        original = app_mod.X402_VERIFY
        app_mod.X402_VERIFY = False
        try:
            with patch("app.get_crypto_price") as mock_fn:
                mock_fn.return_value = {"coin": "bitcoin", "price": 95000}
                from app import crypto_cache
                crypto_cache.clear()
                resp = self.client.get(
                    "/api/v1/crypto_price?coin_id=bitcoin",
                    headers={"X-PAYMENT": "test-pay"},
                )
                self.assertEqual(resp.status_code, 200)
                import base64, json
                raw = resp.headers["payment-response"]
                decoded = base64.b64decode(raw)
                data = json.loads(decoded)
                self.assertIsInstance(data, dict)
                self.assertEqual(data["amount"], app_mod.X402_AMOUNT)
        finally:
            app_mod.X402_VERIFY = original

    def test_402_includes_eip712_domain(self):
        """402 response includes EIP-712 domain params (name, version) in extra."""
        resp = self.client.get("/api/v1/stock_quote?ticker=AAPL")
        self.assertEqual(resp.status_code, 402)
        data = resp.json()
        accepts = data["accepts"][0]
        self.assertIn("extra", accepts)
        self.assertEqual(accepts["extra"]["name"], "USD Coin")
        self.assertEqual(accepts["extra"]["version"], "2")


# ──────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────

class TestSymbolResolution(unittest.TestCase):
    """Tests for crypto_price symbol → CoinGecko ID resolution."""

    def test_known_symbols_resolve(self):
        from tools.crypto_price import resolve_coin_id
        self.assertEqual(resolve_coin_id("BTC"), "bitcoin")
        self.assertEqual(resolve_coin_id("ETH"), "ethereum")
        self.assertEqual(resolve_coin_id("SOL"), "solana")
        self.assertEqual(resolve_coin_id("Doge"), "dogecoin")

    def test_coingecko_ids_pass_through(self):
        from tools.crypto_price import resolve_coin_id
        self.assertEqual(resolve_coin_id("bitcoin"), "bitcoin")
        self.assertEqual(resolve_coin_id("ethereum"), "ethereum")

    def test_unknown_symbol_passes_through(self):
        from tools.crypto_price import resolve_coin_id
        self.assertEqual(resolve_coin_id("notacoin"), "notacoin")

    def test_whitespace_handled(self):
        from tools.crypto_price import resolve_coin_id
        self.assertEqual(resolve_coin_id("  BTC  "), "bitcoin")


def tearDownModule():
    try:
        os.unlink(TEST_DB_PATH)
    except OSError:
        pass


if __name__ == "__main__":
    unittest.main()
