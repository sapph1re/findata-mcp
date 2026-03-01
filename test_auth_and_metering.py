"""Tests for auth, x402 payment flow, metering, and API middleware."""

import os
import sys
import sqlite3
import tempfile
import time
import unittest

# Use a temp database for tests
_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB_PATH = _test_db.name
_test_db.close()
os.environ["FINDATA_DB_PATH"] = TEST_DB_PATH

sys.path.insert(0, os.path.dirname(__file__))

from auth import init_db, generate_key, register_key, validate_key, check_rate_limit, TIERS
from metering import init_metering_db, log_call, get_usage_stats


# ──────────────────────────────────────────────────────────────────
# Auth module tests
# ──────────────────────────────────────────────────────────────────

class TestKeyGeneration(unittest.TestCase):
    def test_live_key_format(self):
        key = generate_key(test=False)
        self.assertTrue(key.startswith("fd_live_"))
        self.assertGreater(len(key), 20)

    def test_test_key_format(self):
        key = generate_key(test=True)
        self.assertTrue(key.startswith("fd_test_"))

    def test_keys_are_unique(self):
        keys = {generate_key() for _ in range(100)}
        self.assertEqual(len(keys), 100)


class TestKeyRegistration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_register_free_tier(self):
        result = register_key("test@example.com", "free")
        self.assertIn("api_key", result)
        self.assertEqual(result["tier"], "free")
        self.assertEqual(result["daily_limit"], 100)
        self.assertTrue(result["api_key"].startswith("fd_live_"))

    def test_register_pro_tier(self):
        result = register_key("pro@example.com", "pro")
        self.assertEqual(result["tier"], "pro")
        self.assertEqual(result["daily_limit"], 10_000)

    def test_register_enterprise_tier(self):
        result = register_key("ent@example.com", "enterprise")
        self.assertEqual(result["tier"], "enterprise")
        self.assertEqual(result["daily_limit"], 100_000)

    def test_invalid_tier_raises(self):
        with self.assertRaises(ValueError):
            register_key("bad@example.com", "ultra")


class TestKeyValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.key_info = register_key("validate@example.com", "free")

    def test_valid_key(self):
        result = validate_key(self.key_info["api_key"])
        self.assertIsNotNone(result)
        self.assertEqual(result["tier"], "free")
        self.assertEqual(result["email"], "validate@example.com")

    def test_invalid_key(self):
        result = validate_key("fd_live_nonexistent_key_abc123")
        self.assertIsNone(result)


class TestRateLimiting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_within_limit(self):
        info = register_key("rate@example.com", "free")
        allowed, key_info = check_rate_limit(info["api_key"])
        self.assertTrue(allowed)
        self.assertEqual(key_info["calls_today"], 1)

    def test_exceeds_limit(self):
        info = register_key("limited@example.com", "free")
        key = info["api_key"]
        # Manually set calls_today to the limit
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.execute("UPDATE api_keys SET calls_today = 100 WHERE key = ?", (key,))
        conn.commit()
        conn.close()

        allowed, key_info = check_rate_limit(key)
        self.assertFalse(allowed)
        self.assertEqual(key_info["calls_today"], 100)

    def test_invalid_key_denied(self):
        allowed, key_info = check_rate_limit("fd_live_fake_key_xyz")
        self.assertFalse(allowed)
        self.assertIsNone(key_info)

    def test_counter_increments(self):
        info = register_key("counter@example.com", "free")
        key = info["api_key"]

        for i in range(5):
            allowed, key_info = check_rate_limit(key)
            self.assertTrue(allowed)
            self.assertEqual(key_info["calls_today"], i + 1)


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

    def test_log_with_api_key(self):
        log_call("crypto_price", "api_key:free", api_key="fd_live_test123",
                 response_time_ms=12.0, client_ip="127.0.0.1")
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM metering WHERE api_key = 'fd_live_test123'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["tool_name"], "crypto_price")
        self.assertEqual(row["client_ip"], "127.0.0.1")

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
        log_call("stock_quote", "api_key:free", response_time_ms=20.0)
        log_call("crypto_price", "x402", response_time_ms=30.0)

        stats = get_usage_stats()
        self.assertEqual(stats["total_calls"], 3)
        self.assertEqual(stats["by_tool"]["stock_quote"], 2)
        self.assertEqual(stats["by_tool"]["crypto_price"], 1)
        self.assertEqual(stats["by_payment_method"]["x402"], 2)
        self.assertEqual(stats["avg_response_time_ms"], 20.0)


# ──────────────────────────────────────────────────────────────────
# FastAPI middleware integration tests
# ──────────────────────────────────────────────────────────────────

class TestAPIMiddleware(unittest.TestCase):
    """Integration tests for the FastAPI middleware using TestClient."""

    @classmethod
    def setUpClass(cls):
        # Import after env is set
        from fastapi.testclient import TestClient
        from app import app
        cls.client = TestClient(app)
        # Register a test key
        resp = cls.client.post("/api/v1/register?email=test@test.com&tier=free")
        cls.api_key = resp.json()["api_key"]

    def test_root_no_auth(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["service"], "FinData MCP")

    def test_health_no_auth(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_register_endpoint(self):
        resp = self.client.post("/api/v1/register?email=new@test.com")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("api_key", data)
        self.assertEqual(data["tier"], "free")

    def test_402_without_auth(self):
        """Paid endpoint returns 402 with x402 payment instructions when no auth provided."""
        resp = self.client.get("/api/v1/stock_quote?ticker=AAPL")
        self.assertEqual(resp.status_code, 402)
        data = resp.json()
        self.assertEqual(data["error"], "Payment Required")
        self.assertIn("x402", data)
        self.assertEqual(data["x402"]["accepts"][0]["price"], "$0.01")
        self.assertEqual(data["x402"]["accepts"][0]["scheme"], "exact")
        self.assertIn("facilitator", data["x402"])
        self.assertIn("api_key", data)

    def test_401_invalid_key(self):
        resp = self.client.get(
            "/api/v1/stock_quote?ticker=AAPL",
            headers={"X-API-Key": "fd_live_totally_fake_key"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Invalid API key", resp.json()["error"])

    def test_x402_payment_accepted(self):
        """x402 payment header is accepted in test mode (X402_VERIFY=false)."""
        from unittest.mock import patch
        with patch("app.get_stock_quote") as mock_fn:
            mock_fn.return_value = {"ticker": "AAPL", "price": 185.50}
            # Clear cache to force tool call
            from app import stock_cache
            stock_cache.clear()

            resp = self.client.get(
                "/api/v1/stock_quote?ticker=AAPL",
                headers={"X-PAYMENT": "test-payment-signature-abc123"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["ticker"], "AAPL")

    def test_api_key_auth_works(self):
        """Valid API key grants access to paid endpoints."""
        from unittest.mock import patch
        with patch("app.get_crypto_price") as mock_fn:
            mock_fn.return_value = {"coin_id": "bitcoin", "price_usd": 85000.0}
            from app import crypto_cache
            crypto_cache.clear()

            resp = self.client.get(
                "/api/v1/crypto_price?coin_id=bitcoin",
                headers={"X-API-Key": self.api_key},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["coin_id"], "bitcoin")

    def test_rate_limit_enforced(self):
        """API key rate limiting returns 429 when exceeded."""
        # Create a key and exhaust its limit
        resp = self.client.post("/api/v1/register?email=ratelimit@test.com&tier=free")
        key = resp.json()["api_key"]

        conn = sqlite3.connect(TEST_DB_PATH)
        conn.execute("UPDATE api_keys SET calls_today = 100 WHERE key = ?", (key,))
        conn.commit()
        conn.close()

        resp = self.client.get(
            "/api/v1/stock_quote?ticker=AAPL",
            headers={"X-API-Key": key},
        )
        self.assertEqual(resp.status_code, 429)
        data = resp.json()
        self.assertIn("Rate limit exceeded", data["error"])
        self.assertEqual(data["daily_limit"], 100)

    def test_metering_logs_calls(self):
        """Verify metering table gets populated from middleware."""
        # Clear metering
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
        """All 5 tool endpoints return 402 without auth."""
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
