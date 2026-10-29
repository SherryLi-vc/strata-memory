"""L0 recall must follow the query, return real scores, and honour limit."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.pipeline.commit import commit_memory
from strata_memory.pipeline.recall import recall_context
from strata_memory.storage.truth_store import TruthStore
from tests.recall_probe import FACTS, QUERIES


@pytest.fixture
def env(tmp_path: Path):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(
        palace_path=str(palace),
        mode="personal",
        version="2.2.0",
        cbt={"enabled": True, "mode": "passive", "cooling_hours": 48, "detect_distortions": True},
    )
    save_config(cfg)
    store = TruthStore(truth_db_path(palace))
    return cfg, store


def _commit_probe(cfg, store) -> dict[str, str]:
    ids: dict[str, str] = {}

    async def run():
        for fact in FACTS:
            result = await commit_memory(
                config=cfg,
                store=store,
                embed_provider=None,
                chroma=None,
                user_id="user_001",
                memory_type=fact["memory_type"],
                fact_claim=fact["fact_claim"],
                confidence_score=0.95,
            )
            assert result["status"] == "ok"
            ids[fact["marker"]] = result["memory_id"]

    asyncio.run(run())
    return ids


def test_l0_top1_and_limit(env):
    cfg, store = env
    _commit_probe(cfg, store)

    async def run():
        hits = 0
        for query, marker in QUERIES:
            recall = await recall_context(
                config=cfg,
                store=store,
                embed_provider=None,
                chroma=None,
                user_id="user_001",
                query=query,
                limit=3,
            )
            assert recall["status"] == "ok"
            assert recall["hit_count"] <= 3
            assert recall["hit_count"] == len(recall["hits"])
            assert recall["hits"], query
            top = recall["hits"][0]
            assert marker in top["summary"], query
            assert top["score"] != 1.0
            assert top["score_breakdown"]["why"] != "L0 core profile"
            assert top["score_breakdown"]["relevance"] > 0
            scores = [hit["score"] for hit in recall["hits"]]
            assert all(score != 1.0 for score in scores)
            if len(scores) > 1:
                assert scores[0] > scores[1]
            hits += 1
        assert hits == 4

    asyncio.run(run())


def test_limit_applies_when_every_card_matches(env):
    cfg, store = env

    async def run():
        for index in range(8):
            filler = " ".join(["catalogentry", "alpha"] * (index + 1))
            result = await commit_memory(
                config=cfg,
                store=store,
                embed_provider=None,
                chroma=None,
                user_id="user_001",
                memory_type="factual_truth",
                fact_claim=f"Catalog note {index}: {filler} stays in the palace.",
                confidence_score=0.9,
                supersede=False,
            )
            assert result["status"] == "ok"
        recall = await recall_context(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            user_id="user_001",
            query="catalogentry",
            limit=3,
        )
        assert recall["hit_count"] == 3
        assert len({round(hit["score"], 4) for hit in recall["hits"]}) >= 1
        assert max(hit["score"] for hit in recall["hits"]) > min(hit["score"] for hit in recall["hits"])

    asyncio.run(run())


def test_include_l0_false_drops_core_layers(env):
    cfg, store = env
    _commit_probe(cfg, store)

    async def run():
        recall = await recall_context(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            user_id="user_001",
            query="API gateway listens on port 8017",
            limit=5,
            include_l0=False,
        )
        assert recall["hit_count"] == 0
        assert recall["include_l0"] is False

    asyncio.run(run())


def test_recall_touches_only_returned_cards(env):
    cfg, store = env
    ids = _commit_probe(cfg, store)

    async def run():
        await recall_context(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            user_id="user_001",
            query="API gateway listens on port 8017",
            limit=1,
        )

    asyncio.run(run())
    port = store.get_by_id(ids["port 8017"])
    assert port["usage_count"] >= 1
    for marker, mid in ids.items():
        if marker == "port 8017":
            continue
        assert store.get_by_id(mid)["usage_count"] == 0


def test_shallow_is_ranked_and_limited(env):
    cfg, store = env
    _commit_probe(cfg, store)

    async def run():
        recall = await recall_context(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            user_id="user_001",
            query="dog named Mochi morning walks",
            limit=2,
            context_depth="shallow",
        )
        assert recall["mode"] == "shallow"
        assert recall["hit_count"] <= 2
        assert "Mochi" in recall["hits"][0]["summary"]

    asyncio.run(run())


def test_recall_tool_exposes_include_l0():
    from strata_memory.server import handle_list_tools

    tools = asyncio.run(handle_list_tools())
    recall = next(tool for tool in tools if tool.name == "recall_context")
    prop = recall.inputSchema["properties"]["include_l0"]
    assert prop["type"] == "boolean"
    assert prop["default"] is True
