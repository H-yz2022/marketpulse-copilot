from marketpulse.db import fetch_sentiment_scores
from marketpulse.nlp import sentiment


def test_lexicon_positive(monkeypatch):
    monkeypatch.setattr(sentiment, "_load_finbert_pipeline", lambda: None)
    result = sentiment.score_text("Revenue growth beat expectations with record profit.")
    assert result.label == "positive"
    assert result.method == "lexicon"


def test_lexicon_negative(monkeypatch):
    monkeypatch.setattr(sentiment, "_load_finbert_pipeline", lambda: None)
    result = sentiment.score_text(
        "The company faces a lawsuit and reported a sharp decline in sales."
    )
    assert result.label == "negative"


def test_empty_text_is_neutral():
    result = sentiment.score_text("")
    assert result.label == "neutral"
    assert result.score == 0.0


def test_score_and_store_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(sentiment, "_load_finbert_pipeline", lambda: None)
    db_path = str(tmp_path / "test.db")

    result = sentiment.score_and_store(
        "AAPL", "Strong growth and record profit.", "news", db_path=db_path
    )
    assert result.label == "positive"

    rows = fetch_sentiment_scores("AAPL", db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["label"] == "positive"
