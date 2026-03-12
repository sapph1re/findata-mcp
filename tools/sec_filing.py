"""sec_filing tool — 10-K, 10-Q, 8-K full text via SEC EDGAR API."""

import re
import time
from html.parser import HTMLParser
from io import StringIO
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


class _FilingStripper(HTMLParser):
    """HTML/XBRL-aware stripper that removes noise from SEC filings."""

    # Tags whose entire content (including nested tags) should be skipped
    SKIP_TAGS = frozenset({
        "script", "style", "head",
        # XBRL metadata blocks — pure noise (context definitions, unit defs, hidden facts)
        "ix:header", "ix:hidden", "ix:references",
    })

    # Block-level tags that should insert a newline when opened
    BLOCK_TAGS = frozenset({
        "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
        "table", "section", "article", "header", "footer",
    })

    def __init__(self):
        super().__init__()
        self.result = StringIO()
        self._skip_depth = 0  # nesting depth inside skip tags

    def _tag_name(self, tag: str) -> str:
        """Normalize tag name (handles ix:nonFraction → ix:nonfraction already by HTMLParser)."""
        return tag.lower()

    def handle_starttag(self, tag, attrs):
        t = self._tag_name(tag)
        if t in self.SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and t in self.BLOCK_TAGS:
            self.result.write("\n")

    def handle_endtag(self, tag):
        t = self._tag_name(tag)
        if t in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self.result.write(data)


def _clean_text(raw: str) -> str:
    """Post-process stripped text to remove residual XBRL/filing noise."""
    # Remove leftover XBRL namespace declarations and attributes that leak through
    text = re.sub(r'xmlns(?::\w+)?="[^"]*"', "", raw)

    # Collapse runs of whitespace on the same line (tabs, multiple spaces)
    text = re.sub(r"[ \t]+", " ", text)

    # Strip each line, drop empties, then collapse 3+ consecutive blank lines to 2
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove lines that are just page numbers or section-divider noise
    # e.g. "- 42 -", "Page 42", "F-12", "Table of Contents"  (repeated nav links)
    text = re.sub(
        r"^(?:[-–—\s]*\d+[-–—\s]*|Page\s+\d+|F-\d+|Table of Contents)$",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Remove lines that are only dashes/underscores (visual separators)
    text = re.sub(r"^[_\-=]{3,}$", "", text, flags=re.MULTILINE)

    # Final pass: collapse blank lines again after removals
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _fetch_filing_text(url: str, max_chars: int = 10000) -> str:
    """Fetch filing document text, strip XBRL/HTML noise, truncate to max_chars."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = resp.text

        # Strip HTML/XBRL tags for readability
        if "<html" in text.lower()[:500]:
            s = _FilingStripper()
            s.feed(text)
            text = s.result.getvalue()

        text = _clean_text(text)

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
