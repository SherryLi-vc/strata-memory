"""Rebuild must embed and write in batches, not one SQLite chroma upsert per row."""

from __future__ import annotations

import asyncio
from pathlib import Path

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.ops.rebuild import strata_rebuild_index
from strata_memory.storage.sqlite_vectors import SqliteVectorStore
from strata_memory.storage.truth_store import TruthStore


class _CountingEmbed:
    backend = "hashing"
    dimension = 4

    def __init__(self):
        self.embed_calls = 0
        self.batch_calls = 0
        self.batch_sizes: list[int] = []

    async def embed(self, text: str) -> list[float]:
        self.embed_calls += 1
        return [0.1, 0.2, 0.3, 0.4]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls += 1
        self.batch_sizes.append(len(texts))
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


class _CountingChroma(SqliteVectorStore):
    def __init__(self, persist_dir: Path):
        super().__init__(persist_dir)
        self.add_calls = 0
        self.add_batch_sizes: list[int] = []

    def add(self, documents, metadatas, ids, embeddings):  # type: ignore[override]
        self.add_calls += 1
        self.add_batch_sizes.append(len(ids))
        return super().add(documents, metadatas, ids, embeddings)


def _palace(tmp_path: Path, n: int):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(
        palace_path=str(palace),
        mode="personal",
        version="2.2.1",
        embedding={"provider": "local", "model": "hashing", "dimension": 4, "mode": "local"},
        cbt={"enabled": False, "mode": "off", "cooling_hours": 48, "detect_distortions": False},
    )
    save_config(cfg)
    store = TruthStore(truth_db_path(palace))
    for i in range(n):
        store.insert_memory(
            tenant_id="",
            user_id="user_a",
            session_id="",
            memory_type="factual_truth",
            fact_claim=f"Batch rebuild fact number {i:04d} about gateway port {8000 + i}.",
            content_hash=f"batch-{i}",
            confidence=0.9,
            importance=0.5,
        )
    return cfg, store, _CountingChroma(palace / "l2_vector")


def test_rebuild_uses_embed_batch_and_batched_chroma_writes(tmp_path: Path):
    """With N>1 rows, rebuild must call embed_batch and must not upsert once per row."""
    n = 25
    cfg, store, chroma = _palace(tmp_path, n)
    embed = _CountingEmbed()

    out = asyncio.run(strata_rebuild_index(config=cfg, store=store, embed_provider=embed, chroma=chroma, confirm=True))

    assert out["status"] == "ok"
    assert out["indexed"] == n
    assert chroma.count() == n
    assert embed.batch_calls >= 1, "rebuild must call embed_batch"
    assert sum(embed.batch_sizes) == n
    # Prefer batches: single-row embed path must not be the main path.
    assert embed.embed_calls == 0, f"per-row embed still used {embed.embed_calls} times"
    assert chroma.add_calls < n, f"expected batched chroma.add, got {chroma.add_calls} calls for {n} rows"
    assert max(chroma.add_batch_sizes) > 1
    assert sum(chroma.add_batch_sizes) == n


def test_rebuild_batch_skips_negative_schema_and_preserves_semantics(tmp_path: Path):
    cfg, store, chroma = _palace(tmp_path, 5)
    store.insert_memory(
        tenant_id="",
        user_id="user_a",
        session_id="",
        memory_type="episodic_event",
        fact_claim="I am a total failure at everything forever.",
        content_hash="neg-1",
        confidence=0.5,
        is_negative_schema=True,
        is_scratch=True,
        layer="scratch",
    )
    embed = _CountingEmbed()
    out = asyncio.run(strata_rebuild_index(config=cfg, store=store, embed_provider=embed, chroma=chroma, confirm=True))
    assert out["status"] == "ok"
    assert out["indexed"] == 5
    assert sum(embed.batch_sizes) == 5
    assert chroma.count() == 5
