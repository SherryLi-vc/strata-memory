"""H2: an empty tenant is its own scope in recall. N5: recall audit does not keep the query text."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.embedder_stamp import identity_dict, write_stamp
from strata_memory.pipeline.recall import recall_context
from strata_memory.storage.sqlite_vectors import SqliteVectorStore
from strata_memory.storage.truth_store import TruthStore


class _HashEmbed:
    backend = "hashing"

    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


def _setup(tmp_path: Path):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(
        palace_path=str(palace),
        mode="personal",
        embedding={"provider": "local", "model": "hashing", "dimension": 4, "mode": "local"},
        cbt={"enabled": False, "mode": "off", "cooling_hours": 48, "detect_distortions": False},
    )
    save_config(cfg)
    store = TruthStore(truth_db_path(palace))
    chroma = SqliteVectorStore(palace / "l2_vector")
    ids = {}
    for tenant in ("", "t1", "t2"):
        row = store.insert_memory(
            tenant_id=tenant,
            user_id="user_a",
            session_id="",
            memory_type="factual_truth",
            fact_claim=f"The falcon launch codename for tenant {tenant or 'default'} is Bluebird.",
            content_hash=f"falcon-{tenant}",
            confidence=0.95,
        )
        ids[tenant] = row["id"]
        chroma.add(
            documents=[row["fact_claim"]],
            metadatas=[{"memory_id": row["id"], "user_id": "user_a", "tenant_id": tenant}],
            ids=[row["id"]],
            embeddings=[[0.1, 0.2, 0.3, 0.4]],
        )
    write_stamp(chroma.persist_dir, identity_dict(provider="local", model="hashing", dimension=4, backend="hashing"))
    return cfg, store, chroma, ids


def _recall(cfg, store, chroma, tenant: str, query: str = "falcon launch codename"):
    return asyncio.run(
        recall_context(
            config=cfg,
            store=store,
            embed_provider=_HashEmbed(),
            chroma=chroma,
            user_id="user_a",
            tenant_id=tenant,
            query=query,
        )
    )


def test_empty_tenant_recall_does_not_return_other_tenants(tmp_path: Path):
    cfg, store, chroma, ids = _setup(tmp_path)

    out = _recall(cfg, store, chroma, "")

    assert [hit["id"] for hit in out["hits"]] == [ids[""]]
    assert out["fusion"]["vector_hits"] == 1


def test_named_tenant_recall_stays_in_its_tenant(tmp_path: Path):
    cfg, store, chroma, ids = _setup(tmp_path)

    out = _recall(cfg, store, chroma, "t1")

    assert [hit["id"] for hit in out["hits"]] == [ids["t1"]]


def test_recall_audit_does_not_store_query_text(tmp_path: Path):
    cfg, store, chroma, _ids = _setup(tmp_path)
    secret_query = "zebracorn merger rumor"

    _recall(cfg, store, chroma, "", query=secret_query)

    with sqlite3.connect(truth_db_path(Path(cfg.palace_path))) as conn:
        rows = conn.execute(
            "SELECT summary, before_snap, after_snap FROM audit_log WHERE action='recall_context'"
        ).fetchall()
    assert rows, "recall must still be audited"
    for row in rows:
        assert "zebracorn" not in " ".join(str(col) for col in row)
    assert f"q_len={len(secret_query)}" in rows[-1][0]


def test_legacy_recall_audit_rows_are_scrubbed_on_open(tmp_path: Path):
    cfg, store, _chroma, _ids = _setup(tmp_path)
    store.audit("recall_context", user_id="user_a", target="user_a", summary="q=my bank pin hint hits=1 tokens~9")

    TruthStore(truth_db_path(Path(cfg.palace_path)))

    with sqlite3.connect(truth_db_path(Path(cfg.palace_path))) as conn:
        summaries = [r[0] for r in conn.execute("SELECT summary FROM audit_log WHERE action='recall_context'")]
    assert summaries and all("bank pin" not in s for s in summaries)
    assert any("hits=1" in s for s in summaries)


def test_scrubbed_query_text_is_gone_from_the_database_files(tmp_path: Path):
    cfg, store, _chroma, _ids = _setup(tmp_path)
    store.audit("recall_context", user_id="user_a", target="user_a", summary="q=quokka-passphrase-77 hits=0 tokens~0")

    TruthStore(truth_db_path(Path(cfg.palace_path)))

    db = truth_db_path(Path(cfg.palace_path))
    blobs = b"".join(p.read_bytes() for p in db.parent.glob(db.name + "*") if p.is_file())
    assert b"quokka-passphrase-77" not in blobs
