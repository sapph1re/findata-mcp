"""sec_filing tool — 10-K, 10-Q, 8-K full text via SEC EDGAR API."""

import time
from typing import Any

import requests

EDGAR_BASE = "https://efts.sec.gov/LATEST"
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# Required by SEC — they block requests without a proper User-Agent
HEADERS = {
    "User-Agent": "FinDataMCP/0.1.0 (contact@findata-mcp.io)",
    "Accept": "application/json",
}


def _resolve_cik(ticker_or_cik: str) -> str | None:
    """Resolve a ticker symbol to a CIK number, or return CIK if already numeric."""
    if ticker_or_cik.isdigit():
        return ticker_or_cik.zfill(10)

    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        tickers = resp.json()
        for entry in tickers.values():
            if entry.get("ticker", "").upper() == ticker_or_cik.upper():
                return str(entry["cik_str"]).zfill(10)
    except Exception:
        pass
    return None


def _get_filing_url(cik: str, form_type: str) -> dict[str, Any] | None:
    """Find the most recent filing of the given type."""
    try:
        resp = requests.get(
            f"{EDGAR_SUBMISSIONS}/CIK{cik}.json",
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        for i, form in enumerate(forms):
            if form.upper() == form_type.upper():
                accession = accessions[i].replace("-", "")
                return {
                    "accession": accessions[i],
                    "filing_date": dates[i],
                    "primary_document": primary_docs[i],
                    "url": f"{EDGAR_ARCHIVES}/{cik.lstrip('0')}/{accession}/{primary_docs[i]}",
                }
    except Exception:
        pass
    return None


def _fetch_filing_text(url: str, max_chars: int = 50000) -> str:
    """Fetch filing document text, truncated to max_chars."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = resp.text

        # Strip HTML tags for readability if it's HTML
        if "<html" in text.lower()[:500]:
            from html.parser import HTMLParser
            from io import StringIO

            class _Stripper(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.result = StringIO()
                    self.skip = False

                def handle_starttag(self, tag, attrs):
                    if tag in ("script", "style"):
                        self.skip = True

                def handle_endtag(self, tag):
                    if tag in ("script", "style"):
                        self.skip = False

                def handle_data(self, data):
                    if not self.skip:
                        self.result.write(data)

            s = _Stripper()
            s.feed(text)
            text = s.result.getvalue()

        # Clean up excessive whitespace
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(line for line in lines if line)

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[TRUNCATED — full filing is {len(resp.text):,} characters]"

        return text
    except Exception as e:
        return f"Error fetching filing: {str(e)}"


def get_sec_filing(ticker_or_cik: str, form_type: str = "10-K") -> dict[str, Any]:
    """Fetch the most recent SEC filing of the specified type."""
    cik = _resolve_cik(ticker_or_cik)
    if not cik:
        return {
            "error": f"Could not resolve '{ticker_or_cik}' to a CIK number",
            "ticker_or_cik": ticker_or_cik,
        }

    try:
        filing_info = _get_filing_url(cik, form_type)
        if not filing_info:
            return {
                "error": f"No {form_type} filing found for CIK {cik}",
                "ticker_or_cik": ticker_or_cik,
                "form_type": form_type,
            }

        text = _fetch_filing_text(filing_info["url"])

        return {
            "ticker_or_cik": ticker_or_cik,
            "cik": cik,
            "form_type": form_type,
            "filing_date": filing_info["filing_date"],
            "accession_number": filing_info["accession"],
            "document_url": filing_info["url"],
            "content": text,
            "source": "SEC EDGAR",
            "timestamp": int(time.time()),
        }

    except Exception as e:
        return {"error": str(e), "ticker_or_cik": ticker_or_cik, "form_type": form_type}
