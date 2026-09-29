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
        self.vectors = {}

    def upsert(self, ids, documents, metadatas, embeddings=None):
        for n, (i, d, m) in enumerate(zip(ids, documents, metadatas)):
            self.docs[i] = (d, m)
            if embeddings is not None:
                self.vectors[i] = embeddings[n]

    def get(self, ids, include=None):
        return {"ids": [i for i in ids if i in self.docs]}

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


def test_retrieve_catches_up_vector_index_lazily(monkeypatch):
    """Chunks indexed with dense=False reach Chroma on the first query, using the
    snapshot's precomputed vectors where present and the model only for the rest."""
    from marketpulse import db, seed

    rows = [{"chunk_id": f"doc1-{i}", "text": f"export controls {i}", "metadata_json": '{"ticker": "NVDA"}'}
            for i in range(3)]
    monkeypatch.setattr(db, "fetch_chunks", lambda ticker=None: rows)
    monkeypatch.setattr(seed, "load_vectors", lambda: {"doc1-0": [0.0, 0.0], "doc1-1": [1.0, 1.0]})
    fake = _FakeCollection()
    monkeypatch.setattr(pipeline, "_get_collection", lambda: fake)
    monkeypatch.setattr(pipeline, "_SYNCED", False)

    assert pipeline.retrieve("export controls")
    assert set(fake.docs) == {"doc1-0", "doc1-1", "doc1-2"}
    assert fake.vectors == {"doc1-0": [0.0, 0.0], "doc1-1": [1.0, 1.0]}  # doc1-2 left to the model
    assert pipeline._SYNCED
    assert pipeline.embed_stored_chunks(collection=fake) == 0  # idempotent
