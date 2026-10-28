#!/usr/bin/env python3
"""Reproducible L0 recall benchmark.

Loads 6 facts (factual_truth, user_preference, procedure_rule) and runs 4
queries at limit=3. Prints JSON with top-1 accuracy, whether every result
respects limit, and the score spread.

    uv run python scripts/recall_benchmark.py

No network and no API key. Embeddings are left unset so the run measures
lexical ranking of L0 rows, which is the path the 2026-10-29 teardown failed.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from probe_facts import FACTS, QUERIES

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.pipeline.commit import commit_memory
from strata_memory.pipeline.recall import recall_context
from strata_memory.storage.truth_store import TruthStore


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

    rows = []
    top1 = 0
    limit_ok = True
    for query, marker in QUERIES:
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
        hits = recall.get("hits") or []
        scores = [hit.get("score") for hit in hits]
        summaries = [hit.get("summary") or "" for hit in hits]
        hit_ok = bool(summaries) and marker in summaries[0]
        top1 += int(hit_ok)
        if len(hits) > 3:
            limit_ok = False
        rows.append(
            {
                "query": query,
                "marker": marker,
                "top1_ok": hit_ok,
                "hit_count": len(hits),
                "scores": scores,
                "top_summary": summaries[0] if summaries else "",
            }
        )
    flat_scores = [score for row in rows for score in row["scores"] if isinstance(score, (int, float))]
    return {
        "facts": len(FACTS),
        "queries": len(QUERIES),
        "limit": 3,
        "top1_hits": top1,
        "top1_of": len(QUERIES),
        "limit_honoured": limit_ok,
        "scores_all_one": bool(flat_scores) and all(score == 1.0 for score in flat_scores),
        "score_min": min(flat_scores) if flat_scores else None,
        "score_max": max(flat_scores) if flat_scores else None,
        "results": rows,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="strata-recall-bench-") as tmp:
        report = asyncio.run(_run(Path(tmp) / "palace"))
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
