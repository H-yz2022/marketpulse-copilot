from datetime import date

from marketpulse import db
from marketpulse.ingestion import fundamentals as fx


def test_parse_info_normalises_units():
    out = fx.parse_info(
        {"longName": "Apple Inc.", "sector": "Technology", "trailingPE": 38.3, "revenueGrowth": 0.164,
         "dividendYield": 0.32, "debtToEquity": 78.4, "heldPercentInstitutions": 0.663, "shortPercentOfFloat": "n/a"}
    )
    assert out["name"] == "Apple Inc." and out["pe_trailing"] == 38.3
    assert out["revenue_growth_pct"] == 16.4  # fraction -> percent
    assert out["dividend_yield_pct"] == 0.32  # Yahoo already reports this one in percent
    assert out["debt_to_equity"] == 0.784  # Yahoo's D/E is x100
    assert out["institution_pct"] == 66.3 and out["short_pct_float"] is None
    assert fx.parse_info({"quoteType": "ETF"})["sector"] == "Fund"


def test_summarize_insiders_counts_only_open_market_trades_in_window():
    rows = [
        {"Start Date": "2026-09-21", "Text": "Sale at price 222.19 per share.", "Shares": 100, "Value": 22000,
         "Insider": "DOE JANE", "Position": "Officer"},
        {"Start Date": "2026-08-01", "Text": "Purchase at price 200 per share.", "Shares": 10, "Value": 2000,
         "Insider": "ROE RICHARD", "Position": "Director"},
        {"Start Date": "2026-07-01", "Text": "Stock Award(Grant) at price 0.00", "Shares": 500, "Value": 0,
         "Insider": "X", "Position": "Officer"},
        {"Start Date": "2024-01-01", "Text": "Sale at price 100", "Shares": 1, "Value": 999, "Insider": "OLD",
         "Position": ""},
    ]
    s = fx.summarize_insiders(rows, today=date(2026, 10, 1))
    assert (s["buy_value"], s["sell_value"], s["buy_count"], s["sell_count"]) == (2000, 22000, 1, 1)
    assert s["net_value"] == -20000
    assert [r["type"] for r in s["recent"]] == ["sell", "buy", "other", "sell"]
    assert s["recent"][0]["insider"] == "Doe Jane"


def test_fundamentals_round_trip(tmp_path):
    path = str(tmp_path / "f.db")
    db.upsert_fundamentals("aapl", "2026-10-01", {"pe_trailing": 30.0}, db_path=path)
    db.upsert_fundamentals("AAPL", "2026-10-02", {"pe_trailing": 31.0}, db_path=path)
    got = db.fetch_fundamentals(["AAPL", "MSFT"], db_path=path)
    assert got == {"AAPL": {"pe_trailing": 31.0, "as_of": "2026-10-02"}}
    assert db.fetch_fundamentals([], db_path=path) == {}
