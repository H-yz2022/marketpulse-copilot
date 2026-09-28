"""Delete the locally generated SQLite DB and Chroma vector index.

Both are pure caches rebuilt by scripts/run_pipeline.py - safe to delete at
any time you want a clean re-ingest. This matters in particular after fixing
a parsing bug in the ingestion code: run_pipeline.py's writes are all
upserts, so they overwrite a filing that gets re-fetched under the *same*
ID, but they never remove old chunks/rows left behind by filings that don't
get re-fetched (e.g. because you changed which forms are searched). Those
stale entries just sit there and can still win future similarity searches.
Wiping both stores before re-ingesting guarantees only current, correctly
parsed data is present.

Usage:
    python scripts/reset_data.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketpulse.config import settings  # noqa: E402


def main() -> None:
    db_path = Path(settings.db_path)
    chroma_dir = Path(settings.chroma_persist_dir)

    if db_path.exists():
        db_path.unlink()
        print(f"Deleted {db_path}")
    else:
        print(f"No DB found at {db_path} (nothing to delete)")

    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)
        print(f"Deleted {chroma_dir}")
    else:
        print(f"No Chroma index found at {chroma_dir} (nothing to delete)")

    print("\nDone. Re-run scripts/run_pipeline.py for each ticker to rebuild from scratch.")


if __name__ == "__main__":
    main()