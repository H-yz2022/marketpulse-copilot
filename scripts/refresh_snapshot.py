"""Rebuild the built-in snapshot (seed/marketpulse_seed.json.gz) from live data.

Fetches 10 years of prices, fundamentals and insider trades, the latest 10-K
risk-factor sections and sentiment for every default ticker, plus prices and
fund data for the benchmark ETFs, then exports them as the new snapshot.

Run weekly by .github/workflows/refresh-data.yml, so hosts without a persistent
disk (like Vercel) still serve current data. Works in a throwaway database and
only overwrites the snapshot if every ticker refreshed and passed sanity checks;
otherwise it exits non-zero and leaves the existing file alone.

Usage:
    python scripts/refresh_snapshot.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

# A fresh database per run, isolated from any local data/.
_tmp = tempfile.mkdtemp(prefix="marketpulse-refresh-")
os.environ.setdefault("MARKETPULSE_DATA_DIR", _tmp)
os.environ["MARKETPULSE_DB_PATH"] = str(Path(_tmp) / "refresh.db")
os.environ["MARKETPULSE_AUTO_SEED"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketpulse import db  # noqa: E402
from marketpulse.config import settings  # noqa: E402
from marketpulse.pipeline import refresh_prices, refresh_ticker  # noqa: E402
from marketpulse.seed import SEED_PATH, export_snapshot  # noqa: E402

MIN_PRICE_ROWS = 1000  # ~4 years; a 10-year fetch returns ~2,500
MAX_STALENESS = timedelta(days=7)


def main() -> int:
    db.init_db()
    problems: list[str] = []
    for t in settings.default_tickers:
        try:
            r = refresh_ticker(t, progress=lambda m: print(f"  {m}"))
            print(f"{t}: {r}")
        except Exception as exc:  # noqa: BLE001 - report every failure, then refuse to publish
            problems.append(f"{t}: {type(exc).__name__}: {exc}")
    for b in settings.benchmarks:
        try:
            print(f"{b}: {refresh_prices(b)}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{b}: {type(exc).__name__}: {exc}")

    cutoff = (date.today() - MAX_STALENESS).isoformat()
    for t in (*settings.default_tickers, *settings.benchmarks):
        rows = db.fetch_price_history(t)
        if len(rows) < MIN_PRICE_ROWS or rows[-1]["trade_date"] < cutoff:
            last = rows[-1]["trade_date"] if rows else "none"
            problems.append(f"{t}: only {len(rows)} price rows, last {last}")
    for t in settings.default_tickers:
        if not db.fetch_filings(t):
            problems.append(f"{t}: no 10-K filings")

    if problems:
        print("\nNot publishing a new snapshot:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    summary = export_snapshot(SEED_PATH, per_ticker=3)
    print(
        f"\nWrote {summary['path']} ({summary['bytes'] / 1024:.0f} KB): {len(summary['tickers'])} tickers, "
        f"{summary['prices']} price rows, {summary['filings']} filings, {summary['fundamentals']} fundamentals, "
        f"{summary['vectors']} vectors"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
