import json

from marketpulse import db, seed
from tests.fakes import seed_db


def test_snapshot_roundtrip_keeps_latest_main_filings(tmp_path, monkeypatch):
    src = str(tmp_path / "src.db")
    seed_db(src)
    # Older filing, a duplicate document of the same accession, and an exhibit - only the newest main doc survives.
    for fid, date, text in [
        ("AAPL-0:old.htm", "2020-11-01", "Old risk factors"),
        ("AAPL-1:dup.htm", "2025-10-01", "Duplicate document"),
        ("AAPL-2:ex10.htm", "2026-01-01", "EX-10.1 2 ex10.htm Compensation agreement"),
    ]:
        db.upsert_filing({"filing_id": fid, "ticker": "AAPL", "form_type": "10-K", "filed_date": date,
                          "title": "t", "url": "", "excerpt": text}, db_path=src)
    import marketpulse.rag.pipeline as rp

    monkeypatch.setattr(rp, "embed_texts", lambda texts: [[0.5, -0.25, float(i)] for i in range(len(texts))])
    path = tmp_path / "snap.json.gz"
    summary = seed.export_snapshot(path, per_ticker=2, db_path=src)
    assert summary["tickers"] == ["AAPL", "MSFT"] and summary["prices"] == 60

    dst = str(tmp_path / "dst.db")

    calls = []
    monkeypatch.setattr(rp, "upsert_chunks", lambda rows: calls.append(len(rows)))
    loaded = seed.load_snapshot(path, db_path=dst)
    ids = [f["filing_id"] for f in db.fetch_filings("AAPL", db_path=dst)]
    assert ids == ["AAPL-1", "AAPL-0:old.htm"]
    assert loaded["filings"] == 3 and sum(calls) == loaded["chunks"] > 0
    # One precomputed vector per indexed chunk, keyed by the chunk ids the loader creates.
    vectors = seed.load_vectors(path)
    assert summary["vectors"] == len(vectors) == loaded["chunks"]
    assert vectors["AAPL-1-0"] == [0.5, -0.25, 0.0]
    status = seed.data_status("AAPL", db_path=dst)
    assert status["source"] == "snapshot" and status["as_of"] == json.loads(
        db.get_meta("source:MSFT", db_path=dst))["as_of"]


def test_backfill_adds_older_history_and_fundamentals_without_touching_live_rows(tmp_path):
    from marketpulse.seed import SEED_PATH

    dst = str(tmp_path / "p.db")
    live = {"ticker": "AAPL", "trade_date": "2026-09-25", "open": 1, "high": 1, "low": 1, "close": 1.0, "volume": 1}
    db.upsert_price_history([live], db_path=dst)
    added = seed.backfill_from_snapshot(SEED_PATH, db_path=dst)
    assert added["prices"] > 1000 and "SPY" in added["fundamentals"]
    aapl = db.fetch_price_history("AAPL", db_path=dst)
    assert aapl[-1]["close"] == 1.0 and aapl[0]["trade_date"] < "2020-01-01"  # live row kept, older history added
    assert seed.data_status("SPY", db_path=dst)["source"] == "snapshot"
    assert seed.backfill_from_snapshot(SEED_PATH, db_path=dst) == {"prices": 0, "fundamentals": []}  # once per snapshot
