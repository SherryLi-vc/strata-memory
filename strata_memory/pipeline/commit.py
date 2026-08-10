"""commit_memory pipeline — bulletproof write path (2.0).

Flow (all deterministic after LLM proposes claim):
  1. Quality Kernel validates claim + injects hash/TTL/layer
  2. CBT middleware detects negative schemas + redacts secrets
  3. Dedup against Truth Store (SQLite)
  4. Insert SoT row
  5. Embed + upsert rebuildable vector companion (skip if scratch/no embed)
  6. Audit + trajectory

LLM never touches raw filesystem or raw SQL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..config import Config
from ..embedding import EmbeddingProvider
from ..governance import CBTMiddleware, QualityKernel, ToolError, success_payload
from ..storage.chroma import ChromaStore
from ..storage.truth_store import TruthStore


async def commit_memory(
    *,
    config: Config,
    store: TruthStore,
    embed_provider: Optional[EmbeddingProvider],
    chroma: Optional[ChromaStore],
    user_id: str,
    memory_type: str,
    fact_claim: str,
    confidence_score: float,
    tenant_id: str = "",
    session_id: str = "",
    room: str = "general",
    context_tags: Optional[list[str]] = None,
    is_scratch: bool = False,
    importance: Optional[float] = None,
) -> dict[str, Any]:
    if not user_id or not str(user_id).strip():
        raise ToolError(
            "MISSING_USER_ID",
            "user_id is required for scope isolation.",
            fix="Pass user_id (stable principal id). Example: user_id='user_001'.",
        )

    tenant_id = tenant_id or config.tenant_id or ""
    kernel = QualityKernel(min_confidence=getattr(config, "min_confidence", 0.4))
    verdict = kernel.validate(
        memory_type=memory_type,
        fact_claim=fact_claim,
        confidence_score=confidence_score,
        is_scratch=is_scratch,
        importance=importance,
    )
    verdict.raise_if_rejected()

    cbt = CBTMiddleware(
        enabled=config.cbt.enabled and config.cbt.detect_distortions,
        cooling_hours=config.cbt.cooling_hours,
    )
    assessment = cbt.assess(verdict.fact_claim)
    claim = assessment.redacted_text or verdict.fact_claim

    # Re-hash after redaction
    content_hash = QualityKernel.content_hash(claim)

    # Dedup: exact content hash within tenant+user
    existing = store.find_by_hash(tenant_id, user_id, content_hash)
    if existing:
        store.touch(existing["id"])
        store.audit(
            "commit_memory_dedup",
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            target=existing["id"],
            summary="Duplicate fact_claim — bumped usage_count",
        )
        return success_payload(
            {
                "memory_id": existing["id"],
                "deduplicated": True,
                "layer": existing["layer"],
                "is_scratch": bool(existing["is_scratch"]),
                "usage_count": existing["usage_count"] + 1,
            },
            message="Duplicate memory — usage_count incremented, no new row.",
        )

    # Negative schema: force scratch/cooling — never L0
    force_scratch = verdict.is_scratch
    layer = verdict.layer
    if assessment.is_negative_schema:
        force_scratch = True
        layer = "scratch"

    row = store.insert_memory(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id or "",
        memory_type=verdict.memory_type,
        fact_claim=claim,
        content_hash=content_hash,
        confidence=verdict.confidence,
        importance=verdict.importance,
        emotional_salience=0.0,  # set below if scoring available
        summary=verdict.summary if claim == verdict.fact_claim else claim[:240],
        detail=claim,
        is_negative_schema=assessment.is_negative_schema,
        is_scratch=force_scratch,
        context_tags=context_tags,
        room=room or "general",
        ttl_seconds=verdict.ttl_seconds,
        layer=layer,
        source="commit_memory",
    )

    # Optional emotional salience (keyword) — deterministic
    try:
        from .scoring import estimate_emotional_salience
        sal = estimate_emotional_salience(claim)
        if sal > 0:
            with store._conn() as conn:
                conn.execute(
                    "UPDATE memories SET emotional_salience=? WHERE id=?",
                    (sal, row["id"]),
                )
            row["emotional_salience"] = sal
    except Exception:
        pass

    # Vector companion — only durable non-negative (or allow negative with flag)
    indexed = False
    if (
        not force_scratch
        and embed_provider is not None
        and chroma is not None
        and not assessment.is_negative_schema
    ):
        try:
            text = f"[{user_id}/{room}] {claim[:2000]}"
            vec = await embed_provider.embed(text)
            chroma.add(
                documents=[text],
                metadatas=[{
                    "memory_id": row["id"],
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "session_id": session_id or "",
                    "memory_type": verdict.memory_type,
                    "layer": layer,
                    "room": room or "general",
                    "confidence": verdict.confidence,
                    "importance": verdict.importance,
                    "is_negative_schema": False,
                    "context_tags": ",".join(context_tags or []),
                    "wing": f"users/{user_id}",
                    "category": _type_to_legacy_category(verdict.memory_type),
                    "date": row["created_at"][:10],
                }],
                ids=[row["id"]],
                embeddings=[vec],
            )
            indexed = True
        except Exception as e:
            # Index failure must NOT roll back SoT — rebuildable companion
            store.audit(
                "index_warning",
                tenant_id=tenant_id,
                user_id=user_id,
                target=row["id"],
                summary=f"Vector index failed (SoT intact): {e}",
            )

    store.audit(
        "commit_memory",
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        target=row["id"],
        summary=f"type={verdict.memory_type} layer={layer} scratch={force_scratch}",
        after=claim[:200],
    )

    return success_payload(
        {
            "memory_id": row["id"],
            "deduplicated": False,
            "memory_type": verdict.memory_type,
            "layer": layer,
            "is_scratch": force_scratch,
            "is_negative_schema": assessment.is_negative_schema,
            "cooling_hours": config.cbt.cooling_hours if assessment.is_negative_schema else 0,
            "ttl_seconds": verdict.ttl_seconds,
            "confidence": verdict.confidence,
            "indexed": indexed,
            "summary": row.get("summary") or claim[:240],
            "cbt_hint": assessment.reframed_hint or None,
        },
        message=(
            "Memory committed to Truth Store (SQLite)."
            + (" Held in cooling sandbox." if assessment.is_negative_schema else "")
            + (" Session scratch — call promote_session to make durable." if force_scratch and not assessment.is_negative_schema else "")
        ),
    )


def _type_to_legacy_category(memory_type: str) -> str:
    return {
        "factual_truth": "fact",
        "user_preference": "preference",
        "procedure_rule": "procedure",
        "episodic_event": "event",
    }.get(memory_type, "fact")


async def promote_session(
    *,
    store: TruthStore,
    config: Config,
    embed_provider: Optional[EmbeddingProvider],
    chroma: Optional[ChromaStore],
    user_id: str,
    session_id: str,
    tenant_id: str = "",
) -> dict[str, Any]:
    """Promote validated scratch memories for a session into durable layers."""
    if not session_id:
        raise ToolError(
            "MISSING_SESSION_ID",
            "session_id is required to promote scratch buffer.",
            fix="Pass the same session_id used when committing scratch memories.",
        )
    tenant_id = tenant_id or config.tenant_id or ""
    ids = store.promote_scratch(tenant_id, user_id, session_id)

    # Re-index newly durable rows
    indexed = 0
    if embed_provider and chroma:
        for mid in ids:
            row = store.get_by_id(mid)
            if not row or row.get("is_negative_schema"):
                continue
            try:
                claim = row["fact_claim"]
                text = f"[{user_id}/{row.get('room','general')}] {claim[:2000]}"
                vec = await embed_provider.embed(text)
                chroma.add(
                    documents=[text],
                    metadatas=[{
                        "memory_id": mid,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "memory_type": row["memory_type"],
                        "layer": row["layer"],
                        "room": row.get("room", "general"),
                        "wing": f"users/{user_id}",
                        "category": _type_to_legacy_category(row["memory_type"]),
                        "date": (row.get("created_at") or "")[:10],
                        "is_negative_schema": False,
                        "context_tags": "",
                    }],
                    ids=[mid],
                    embeddings=[vec],
                )
                indexed += 1
            except Exception:
                continue

    store.audit(
        "promote_session",
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        target=session_id,
        summary=f"promoted={len(ids)} indexed={indexed}",
    )
    return success_payload(
        {"promoted_ids": ids, "count": len(ids), "indexed": indexed},
        message=f"Promoted {len(ids)} scratch memories to durable store.",
    )
