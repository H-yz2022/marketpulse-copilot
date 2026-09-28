"""NLP sentiment scoring for finance text.

Primary path: FinBERT (ProsusAI/finbert) via HuggingFace `transformers` — a
model pretrained specifically on financial text. This is the model finance
NLP teams actually reach for, and it's a stronger portfolio signal than a
generic sentiment lexicon.

Fallback path: a small finance-flavored keyword lexicon, used automatically
when `transformers`/`torch` aren't installed or the model can't be
downloaded (e.g. no network in CI). This keeps the pipeline runnable
end to end everywhere; the README is upfront that FinBERT is the intended
production path and the lexicon is a documented offline fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Optional

from marketpulse.db import insert_sentiment_score

_POSITIVE_WORDS = {
    "growth", "beat", "beats", "record", "strong", "upgrade", "outperform",
    "profit", "gain", "gains", "positive", "exceeded", "improve", "improved",
    "surge", "rally", "expansion", "robust",
}
_NEGATIVE_WORDS = {
    "decline", "loss", "losses", "miss", "missed", "downgrade", "underperform",
    "weak", "weakness", "risk", "lawsuit", "investigation", "recall", "layoffs",
    "bankruptcy", "default", "volatility", "impairment", "shortfall",
}


@dataclass
class SentimentResult:
    label: str  # "positive" | "negative" | "neutral"
    score: float  # confidence in [0, 1]
    method: str  # "finbert" | "lexicon"


@lru_cache(maxsize=1)
def _load_finbert_pipeline():
    """Lazily load and cache the FinBERT pipeline. Returns None if unavailable."""
    try:
        from transformers import pipeline
    except ImportError:
        return None
    try:
        return pipeline("sentiment-analysis", model="ProsusAI/finbert")
    except Exception:
        # Covers offline environments, first-run download failures, etc.
        return None


def _lexicon_sentiment(text: str) -> SentimentResult:
    words = [w.strip(".,!?;:()\"'").lower() for w in text.split()]
    pos = sum(1 for w in words if w in _POSITIVE_WORDS)
    neg = sum(1 for w in words if w in _NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return SentimentResult(label="neutral", score=0.5, method="lexicon")
    if pos > neg:
        return SentimentResult(label="positive", score=pos / total, method="lexicon")
    if neg > pos:
        return SentimentResult(label="negative", score=neg / total, method="lexicon")
    return SentimentResult(label="neutral", score=0.5, method="lexicon")


def score_text(text: str, use_finbert: bool = True) -> SentimentResult:
    """Score a piece of finance text as positive/negative/neutral."""
    if not text or not text.strip():
        return SentimentResult(label="neutral", score=0.0, method="lexicon")

    if use_finbert:
        clf = _load_finbert_pipeline()
        if clf is not None:
            result = clf(text[:512])[0]  # stay within FinBERT's tokenizer window
            return SentimentResult(
                label=result["label"].lower(), score=float(result["score"]), method="finbert"
            )

    return _lexicon_sentiment(text)


def score_and_store(
    ticker: str,
    text: str,
    source_type: str,
    source_id: Optional[str] = None,
    use_finbert: bool = True,
    db_path: Optional[str] = None,
) -> SentimentResult:
    """Score text and persist the result to the sentiment_scores table."""
    result = score_text(text, use_finbert=use_finbert)
    insert_sentiment_score(
        {
            "ticker": ticker.upper(),
            "source_type": source_type,
            "source_id": source_id,
            "scored_date": date.today().isoformat(),
            "label": result.label,
            "score": result.score,
            "text_snippet": text[:280],
        },
        db_path=db_path,
    )
    return result
