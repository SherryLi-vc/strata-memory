#!/usr/bin/env python3
"""Reproducible L0 recall benchmark.

The literal set reuses surface words from the six claims. A 4/4 on that set
is lexical overlap, not paraphrase quality. The paraphrase set shares no
distinctive tokens; the hashing backend is not expected to rank those.

    uv run python scripts/recall_benchmark.py

No API key. The semantic block runs only when fastembed is installed.
Otherwise it is reported as not_run. This script does not download weights.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from probe_facts import FACTS, PARAPHRASES, QUERIES

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.pipeline.commit import commit_memory
from strata_memory.pipeline.recall import recall_context
from strata_memory.storage.truth_store import TruthStore


def _score_query(recall: dict, marker: str) -> dict:
    hits = recall.get("hits") or []
    scores = [hit.get("score") for hit in hits]
    summaries = [hit.get("summary") or "" for hit in hits]
    return {
        "marker": marker,
        "top1_ok": bool(summaries) and marker in summaries[0],
        "hit_count": len(hits),
        "scores": scores,
        "top_summary": summaries[0] if summaries else "",
        "limit_ok": len(hits) <= 3,
    }


async def _ask(cfg, store, queries: list[tuple[str, str]]) -> dict:
    rows = []
    for query, marker in queries:
        recall = await recall_context(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            user_id="bench_user",
            query=query,
            limit=3,
            include_l0=True,
        )
        row = _score_query(recall, marker)
        row["query"] = query
        rows.append(row)
    top1 = sum(1 for row in rows if row["top1_ok"])
    return {
        "backend": "lexical-bm25 (no embedding model; hashing is not used)",
        "condition": "See suite name. Literal queries share surface tokens with the claims.",
        "top1_hits": top1,
        "top1_of": len(queries),
        "limit_honoured": all(row["limit_ok"] for row in rows),
        "results": rows,
    }


def _semantic_status() -> dict:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return {
            "status": "not_run",
            "reason": (
                "fastembed is not installed. The default install uses hashing, which matches tokens, not paraphrases."
            ),
        }
    return {
        "status": "not_run",
        "reason": (
            "fastembed is installed, but this script does not load it. "
            "A first load downloads weights and is not an offline benchmark."
        ),
    }


async def _run(palace: Path) -> dict:
    ensure_palace(palace)
    cfg = Config(
        palace_path=str(palace),
        mode="personal",
        version="2.2.0",
        cbt={"enabled": True, "mode": "passive", "cooling_hours": 48, "detect_distortions": True},
    )
    save_config(cfg)
    store = TruthStore(truth_db_path(palace))
    for fact in FACTS:
        result = await commit_memory(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            user_id="bench_user",
            memory_type=fact["memory_type"],
            fact_claim=fact["fact_claim"],
            confidence_score=0.95,
        )
        if result.get("status") != "ok":
            raise SystemExit(f"commit failed: {result}")

    literal = await _ask(cfg, store, QUERIES)
    paraphrase = await _ask(cfg, store, PARAPHRASES)
    literal["condition"] = "Queries reuse surface tokens from the claims. This is not paraphrase quality."
    paraphrase["condition"] = (
        "Queries do not reuse distinctive claim tokens. Hashing and this lexical ranker can miss them."
    )
    paraphrase["backend"] = literal["backend"]
    return {
        "facts": len(FACTS),
        "limit": 3,
        "note": "Do not quote a single 4/4 without naming the suite and backend.",
        "literal_overlap": literal,
        "paraphrase": paraphrase,
        "semantic": _semantic_status(),
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="strata-recall-bench-") as tmp:
        report = asyncio.run(_run(Path(tmp) / "palace"))
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
