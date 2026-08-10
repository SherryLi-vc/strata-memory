"""strata_rebuild_index — destroy & rebuild vector companion from SQLite SoT."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

from ..config import Config
from ..embedding import EmbeddingProvider
from ..storage.chroma import ChromaStore
from ..storage.truth_store import TruthStore


async def strata_rebuild_index(
    *,
    config: Config,
    store: TruthStore,
    embed_provider: EmbeddingProvider,
    chroma: ChromaStore,
    confirm: bool = False,
    tenant_id: str = "",
) -> dict[str, Any]:
    """
    Wipe Chroma persist dir and re-embed all active durable memories from SoT.

    Requires confirm=true as a confirmation gate (destructive to index only;
    SQLite SoT is never touched).
    """
    if not confirm:
        return {
            "status": "error",
            "error_code": "CONFIRMATION_REQUIRED",
            "message": "Rebuild is destructive to the vector index.",
            "how_to_fix": "Re-call with confirm=true. SQLite Truth Store is NOT deleted.",
            "retry_safe": True,
        }

    tenant_id = tenant_id or config.tenant_id or ""
    rows = store.iter_for_index(tenant_id=tenant_id)
    persist = chroma.persist_dir

    # Close / wipe companion
    try:
        # Drop collection by wiping directory
        if persist.exists():
            shutil.rmtree(persist)
        persist.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {
            "status": "error",
            "error_code": "WIPE_FAILED",
            "message": str(e),
            "how_to_fix": "Ensure no other process holds the Chroma lock; retry.",
            "retry_safe": True,
        }

    # Re-open store on clean dir
    new_chroma = ChromaStore(persist)
    ok = 0
    failed = 0
    errors: list[str] = []

    for row in rows:
        if row.get("is_negative_schema"):
            continue  # keep negative schemas out of hot index
        try:
            claim = row["fact_claim"]
            text = f"[{row['user_id']}/{row.get('room','general')}] {claim[:2000]}"
            vec = await embed_provider.embed(text)
            new_chroma.add(
                documents=[text],
                metadatas=[{
                    "memory_id": row["id"],
                    "tenant_id": row.get("tenant_id") or "",
                    "user_id": row["user_id"],
                    "session_id": row.get("session_id") or "",
                    "memory_type": row["memory_type"],
                    "layer": row["layer"],
                    "room": row.get("room") or "general",
                    "wing": f"users/{row['user_id']}",
                    "category": {
                        "factual_truth": "fact",
                        "user_preference": "preference",
                        "procedure_rule": "procedure",
                        "episodic_event": "event",
                    }.get(row["memory_type"], "fact"),
                    "date": (row.get("created_at") or "")[:10],
                    "is_negative_schema": False,
                    "context_tags": "",
                    "confidence": row.get("confidence") or 0.5,
                    "importance": row.get("importance") or 0.5,
                }],
                ids=[row["id"]],
                embeddings=[vec],
            )
            ok += 1
        except Exception as e:
            failed += 1
            if len(errors) < 5:
                errors.append(f"{row['id']}: {e}")

    store.audit(
        "strata_rebuild_index",
        tenant_id=tenant_id,
        summary=f"rebuilt ok={ok} failed={failed} source_rows={len(rows)}",
    )

    return {
        "status": "ok",
        "message": f"Vector index rebuilt from SQLite SoT: {ok} indexed, {failed} failed.",
        "source_rows": len(rows),
        "indexed": ok,
        "failed": failed,
        "errors_sample": errors,
        "vector_count": new_chroma.count(),
        "persist_dir": str(persist),
    }
