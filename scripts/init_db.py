"""Initialize the MarketPulse AI SQLite database (creates tables if missing).

Usage:
    python scripts/init_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketpulse.config import settings  # noqa: E402
from marketpulse.db import init_db  # noqa: E402

if __name__ == "__main__":
    init_db()
    print(f"Initialized database at {settings.db_path}")
