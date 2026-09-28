from marketpulse.db import fetch_filings
from marketpulse.ingestion import filings


class _FakeResponse:
    def __init__(self, json_data=None, text_data=""):
        self._json = json_data
        self.text = text_data

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


def test_get_cik_for_ticker(monkeypatch):
    fake_data = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }

    def fake_get(url, headers=None, timeout=None, params=None):
        return _FakeResponse(json_data=fake_data)

    monkeypatch.setattr(filings.requests, "get", fake_get)
    cik = filings.get_cik_for_ticker("aapl")
    assert cik == "0000320193"


def test_search_filings(monkeypatch):
    fake_hits = {
        "hits": {
            "hits": [
                {
                    "_id": "0000320193-26-000010:aapl10k.htm",
                    "_source": {
                        "adsh": "0000320193-26-000010",
                        "ciks": ["0000320193"],
                        "form": "10-K",
                        "file_date": "2026-01-15",
                        "display_names": ["Apple Inc. (AAPL)"],
                    },
                }
            ]
        }
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(json_data=fake_hits)

    monkeypatch.setattr(filings.requests, "get", fake_get)
    hits = filings.search_filings("risk factors", forms="10-K")
    assert len(hits) == 1
    assert hits[0]["_source"]["form"] == "10-K"


def test_fetch_document_excerpt_extracts_risk_factors(monkeypatch):
    fake_html = (
        "<html><body><p>Item 1A. Risk Factors</p>"
        "<p>Our business faces risks related to supply chain and competition.</p>"
        "<p>Item 1B. Unresolved Staff Comments</p></body></html>"
    )

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(text_data=fake_html)

    monkeypatch.setattr(filings.requests, "get", fake_get)
    excerpt = filings.fetch_document_excerpt("0000320193", "0000320193-26-000010", "aapl10k.htm")
    assert "supply chain" in excerpt.lower()
    assert "unresolved staff comments" not in excerpt.lower()


def test_fetch_document_excerpt_skips_table_of_contents_entry(monkeypatch):
    # Real 10-Ks repeat "Item 1A. Risk Factors" in the table of contents
    # (immediately followed by a page number and "Item 1B") before the real
    # section appears later in the document. The excerpt should come from
    # the real section, not the two-word ToC line.
    fake_html = (
        "<html><body>"
        "<p>Item 1A. Risk Factors 12 Item 1B. Unresolved Staff Comments 14</p>"
        "<p>... table of contents continues ...</p>"
        "<p>Item 1A. Risk Factors</p>"
        "<p>Our business faces risks related to supply chain and competition.</p>"
        "<p>Item 1B. Unresolved Staff Comments</p>"
        "</body></html>"
    )

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(text_data=fake_html)

    monkeypatch.setattr(filings.requests, "get", fake_get)
    excerpt = filings.fetch_document_excerpt("0000320193", "0000320193-26-000010", "aapl10k.htm")
    assert "supply chain" in excerpt.lower()
    assert "table of contents continues" not in excerpt.lower()
    assert "unresolved staff comments" not in excerpt.lower()


def test_fetch_document_excerpt_skips_non_html(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        raise AssertionError("should not fetch a non-HTML document at all")

    monkeypatch.setattr(filings.requests, "get", fake_get)
    excerpt = filings.fetch_document_excerpt("0000320193", "0000320193-26-000010", "R1.xml")
    assert excerpt == ""


def test_ingest_filings_for_ticker(monkeypatch, tmp_path):
    fake_cik_data = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    fake_hits = {
        "hits": {
            "hits": [
                {
                    "_id": "0000320193-26-000010:aapl10k.htm",
                    "_source": {
                        "adsh": "0000320193-26-000010",
                        "ciks": ["0000320193"],
                        "form": "10-K",
                        "file_date": "2026-01-15",
                        "display_names": ["Apple Inc. (AAPL)"],
                    },
                }
            ]
        }
    }
    fake_html = (
        "<html><body><p>Item 1A. Risk Factors</p>"
        "<p>Our business faces risks related to supply chain and competition.</p>"
        "<p>Item 1B. Unresolved Staff Comments</p></body></html>"
    )

    def fake_get(url, params=None, headers=None, timeout=None):
        if "company_tickers" in url:
            return _FakeResponse(json_data=fake_cik_data)
        if "efts.sec.gov" in url:
            return _FakeResponse(json_data=fake_hits)
        return _FakeResponse(text_data=fake_html)  # the filing document itself

    monkeypatch.setattr(filings.requests, "get", fake_get)

    db_path = str(tmp_path / "test.db")
    n = filings.ingest_filings_for_ticker("AAPL", db_path=db_path)
    assert n == 1

    rows = fetch_filings("AAPL", db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["form_type"] == "10-K"
    assert "supply chain" in rows[0]["excerpt"].lower()

def test_select_main_documents_drops_exhibits_duplicates_and_old_years():
    def hit(acc, fname, date, file_type):
        return {"_id": f"{acc}:{fname}", "_source": {"file_date": date, "file_type": file_type, "form": "10-K"}}

    hits = [
        hit("A-2024", "main24.htm", "2024-11-01", "10-K"),
        hit("A-2026", "ex10.htm", "2026-02-25", "EX-10.24"),
        hit("A-2026", "main26.htm", "2026-02-25", "10-K"),
        hit("A-2026", "main26b.htm", "2026-02-25", "10-K"),  # same accession -> dropped
        hit("A-2025", "main25.htm", "2025-02-27", "10-K"),
        hit("A-2010", "main10.htm", "2010-10-27", "10-K"),
    ]
    kept = filings.select_main_documents(hits, forms="10-K", limit=3)
    assert [h["_id"] for h in kept] == ["A-2026:main26.htm", "A-2025:main25.htm", "A-2024:main24.htm"]


def test_pick_risk_section_ignores_toc_references_and_trailing_index():
    real = "Our business faces many risks, including supply chain disruption. " * 20
    body = (
        "Item 1A. Risk Factors 12 Item 1B. Unresolved Staff Comments 14 "  # table of contents
        "Business overview. For more, see \"Item 1A. Risk Factors\" for additional information. "
        "Item 1A. Risk Factors " + real + " Item 1B. Unresolved Staff Comments None. "
        "MD&A discussed in Item 1A. Risk Factors of this report. "
        "Cross reference index Item 1A. Risk Factors 18 Item 1B. Unresolved Staff Comments 30"  # MSFT-style index
    )
    section = filings._pick_risk_section(body)
    assert section.startswith("Our business faces many risks")
    assert "Unresolved" not in section and "Business overview" not in section
