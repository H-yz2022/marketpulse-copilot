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
    path = tmp_path / "snap.json.gz"
    summary = seed.export_snapshot(path, per_ticker=2, db_path=src)
    assert summary["tickers"] == ["AAPL", "MSFT"] and summary["prices"] == 60

    dst = str(tmp_path / "dst.db")
    import marketpulse.rag.pipeline as rp

    calls = []
    monkeypatch.setattr(rp, "upsert_chunks", lambda rows: calls.append(len(rows)))
    loaded = seed.load_snapshot(path, db_path=dst)
    ids = [f["filing_id"] for f in db.fetch_filings("AAPL", db_path=dst)]
    assert ids == ["AAPL-1", "AAPL-0:old.htm"]
    assert loaded["filings"] == 3 and sum(calls) == loaded["chunks"] > 0
    status = seed.data_status("AAPL", db_path=dst)
    assert status["source"] == "snapshot" and status["as_of"] == json.loads(
        db.get_meta("source:MSFT", db_path=dst))["as_of"]
