"""Metering and call logging for FinData MCP.

Logs every API call with: timestamp, tool_name, payment_method,
response_time_ms, status_code, client_ip.
"""

import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("FINDATA_DB_PATH", os.path.join(os.path.dirname(__file__), "findata.db"))


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_metering_db() -> None:
    """Create metering and replay-protection tables if they don't exist."""
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metering (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            response_time_ms REAL,
            status_code INTEGER DEFAULT 200,
            client_ip TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS used_signatures (
            signature_hash TEXT PRIMARY KEY,
            payer TEXT NOT NULL,
            used_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def is_signature_used(signature_hash: str) -> bool:
    """Check if a payment signature has already been used."""
    conn = _get_db()
    row = conn.execute(
        "SELECT 1 FROM used_signatures WHERE signature_hash = ?",
        (signature_hash,),
    ).fetchone()
    conn.close()
    return row is not None


def record_signature(signature_hash: str, payer: str, expires_at: str) -> None:
    """Record a payment signature as used."""
    conn = _get_db()
    conn.execute(
        "INSERT OR IGNORE INTO used_signatures (signature_hash, payer, used_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (signature_hash, payer, datetime.now(timezone.utc).isoformat(), expires_at),
    )
    conn.commit()
    conn.close()


def try_claim_signature(signature_hash: str, expires_at: str) -> bool:
    """Atomically claim a signature. Returns True if newly claimed, False if already used.

    Uses INSERT OR IGNORE + cursor.rowcount so that two concurrent workers racing on
    the same signature will have exactly one succeed (rowcount=1) and the other see
    rowcount=0 (the IGNORE fired because the PRIMARY KEY already existed).
    """
    conn = _get_db()
    conn.execute("PRAGMA busy_timeout = 5000")
    cur = conn.execute(
        "INSERT OR IGNORE INTO used_signatures (signature_hash, payer, used_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (signature_hash, "pending", datetime.now(timezone.utc).isoformat(), expires_at),
    )
    row_added = cur.rowcount > 0
    conn.commit()
    conn.close()
    return row_added


def purge_expired_signatures() -> None:
    """Remove expired signatures to prevent unbounded table growth."""
    conn = _get_db()
    conn.execute(
        "DELETE FROM used_signatures WHERE expires_at < ?",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    conn.close()


def log_call(
    tool_name: str,
    payment_method: str,
    response_time_ms: float | None = None,
    status_code: int = 200,
    client_ip: str | None = None,
) -> None:
    """Log a single API call to the metering table."""
    conn = _get_db()
    conn.execute(
        "INSERT INTO metering (timestamp, tool_name, payment_method, "
        "response_time_ms, status_code, client_ip) VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            tool_name,
            payment_method,
            response_time_ms,
            status_code,
            client_ip,
        ),
    )
    conn.commit()
    conn.close()


def get_usage_stats(since: str | None = None) -> dict:
    """Get aggregate usage stats, optionally filtered by date."""
    conn = _get_db()
    where = ""
    params: tuple = ()
    if since:
        where = "WHERE timestamp >= ?"
        params = (since,)

    total = conn.execute(f"SELECT COUNT(*) FROM metering {where}", params).fetchone()[0]
    by_tool = conn.execute(
        f"SELECT tool_name, COUNT(*) as count FROM metering {where} GROUP BY tool_name",
        params,
    ).fetchall()
    by_method = conn.execute(
        f"SELECT payment_method, COUNT(*) as count FROM metering {where} GROUP BY payment_method",
        params,
    ).fetchall()
    avg_response = conn.execute(
        f"SELECT AVG(response_time_ms) FROM metering {where} AND response_time_ms IS NOT NULL"
        if where
        else "SELECT AVG(response_time_ms) FROM metering WHERE response_time_ms IS NOT NULL",
        params,
    ).fetchone()[0]

    conn.close()
    return {
        "total_calls": total,
        "by_tool": {row["tool_name"]: row["count"] for row in by_tool},
        "by_payment_method": {row["payment_method"]: row["count"] for row in by_method},
        "avg_response_time_ms": round(avg_response, 2) if avg_response else None,
    }
