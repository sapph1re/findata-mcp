"""Metering and call logging for FinData MCP.

Logs every API call with: timestamp, tool_name, payment_method, api_key,
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
    """Create metering table if it doesn't exist."""
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metering (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            api_key TEXT,
            response_time_ms REAL,
            status_code INTEGER DEFAULT 200,
            client_ip TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_call(
    tool_name: str,
    payment_method: str,
    api_key: str | None = None,
    response_time_ms: float | None = None,
    status_code: int = 200,
    client_ip: str | None = None,
) -> None:
    """Log a single API call to the metering table."""
    conn = _get_db()
    conn.execute(
        "INSERT INTO metering (timestamp, tool_name, payment_method, api_key, "
        "response_time_ms, status_code, client_ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            tool_name,
            payment_method,
            api_key,
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
