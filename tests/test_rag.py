from marketpulse.rag import pipeline


def test_chunk_text_basic():
    text = "a" * 2000
    chunks = pipeline.chunk_text(text, chunk_size=800, overlap=100)
    assert len(chunks) >= 2
    assert chunks[0] == text[:800]
    # consecutive chunks should overlap by the requested amount
    assert text[700:800] == chunks[1][:100]


def test_chunk_text_empty():
    assert pipeline.chunk_text("") == []


class _FakeCollection:
    """Minimal stand-in for a chromadb Collection, so tests don't need
    chromadb installed or make any network/model-download calls."""

    def __init__(self):
        self.docs = {}

    def upsert(self, ids, documents, metadatas):
        for i, d, m in zip(ids, documents, metadatas):
            self.docs[i] = (d, m)

    def query(self, query_texts, n_results, where=None):
        items = list(self.docs.items())[:n_results]
        return {
            "ids": [[i for i, _ in items]],
            "documents": [[d for _, (d, _m) in items]],
            "metadatas": [[m for _, (_d, m) in items]],
            "distances": [[0.1] * len(items)],
        }

    def delete(self, where=None):
        if not where:
            self.docs.clear()
            return
        self.docs = {
            i: (d, m) for i, (d, m) in self.docs.items() if not all(m.get(k) == v for k, v in where.items())
        }


def test_index_and_retrieve(monkeypatch):
    fake = _FakeCollection()
    monkeypatch.setattr(pipeline, "_get_collection", lambda: fake)

    n = pipeline.index_document(
        "doc1", "Revenue grew due to strong iPhone demand. " * 5, {"ticker": "AAPL"}
    )
    assert n >= 1

    hits = pipeline.retrieve("iPhone demand")
    assert len(hits) >= 1
    assert "metadata" in hits[0]


def test_answer_question_with_mock_generate(monkeypatch):
    fake = _FakeCollection()
    monkeypatch.setattr(pipeline, "_get_collection", lambda: fake)
    pipeline.index_document("doc1", "Revenue grew due to strong iPhone demand.", {"ticker": "AAPL"})

    result = pipeline.answer_question(
        "Why did revenue grow?",
        generate_fn=lambda q, chunks: f"Because: {chunks[0][:20]}",
    )
    assert "Because" in result["answer"]
    assert result["sources"]


def test_answer_question_no_matches(monkeypatch):
    fake = _FakeCollection()
    monkeypatch.setattr(pipeline, "_get_collection", lambda: fake)

    result = pipeline.answer_question("anything")
    assert "No indexed filings" in result["answer"]


def test_delete_ticker_documents_only_removes_matching_ticker(monkeypatch):
    fake = _FakeCollection()
    monkeypatch.setattr(pipeline, "_get_collection", lambda: fake)

    pipeline.index_document("aapl-2016", "old, stale risk text", {"ticker": "AAPL"})
    pipeline.index_document("aapl-2026", "current risk text", {"ticker": "AAPL"})
    pipeline.index_document("msft-2026", "a different company's text", {"ticker": "MSFT"})

    pipeline.delete_ticker_documents("aapl")

    remaining_tickers = {m["ticker"] for _d, m in fake.docs.values()}
    assert remaining_tickers == {"MSFT"}


def test_reset_client_clears_cached_client(monkeypatch):
    monkeypatch.setattr(pipeline, "_CLIENT", object())  # simulate an already-connected client
    pipeline.reset_client()
    assert pipeline._CLIENT is None
