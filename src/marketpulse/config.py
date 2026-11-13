"""Configuration for MarketPulse Copilot, loaded from environment variables.

Copy `.env.example` to `.env` and fill in real values. Every setting has a
sensible default so the app runs (in a degraded/offline mode) even with no
`.env` file at all.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; env vars still work without it
    pass

BASE_DIR = Path(__file__).resolve().parents[2]
# Vercel sets VERCEL=1 at build and run time.
ON_VERCEL = bool(os.getenv("VERCEL"))


def data_dir(env: Mapping[str, str] = os.environ, base: Path = BASE_DIR) -> Path:
    """Where the SQLite database and vector index live.

    Vercel's filesystem is read-only apart from /tmp, which is per-instance scratch
    space: the database is rebuilt there from the built-in snapshot when an
    instance starts, which takes about a second.
    """
    if env.get("MARKETPULSE_DATA_DIR"):
        return Path(env["MARKETPULSE_DATA_DIR"])
    if env.get("VERCEL"):
        return Path(tempfile.gettempdir()) / "marketpulse"
    return base / "data"


DATA_DIR = data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _parse_list(raw: str, upper: bool = False) -> tuple[str, ...]:
    items = (t.strip() for t in raw.split(",") if t.strip())
    return tuple(t.upper() if upper else t for t in items)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("MARKETPULSE_DB_PATH", str(DATA_DIR / "marketpulse.db")))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"))
    sec_user_agent: str = field(
        default_factory=lambda: os.getenv("SEC_USER_AGENT", "MarketPulse Copilot research@example.com")
    )
    chroma_persist_dir: str = field(
        default_factory=lambda: os.getenv("CHROMA_PERSIST_DIR", str(DATA_DIR / "chroma"))
    )
    default_tickers: tuple = field(
        default_factory=lambda: _parse_list(os.getenv("MARKETPULSE_TICKERS", "AAPL,MSFT,JPM,NVDA,GS"), upper=True)
    )
    # Market benchmarks (index ETFs) used as reference series: prices only, no
    # filings. ETFs rather than raw index levels because their adjusted closes
    # include dividends, like the stocks' adjusted closes they're compared with.
    benchmarks: tuple = field(
        default_factory=lambda: _parse_list(os.getenv("MARKETPULSE_BENCHMARKS", "SPY,QQQ,DIA,IWM,XLK,XLF"), upper=True)
    )
    default_benchmark: str = field(default_factory=lambda: os.getenv("MARKETPULSE_DEFAULT_BENCHMARK", "SPY").upper())
    # Master switch for every LLM feature (agent, NL->SQL, briefs, RAG answers, AI compare).
    # Off unless explicitly enabled, so no deployment can make billed calls by accident.
    ai_enabled: bool = field(default_factory=lambda: os.getenv("MARKETPULSE_AI_ENABLED", "0") == "1")
    # --- Cost / abuse guardrails for the billed LLM endpoints -----------------
    # Every endpoint that calls the Anthropic API is checked against both caps
    # *before* the API is called. Per-client is keyed by client IP.
    max_llm_calls_per_client_per_day: int = field(
        default_factory=lambda: _int("MARKETPULSE_MAX_CLIENT_LLM_CALLS", 10)
    )
    max_llm_calls_per_day: int = field(default_factory=lambda: _int("MARKETPULSE_MAX_DAILY_LLM_CALLS", 30))
    # Max tool-use round trips the analyst agent may take for one question.
    agent_max_steps: int = field(default_factory=lambda: _int("MARKETPULSE_AGENT_MAX_STEPS", 6))
    # Comma-separated origins allowed to call the API from a browser (for a
    # separately hosted frontend). The bundled frontend is same-origin.
    cors_origins: tuple = field(
        default_factory=lambda: _parse_list(os.getenv("MARKETPULSE_CORS_ORIGINS", "http://localhost:5173"))
    )
    # "Refresh live data" (fetch prices/filings on demand). Off on Vercel by default: each
    # instance's database is temporary there, so the weekly snapshot job updates the data instead.
    live_refresh: bool = field(
        default_factory=lambda: os.getenv("MARKETPULSE_LIVE_REFRESH", "0" if ON_VERCEL else "1") == "1"
    )
    # Ingest the default tickers in the background on first boot if the DB is
    # empty, so a fresh cloud deploy isn't a blank page.
    auto_seed: bool = field(default_factory=lambda: os.getenv("MARKETPULSE_AUTO_SEED", "1") == "1")


BENCHMARK_NAMES = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq-100",
    "DIA": "Dow Jones 30",
    "IWM": "Russell 2000 small caps",
    "XLK": "Technology sector",
    "XLF": "Financials sector",
    "VTI": "Total US stock market",
    "EFA": "Developed markets ex-US",
}


def benchmark_name(symbol: str) -> str:
    return BENCHMARK_NAMES.get(symbol.upper(), symbol.upper())


settings = Settings()
