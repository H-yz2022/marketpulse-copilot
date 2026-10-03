"""Ingest price history + SEC filings, score sentiment, and index for RAG.

Usage:
    python scripts/run_pipeline.py --ticker AAPL
    python scripts/run_pipeline.py --ticker AAPL MSFT NVDA --period 1y
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketpulse.pipeline import refresh_ticker  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", nargs="+", default=["AAPL"], help="One or more ticker symbols")
    parser.add_argument("--period", default="10y", help="yfinance history period, e.g. 1y, 5y, 10y")
    args = parser.parse_args()
    for t in args.ticker:
        result = refresh_ticker(t, period=args.period, progress=lambda m: print(f"  - {m}"))
        print(f"{result['ticker']}: {result}")
    print("\nDone. Start the app with:  uvicorn marketpulse.api.main:app --reload")
