"""Test configuration.

Makes `src/` importable without an editable install, and points the app at a
throwaway database with auto-seeding and the real LLM disabled *before* any
`marketpulse` module reads its settings - so the suite never touches your
real data, the network, or your API key.
"""
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="marketpulse-tests-")
os.environ["MARKETPULSE_DB_PATH"] = str(Path(_tmp) / "test.db")
os.environ["CHROMA_PERSIST_DIR"] = str(Path(_tmp) / "chroma")
os.environ["MARKETPULSE_AUTO_SEED"] = "0"
os.environ["ANTHROPIC_API_KEY"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
