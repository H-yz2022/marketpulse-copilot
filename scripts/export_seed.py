"""Save the current database as the built-in snapshot (seed/marketpulse_seed.json.gz).

Run this after fetching fresh data locally; commit the resulting file so every
fresh install / deploy starts instantly with this data.

Usage:
    python scripts/export_seed.py              # latest 3 annual reports per ticker
    python scripts/export_seed.py --per-ticker 2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketpulse.seed import SEED_PATH, export_snapshot  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-ticker", type=int, default=3, help="10-K filings to keep per ticker")
    args = parser.parse_args()
    summary = export_snapshot(SEED_PATH, per_ticker=args.per_ticker)
    print(
        f"Wrote {summary['path']} ({summary['bytes'] / 1024:.0f} KB): "
        f"{len(summary['tickers'])} tickers, {summary['prices']} price rows, "
        f"{summary['filings']} filings, {summary['sentiment']} sentiment scores"
    )
