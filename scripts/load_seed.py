"""Load the built-in snapshot into an empty local database (no network needed).

The API does this automatically on first start; run it by hand after
`python scripts/reset_data.py` if you want to go back to the snapshot.

Usage:
    python scripts/load_seed.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketpulse import db  # noqa: E402
from marketpulse.rag.pipeline import embed_stored_chunks  # noqa: E402
from marketpulse.seed import SEED_PATH, load_snapshot, snapshot_available  # noqa: E402

if __name__ == "__main__":
    if not snapshot_available():
        sys.exit(f"No snapshot at {SEED_PATH}. Create one with scripts/export_seed.py.")
    if db.list_tickers():
        sys.exit("Database already has data. Run scripts/reset_data.py first to start from the snapshot.")
    summary = load_snapshot()
    print(f"Loaded {summary['filings']} filings for {', '.join(summary['tickers'])} (snapshot {summary['as_of']})")
    print("Embedding chunks for semantic search (about a minute)...")
    print(f"Embedded {embed_stored_chunks()} chunks. Done.")
