"""Integration coverage for rebuilding an unstamped, pre-upgrade Chroma index."""

from __future__ import annotations

import asyncio
from pathlib import Path

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.embedder_stamp import identity_dict, read_stamp, write_stamp
from strata_memory.ops.rebuild import strata_rebuild_index
from strata_memory.storage.chroma import ChromaStore
from strata_memory.storage.truth_store import TruthStore


class _HashEmbed:
    backend = "hashing"

    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


class _FailingEmbed(_HashEmbed):
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


def _legacy_index(tmp_path: Path):
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
    row = store.insert_memory(
        tenant_id="",
        user_id="user_a",
        session_id="",
        memory_type="factual_truth",
        fact_claim="Legacy memory created before embedder stamps were introduced.",
        content_hash="legacy-memory",
        confidence=0.95,
    )
    chroma = ChromaStore(palace / "l2_vector")
    chroma.add(
        documents=[row["fact_claim"]],
        metadatas=[{"memory_id": row["id"]}],
        ids=[row["id"]],
        embeddings=[[0.1, 0.2, 0.3, 0.4]],
    )
    # This is the main-era state: durable rows and vectors exist, no stamp.
    assert read_stamp(chroma.persist_dir) is None
    return cfg, store, chroma


def test_rebuild_upgrades_legacy_unstamped_index_and_stamps_only_after_success(tmp_path: Path):
    cfg, store, chroma = _legacy_index(tmp_path)

    result = asyncio.run(
        strata_rebuild_index(
            config=cfg,
            store=store,
            embed_provider=_HashEmbed(),
            chroma=chroma,
            confirm=True,
        )
    )

    assert result["status"] == "ok"
    assert result["indexed"] == 1
    assert result["failed"] == 0
    assert chroma.count() == 1
    assert read_stamp(chroma.persist_dir) == identity_dict(
        provider="local", model="hashing", dimension=4, backend="hashing"
    )


def test_failed_rebuild_returns_error_and_does_not_write_stamp(tmp_path: Path):
    cfg, store, chroma = _legacy_index(tmp_path)
    write_stamp(
        chroma.persist_dir,
        identity_dict(provider="local", model="old-model", dimension=4, backend="hashing"),
    )

    result = asyncio.run(
        strata_rebuild_index(
            config=cfg,
            store=store,
            embed_provider=_FailingEmbed(),
            chroma=chroma,
            confirm=True,
        )
    )

    assert result["status"] == "error"
    assert result["error_code"] == "REBUILD_INCOMPLETE"
    assert result["failed"] == 1
    assert read_stamp(chroma.persist_dir) is None


def _multi_tenant_index(tmp_path: Path):
    """Three tenants ('' , t1, t2), all indexed and stamped by a full rebuild."""
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
    sizes = {"": 3, "t1": 2, "t2": 4}
    for tenant, n in sizes.items():
        for i in range(n):
            store.insert_memory(
                tenant_id=tenant,
                user_id="user_a",
                session_id="",
                memory_type="factual_truth",
                fact_claim=f"Tenant {tenant or 'default'} fact number {i} about the falcon project.",
                content_hash=f"h-{tenant}-{i}",
                confidence=0.9,
            )
    chroma = ChromaStore(palace / "l2_vector")
    return cfg, store, chroma, sizes


def _tenant_vectors(chroma: ChromaStore, tenant: str) -> int:
    got = chroma.client.get_collection("strata_memory").get(where={"tenant_id": tenant})
    return len(got["ids"])


def test_tenant_scoped_rebuild_keeps_other_tenants_vectors(tmp_path: Path):
    cfg, store, chroma, sizes = _multi_tenant_index(tmp_path)
    full = asyncio.run(
        strata_rebuild_index(config=cfg, store=store, embed_provider=_HashEmbed(), chroma=chroma, confirm=True)
    )
    assert full["status"] == "ok"
    assert chroma.count() == sum(sizes.values())

    scoped = asyncio.run(
        strata_rebuild_index(
            config=cfg, store=store, embed_provider=_HashEmbed(), chroma=chroma, confirm=True, tenant_id="t1"
        )
    )

    assert scoped["status"] == "ok", scoped
    assert scoped["scope"] == "tenant"
    assert scoped["indexed"] == sizes["t1"]
    assert chroma.count() == sum(sizes.values())
    assert _tenant_vectors(chroma, "") == sizes[""]
    assert _tenant_vectors(chroma, "t1") == sizes["t1"]
    assert _tenant_vectors(chroma, "t2") == sizes["t2"]
    assert read_stamp(chroma.persist_dir) is not None


def test_tenant_scoped_rebuild_drops_stale_vectors_of_that_tenant_only(tmp_path: Path):
    cfg, store, chroma, sizes = _multi_tenant_index(tmp_path)
    asyncio.run(strata_rebuild_index(config=cfg, store=store, embed_provider=_HashEmbed(), chroma=chroma, confirm=True))
    # An orphan vector for t1 (row no longer in SoT) and one for t2.
    for tenant in ("t1", "t2"):
        chroma.add(
            documents=["orphan"],
            metadatas=[{"memory_id": f"orphan-{tenant}", "tenant_id": tenant, "user_id": "user_a"}],
            ids=[f"orphan-{tenant}"],
            embeddings=[[0.1, 0.2, 0.3, 0.4]],
        )

    scoped = asyncio.run(
        strata_rebuild_index(
            config=cfg, store=store, embed_provider=_HashEmbed(), chroma=chroma, confirm=True, tenant_id="t1"
        )
    )

    assert scoped["status"] == "ok", scoped
    assert _tenant_vectors(chroma, "t1") == sizes["t1"]
    assert _tenant_vectors(chroma, "t2") == sizes["t2"] + 1  # t2 untouched, orphan included


def test_tenant_scoped_rebuild_on_unstamped_index_escalates_to_full(tmp_path: Path):
    """Without a matching stamp the other tenants' vectors are unusable; rebuild them too instead of dropping them."""
    cfg, store, chroma, sizes = _multi_tenant_index(tmp_path)
    # Legacy (unstamped) vectors for t2 only.
    for row in store.iter_for_index(tenant_id="t2"):
        chroma.add(
            documents=[row["fact_claim"]],
            metadatas=[{"memory_id": row["id"], "tenant_id": "t2", "user_id": "user_a"}],
            ids=[row["id"]],
            embeddings=[[0.4, 0.3, 0.2, 0.1]],
        )
    assert read_stamp(chroma.persist_dir) is None

    result = asyncio.run(
        strata_rebuild_index(
            config=cfg, store=store, embed_provider=_HashEmbed(), chroma=chroma, confirm=True, tenant_id="t1"
        )
    )

    assert result["status"] == "ok", result
    assert result["scope"] == "all"
    assert result["escalated_from_tenant"] == "t1"
    assert chroma.count() == sum(sizes.values())
    assert _tenant_vectors(chroma, "t2") == sizes["t2"]
    assert read_stamp(chroma.persist_dir) is not None


def test_doctor_is_not_healthy_after_a_fully_failed_rebuild(tmp_path: Path):
    from strata_memory.ops.doctor import strata_doctor

    cfg, store, chroma = _legacy_index(tmp_path)
    result = asyncio.run(
        strata_rebuild_index(config=cfg, store=store, embed_provider=_FailingEmbed(), chroma=chroma, confirm=True)
    )
    assert result["status"] == "error"

    report = strata_doctor(config=cfg, store=store, chroma=chroma)

    assert report["healthy"] is False
    assert report["status"] == "degraded"
    codes = {issue["code"] for issue in report["issues"]}
    assert "INDEX_INCOMPLETE" in codes


def test_doctor_flags_partially_missing_vectors(tmp_path: Path):
    from strata_memory.ops.doctor import strata_doctor

    cfg, store, chroma, sizes = _multi_tenant_index(tmp_path)
    asyncio.run(strata_rebuild_index(config=cfg, store=store, embed_provider=_HashEmbed(), chroma=chroma, confirm=True))
    assert strata_doctor(config=cfg, store=store, chroma=chroma)["healthy"] is True

    victim = store.iter_for_index(tenant_id="t2")[0]["id"]
    chroma.delete_by_ids([victim])
    report = strata_doctor(config=cfg, store=store, chroma=chroma)

    assert report["healthy"] is False
    assert "INDEX_INCOMPLETE" in {issue["code"] for issue in report["issues"]}
