"""commit_memory pipeline — bulletproof write path (2.0 + 3.0 Slice C).

Flow:
  1. Quality Kernel (+ typed TTL/status/validator_kind defaults)
  2. CBT middleware
  3. Exact hash dedup
  4. Near-dup FTS → supersede version chain
  5. Insert SoT with provenance
  6. Optional embed
"""

from __future__ import annotations

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
    entity: str = "",
    authority: str = "",
    sensitivity: str = "",
    supersede: bool = True,
    provenance: Optional[dict] = None,
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
    meta = verdict.metadata or {}

    cbt = CBTMiddleware(
        enabled=config.cbt.enabled and config.cbt.detect_distortions,
        cooling_hours=config.cbt.cooling_hours,
    )
    assessment = cbt.assess(verdict.fact_claim)
    claim = assessment.redacted_text or verdict.fact_claim
    content_hash = QualityKernel.content_hash(claim)

    # Exact dedup
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
                "superseded": False,
                "layer": existing["layer"],
                "is_scratch": bool(existing["is_scratch"]),
                "usage_count": existing["usage_count"] + 1,
                "validator_kind": meta.get("validator_kind"),
                "ttl_days": meta.get("ttl_days"),
            },
            message="Duplicate memory — usage_count incremented, no new row.",
        )

    # Near-dup → supersede (version chain)
    supersedes_id = None
    near = []
    if supersede and not verdict.is_scratch:
        near = store.find_near_duplicates(
            tenant_id,
            user_id,
            claim,
            memory_type=verdict.memory_type,
            limit=5,
            min_token_overlap=0.55,
        )
        # Prefer highest jaccard that is not identical hash (already handled)
        for cand in near:
            if cand.get("content_hash") == content_hash:
                continue
            if float(cand.get("jaccard") or 0) >= 0.55:
                supersedes_id = cand["id"]
                break

    force_scratch = verdict.is_scratch
    layer = verdict.layer
    if assessment.is_negative_schema:
        force_scratch = True
        layer = "scratch"
        supersedes_id = None  # never supersede L0 via negative content

    prov = dict(provenance or {})
    prov.setdefault("session_id", session_id or "")
    prov.setdefault("pipeline", "commit_memory")
    if supersedes_id:
        prov["supersede_of"] = supersedes_id
        if near:
            prov["near_jaccard"] = near[0].get("jaccard")

    row = store.insert_memory(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id or "",
        memory_type=verdict.memory_type,
        fact_claim=claim,
        content_hash=content_hash,
        confidence=verdict.confidence,
        importance=verdict.importance,
        emotional_salience=0.0,
        summary=verdict.summary if claim == verdict.fact_claim else claim[:240],
        detail=claim,
        is_negative_schema=assessment.is_negative_schema,
        is_scratch=force_scratch,
        context_tags=context_tags,
        room=room or "general",
        ttl_seconds=verdict.ttl_seconds,
        ttl_days=meta.get("ttl_days"),
        layer=layer,
        source="commit_memory",
        supersedes_id=supersedes_id,
        authority=authority or meta.get("authority") or "agent",
        sensitivity=sensitivity or meta.get("sensitivity") or "normal",
        entity=entity or "",
        validator_kind=meta.get("validator_kind") or "quality_kernel",
        provenance=prov,
        status=meta.get("status") or "active",
    )

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
                    "entity": entity or "",
                    "wing": f"users/{user_id}",
                    "category": _type_to_legacy_category(verdict.memory_type),
                    "date": row["created_at"][:10],
                }],
                ids=[row["id"]],
                embeddings=[vec],
            )
            indexed = True
            # Drop superseded vector companion if present
            if supersedes_id:
                try:
                    chroma.delete_by_ids([supersedes_id])
                except Exception:
                    pass
        except Exception as e:
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
        summary=(
            f"type={verdict.memory_type} layer={layer} scratch={force_scratch} "
            f"supersedes={supersedes_id or '-'}"
        ),
        after=claim[:200],
    )

    msg = "Memory committed to Truth Store (SQLite)."
    if supersedes_id:
        msg += f" Superseded prior memory {supersedes_id} (version chain)."
    if assessment.is_negative_schema:
        msg += " Held in cooling sandbox."
    elif force_scratch:
        msg += " Session scratch — call promote_session to make durable."

    return success_payload(
        {
            "memory_id": row["id"],
            "deduplicated": False,
            "superseded": bool(supersedes_id),
            "supersedes_id": supersedes_id,
            "memory_type": verdict.memory_type,
            "layer": layer,
            "is_scratch": force_scratch,
            "is_negative_schema": assessment.is_negative_schema,
            "cooling_hours": config.cbt.cooling_hours if assessment.is_negative_schema else 0,
            "ttl_seconds": verdict.ttl_seconds,
            "ttl_days": meta.get("ttl_days"),
            "memory_status": meta.get("status", "active"),
            "validator_kind": meta.get("validator_kind"),
            "authority": authority or meta.get("authority"),
            "sensitivity": sensitivity or meta.get("sensitivity"),
            "entity": entity or None,
            "confidence": verdict.confidence,
            "indexed": indexed,
            "summary": row.get("summary") or claim[:240],
            "cbt_hint": assessment.reframed_hint or None,
            "provenance": prov,
        },
        message=msg,
    )


def _type_to_legacy_category(memory_type: str) -> str:
    return {
        "factual_truth": "fact",
        "user_preference": "preference",
        "procedure_rule": "procedure",
        "episodic_event": "event",
        "decision_record": "goal",
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
                        "entity": row.get("entity") or "",
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
