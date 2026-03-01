"""API key authentication and rate limiting for FinData MCP.

Supports three tiers:
- free:       100 calls/day, no payment required
- pro:        10,000 calls/day, $29/mo
- enterprise: 100,000 calls/day, $199/mo

Key format: fd_live_<random> (production) or fd_test_<random> (test)
"""

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("FINDATA_DB_PATH", os.path.join(os.path.dirname(__file__), "findata.db"))

TIERS = {
    "free": {"daily_limit": 100, "price_monthly": 0},
    "pro": {"daily_limit": 10_000, "price_monthly": 29},
    "enterprise": {"daily_limit": 100_000, "price_monthly": 199},
}


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create api_keys table if it doesn't exist."""
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key TEXT PRIMARY KEY,
            tier TEXT NOT NULL DEFAULT 'free',
            daily_limit INTEGER NOT NULL DEFAULT 100,
            calls_today INTEGER NOT NULL DEFAULT 0,
            reset_at TEXT NOT NULL,
            email TEXT,
            stripe_customer_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def _next_reset() -> str:
    """Return ISO timestamp for midnight UTC tomorrow."""
    tomorrow = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    return tomorrow.isoformat()


def generate_key(test: bool = False) -> str:
    """Generate a new API key."""
    prefix = "fd_test" if test else "fd_live"
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def register_key(email: str, tier: str = "free") -> dict:
    """Register a new API key. Returns key info dict."""
    if tier not in TIERS:
        raise ValueError(f"Invalid tier: {tier}. Must be one of: {', '.join(TIERS)}")

    key = generate_key()
    limit = TIERS[tier]["daily_limit"]

    conn = _get_db()
    conn.execute(
        "INSERT INTO api_keys (key, tier, daily_limit, calls_today, reset_at, email) "
        "VALUES (?, ?, ?, 0, ?, ?)",
        (key, tier, limit, _next_reset(), email),
    )
    conn.commit()
    conn.close()

    return {
        "api_key": key,
        "tier": tier,
        "daily_limit": limit,
        "email": email,
    }


def validate_key(key: str) -> dict | None:
    """Validate an API key. Returns key info dict or None if invalid."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM api_keys WHERE key = ?", (key,)).fetchone()
    if not row:
        conn.close()
        return None

    now = datetime.now(timezone.utc).isoformat()

    # Reset counter if past reset time
    if now >= row["reset_at"]:
        new_reset = _next_reset()
        conn.execute(
            "UPDATE api_keys SET calls_today = 0, reset_at = ? WHERE key = ?",
            (new_reset, key),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM api_keys WHERE key = ?", (key,)).fetchone()

    result = dict(row)
    conn.close()
    return result


def check_rate_limit(key: str) -> tuple[bool, dict | None]:
    """Check rate limit and increment usage if allowed.

    Returns (allowed, key_info). If key is invalid, returns (False, None).
    If rate limited, returns (False, key_info) with limit details.
    """
    info = validate_key(key)
    if info is None:
        return False, None

    if info["calls_today"] >= info["daily_limit"]:
        return False, info

    conn = _get_db()
    conn.execute(
        "UPDATE api_keys SET calls_today = calls_today + 1 WHERE key = ?", (key,)
    )
    conn.commit()
    conn.close()
    info["calls_today"] += 1
    return True, info
