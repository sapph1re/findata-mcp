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
        """Paid endpoint returns 402 with x402 payment instructions when no payment."""
        resp = self.client.get("/api/v1/stock_quote?ticker=AAPL")
        self.assertEqual(resp.status_code, 402)
        data = resp.json()
        self.assertEqual(data["error"], "Payment Required")
        self.assertIn("x402", data)
        self.assertEqual(data["x402"]["accepts"][0]["price"], "$0.01")
        self.assertEqual(data["x402"]["accepts"][0]["scheme"], "exact")
        self.assertIn("facilitator", data["x402"])
        # No api_key section anymore
        self.assertNotIn("api_key", data)

    def test_x402_payment_accepted(self):
        """x402 payment header is accepted in test mode (X402_VERIFY=false)."""
        from unittest.mock import patch
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


# ──────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────

def tearDownModule():
    try:
        os.unlink(TEST_DB_PATH)
    except OSError:
        pass


if __name__ == "__main__":
    unittest.main()
