"""SEC filing ingestion via the EDGAR full-text search API (efts.sec.gov).

Free, no API key required, but the SEC requires a descriptive User-Agent
header identifying you (see SEC_USER_AGENT in .env.example) and enforces a
rate limit of ~10 requests/second. See:
https://www.sec.gov/edgar/search/ (the human-facing UI this API powers)

Note: EDGAR's full-text search API only returns *metadata* about which
filings matched a query - despite "highlight" being a common convention for
this kind of search API, EDGAR doesn't return one. To get real filing text,
we fetch the matched document itself (using the "_id" field, which encodes
the accession number and filename, e.g. "0001628280-16-020309:a10-k.htm")
and try to isolate the "Item 1A. Risk Factors" section with a simple regex,
falling back to the start of the document body if that section can't be
found (e.g. this is a 10-Q, which doesn't always include one).
"""
from __future__ import annotations

import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from marketpulse.config import settings
from marketpulse.db import upsert_filing

FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

_RISK_FACTORS_HEADER_RE = re.compile(r"item\s*1a\.?\s*risk factors", re.IGNORECASE)
_ITEM_1B_RE = re.compile(r"item\s*1b\.?", re.IGNORECASE)


def _headers() -> dict:
    return {"User-Agent": settings.sec_user_agent}


def get_cik_for_ticker(ticker: str) -> Optional[str]:
    """Look up a company's 10-digit zero-padded CIK from its ticker symbol."""
    resp = requests.get(COMPANY_TICKERS_URL, headers=_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()  # dict of {"0": {"cik_str": ..., "ticker": "AAPL", "title": ...}, ...}
    ticker = ticker.upper()
    for entry in data.values():
        if entry.get("ticker", "").upper() == ticker:
            return str(entry["cik_str"]).zfill(10)
    return None


def search_filings(
    query: str,
    forms: str = "10-K",
    ciks: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 10,
) -> list[dict]:
    """Search SEC EDGAR full-text search for filings matching a query.

    `query` searches the filing text itself (e.g. "risk factors"). Pass
    `ciks` (10-digit, zero-padded) to restrict to one company - use
    `get_cik_for_ticker` to resolve a ticker to a CIK first.

    Note this only returns *metadata* about matching filings (which
    document matched, its form type, filing date, etc) - not the matching
    text itself. See `fetch_document_excerpt` for that.
    """
    params: dict = {"q": query, "forms": forms, "size": size}
    if ciks:
        params["ciks"] = ciks
    if start_date and end_date:
        params.update({"dateRange": "custom", "startdt": start_date, "enddt": end_date})

    resp = requests.get(FULL_TEXT_SEARCH_URL, params=params, headers=_headers(), timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("hits", {}).get("hits", [])


def fetch_document_excerpt(cik: str, accession_no: str, filename: str, max_chars: int = 4000) -> str:
    """Fetch a filing document and return a plain-text excerpt from it.

    Skips non-HTML documents (a filing's matched file can be a raw XBRL
    ".xml" data file instead of the readable ".htm" filing itself - those
    aren't prose, can be huge, and aren't worth trying to parse as text).
    Tries to isolate the "Item 1A. Risk Factors" section; falls back to the
    start of the document body if that section isn't found.
    """
    if not filename.lower().endswith((".htm", ".html")):
        return ""

    cik_num = str(int(cik))  # EDGAR's Archives path wants no leading zeros
    accession_nodash = accession_no.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_nodash}/{filename}"
    resp = requests.get(url, headers=_headers(), timeout=20)
    resp.raise_for_status()

    # lxml is a compiled parser and handles large real-world filing HTML
    # (some run several MB) far faster and more reliably than the pure
    # Python stdlib "html.parser".
    soup = BeautifulSoup(resp.text, "lxml")
    body_text = soup.get_text(separator=" ", strip=True)
    body_text = re.sub(r"\s+", " ", body_text)

    # A real 10-K repeats "Item 1A. Risk Factors" at least twice: once in the
    # table of contents (immediately followed by a page number and "Item
    # 1B"), and again as the actual section header, with the real prose
    # after it. Taking the *first* occurrence - as an earlier version of
    # this function did - grabs only the two-word-and-a-page-number ToC
    # line. The *last* occurrence is reliably the real section header, so we
    # anchor there and read forward to the next "Item 1B" (uncapped, since
    # real risk-factor sections can run tens of thousands of characters).
    headers = list(_RISK_FACTORS_HEADER_RE.finditer(body_text))
    if headers:
        start = headers[-1].end()
        rest = body_text[start:]
        end_match = _ITEM_1B_RE.search(rest)
        end = end_match.start() if end_match else len(rest)
        excerpt = rest[:end].strip()
        if excerpt:
            return excerpt[:max_chars]
    return body_text[:max_chars]


def ingest_filings_for_ticker(
    ticker: str,
    query: str = "risk factors",
    forms: str = "10-K",
    size: int = 5,
    db_path: Optional[str] = None,
) -> int:
    """Look up a ticker's CIK, search recent filings, fetch real excerpt text, and persist.

    Defaults to 10-K filings only. A 10-Q's "Item 1A. Risk Factors" section is
    usually just a pointer ("see Part I, Item 1A of the year's Form 10-K")
    plus a short list of *changes* since then - often "None." - so indexing
    10-Qs alongside 10-Ks mostly adds boilerplate noise that crowds out the
    actual, detailed risk-factor text a 10-K contains. Pass forms="10-K,10-Q"
    explicitly if you specifically want quarter-over-quarter change language.
    """
    cik = get_cik_for_ticker(ticker)
    hits = search_filings(query, forms=forms, ciks=cik, size=size)

    count = 0
    for hit in hits:
        source = hit.get("_source", {})
        raw_id = hit.get("_id", "")
        accession_no, _, filename = raw_id.partition(":")
        filer_cik = cik or next(iter(source.get("ciks", [])), None)

        url = ""
        excerpt = ""
        if filer_cik and accession_no and filename:
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(filer_cik)}/"
                f"{accession_no.replace('-', '')}/{filename}"
            )
            try:
                excerpt = fetch_document_excerpt(filer_cik, accession_no, filename, max_chars=30000)
            except Exception:  # noqa: BLE001 - network/parsing hiccups shouldn't kill the whole run
                excerpt = ""

        display_name = source.get("display_names", [""])[0] if source.get("display_names") else ""
        if not excerpt:
            excerpt = display_name

        upsert_filing(
            {
                "filing_id": raw_id or f"{ticker}-{accession_no}",
                "ticker": ticker.upper(),
                "form_type": source.get("form", ""),
                "filed_date": source.get("file_date", ""),
                "title": display_name,
                "url": url,
                "excerpt": excerpt,
            },
            db_path=db_path,
        )
        count += 1
    return count