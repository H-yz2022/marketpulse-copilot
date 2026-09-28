"""Configuration for MarketPulse Copilot, loaded from environment variables.

Copy `.env.example` to `.env` and fill in real values. Every setting has a
sensible default so the app runs (in a degraded/offline mode) even with no
`.env` file at all.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; env vars still work without it
    pass

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
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
    # --- Cost / abuse guardrails for the billed LLM endpoints -----------------
    # Every endpoint that calls the Anthropic API is checked against both caps
    # *before* the API is called. Per-client is keyed by client IP.
    max_llm_calls_per_client_per_day: int = field(
        default_factory=lambda: _int("MARKETPULSE_MAX_CLIENT_LLM_CALLS", 15)
    )
    max_llm_calls_per_day: int = field(default_factory=lambda: _int("MARKETPULSE_MAX_DAILY_LLM_CALLS", 150))
    # Max tool-use round trips the analyst agent may take for one question.
    agent_max_steps: int = field(default_factory=lambda: _int("MARKETPULSE_AGENT_MAX_STEPS", 6))
    # Comma-separated origins allowed to call the API from a browser (for a
    # separately hosted frontend). The bundled frontend is same-origin.
    cors_origins: tuple = field(
        default_factory=lambda: _parse_list(os.getenv("MARKETPULSE_CORS_ORIGINS", "http://localhost:5173"))
    )
    # Ingest the default tickers in the background on first boot if the DB is
    # empty, so a fresh cloud deploy isn't a blank page.
    auto_seed: bool = field(default_factory=lambda: os.getenv("MARKETPULSE_AUTO_SEED", "1") == "1")


settings = Settings()
