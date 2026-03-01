"""economic_indicator tool — GDP, CPI, unemployment, rates via FRED API."""

import os
import time
from typing import Any

import requests

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


def get_economic_indicator(series_id: str) -> dict[str, Any]:
    """Fetch economic indicator data from FRED."""
    if not FRED_API_KEY:
        return {
            "error": "FRED_API_KEY environment variable not set. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html",
            "series_id": series_id,
        }

    try:
        # Get series metadata
        meta_resp = requests.get(
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

        # Get latest observations (last 12)
        obs_resp = requests.get(
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
    except Exception as e:
        return {"error": str(e), "series_id": series_id}
