"""economic_indicator tool — GDP, CPI, unemployment, rates via FRED API."""

import os
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# Common series IDs for documentation
COMMON_SERIES = {
    "GDP": "Gross Domestic Product",
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
    "UNRATE": "Unemployment Rate",
    "FEDFUNDS": "Federal Funds Effective Rate",
    "DGS10": "10-Year Treasury Constant Maturity Rate",
    "DGS2": "2-Year Treasury Constant Maturity Rate",
    "T10Y2Y": "10-Year Treasury Minus 2-Year Treasury (Yield Curve Spread)",
    "MORTGAGE30US": "30-Year Fixed Rate Mortgage Average",
    "VIXCLS": "CBOE Volatility Index (VIX)",
    "M2SL": "M2 Money Supply",
}

# Map friendly aliases to FRED series IDs
INDICATOR_ALIASES: dict[str, str] = {
    "CPI": "CPIAUCSL",
    "INFLATION": "CPIAUCSL",
    "UNEMPLOYMENT": "UNRATE",
    "JOBS": "UNRATE",
    "INTEREST_RATE": "FEDFUNDS",
    "FED_RATE": "FEDFUNDS",
    "FED_FUNDS": "FEDFUNDS",
    "TREASURY_10Y": "DGS10",
    "TREASURY_2Y": "DGS2",
    "YIELD_CURVE": "T10Y2Y",
    "MORTGAGE": "MORTGAGE30US",
    "VIX": "VIXCLS",
    "MONEY_SUPPLY": "M2SL",
    "M2": "M2SL",
}


def _fred_session() -> requests.Session:
    """Create a requests session with retry logic for transient FRED failures."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,  # 0s, 0.5s, 1s between retries
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


_session = _fred_session()


def resolve_series_id(raw: str) -> str:
    """Resolve a friendly alias to a FRED series ID, or pass through."""
    normalized = raw.strip().upper()
    return INDICATOR_ALIASES.get(normalized, normalized)


def get_economic_indicator(series_id: str) -> dict[str, Any]:
    """Fetch economic indicator data from FRED."""
    if not FRED_API_KEY:
        return {
            "error": "FRED_API_KEY environment variable not set. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html",
            "series_id": series_id,
        }

    try:
        # Get series metadata (retries on 5xx via session adapter)
        meta_resp = _session.get(
            f"{FRED_BASE_URL}/series",
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
            },
            timeout=15,
        )
        meta_resp.raise_for_status()
        meta = meta_resp.json()

        if "seriess" not in meta or not meta["seriess"]:
            return {"error": f"Series '{series_id}' not found", "series_id": series_id}

        series_meta = meta["seriess"][0]

        # Get latest observations (last 12, retries on 5xx)
        obs_resp = _session.get(
            f"{FRED_BASE_URL}/series/observations",
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 12,
            },
            timeout=15,
        )
        obs_resp.raise_for_status()
        obs_data = obs_resp.json()

        observations = []
        for obs in obs_data.get("observations", []):
            val = obs.get("value", ".")
            observations.append({
                "date": obs.get("date"),
                "value": float(val) if val != "." else None,
            })

        # Latest value
        latest = observations[0] if observations else None

        return {
            "series_id": series_id,
            "title": series_meta.get("title"),
            "units": series_meta.get("units"),
            "frequency": series_meta.get("frequency"),
            "seasonal_adjustment": series_meta.get("seasonal_adjustment"),
            "latest_value": latest["value"] if latest else None,
            "latest_date": latest["date"] if latest else None,
            "observations": observations,
            "source": "Federal Reserve Economic Data (FRED)",
            "timestamp": int(time.time()),
        }

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            return {
                "error": "FRED rate limit exceeded (120 req/min). Try again shortly.",
                "series_id": series_id,
            }
        return {"error": f"FRED API error: {str(e)}", "series_id": series_id}
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        return {
            "error": "FRED API temporarily unavailable (retries exhausted). Try again shortly.",
            "series_id": series_id,
        }
    except Exception as e:
        return {"error": str(e), "series_id": series_id}
