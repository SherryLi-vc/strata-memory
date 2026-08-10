"""Progressive Recall Funnel (2.0).

Never dump full Markdown into the LLM context.

Stage 1 — recall_context:
  Hybrid RRF (vector + FTS) → return [{id, summary, score, layer, type}]
  Plus compact L0 profile summaries (token-budgeted).

Stage 2 — expand_memory_detail(id):
  Return full detail for a single id after the model opts in.
"""

from __future__ import annotations

from typing import Any, Optional

from ..config import Config
from ..embedding import EmbeddingProvider
from ..governance import CBTMiddleware, ToolError, success_payload
from ..storage.chroma import ChromaStore
from ..storage.truth_store import TruthStore


def _rrf_fuse(
    ranked_lists: list[list[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over ordered id lists."""
    scores: dict[str, float] = {}
    for lst in ranked_lists:
        for rank, doc_id in enumerate(lst):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


async def recall_context(
    *,
    config: Config,
    store: TruthStore,
    embed_provider: Optional[EmbeddingProvider],
    chroma: Optional[ChromaStore],
    user_id: str,
    query: str,
    tenant_id: str = "",
    session_id: str = "",
    limit: int = 8,
    include_l0: bool = True,
    context_depth: str = "deep",
) -> dict[str, Any]:
    if not user_id or not str(user_id).strip():
        raise ToolError(
            "MISSING_USER_ID",
            "user_id is required.",
            fix="Pass user_id for principal isolation.",
        )
    if not query or not str(query).strip():
        raise ToolError(
            "MISSING_QUERY",
            "query is required for progressive recall.",
            fix="Pass a short intent query, e.g. 'coding IDE preferences'.",
        )

    tenant_id = tenant_id or config.tenant_id or ""
    limit = max(1, min(int(limit), 20))
    cbt = CBTMiddleware(
        enabled=config.cbt.enabled,
        cooling_hours=config.cbt.cooling_hours,
    )

    # ── L0 compact profiles (from SoT, not Markdown dump) ──
    l0_cards: list[dict[str, Any]] = []
    if include_l0:
        l0_rows = store.list_active(
            tenant_id=tenant_id,
            user_id=user_id,
            layers=["L0"],
            include_scratch=False,
            exclude_negative=True,
            limit=12,
        )
        budget = config.l0_token_budget
        used = 0
        for r in l0_rows:
            card = {
                "id": r["id"],
                "summary": r.get("summary") or r["fact_claim"][:240],
                "memory_type": r["memory_type"],
                "layer": "L0",
                "score": 1.0,
            }
            cost = _estimate_tokens(card["summary"])
            if used + cost > budget:
                break
            l0_cards.append(card)
            used += cost
            store.touch(r["id"])

    # ── Scratch (current session only) ──
    scratch_cards: list[dict[str, Any]] = []
    if session_id:
        scratch_rows = store.list_active(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            layers=["scratch"],
            include_scratch=True,
            limit=5,
        )
        for r in scratch_rows:
            if r.get("session_id") != session_id and r.get("is_scratch"):
                continue
            scratch_cards.append({
                "id": r["id"],
                "summary": r.get("summary") or r["fact_claim"][:240],
                "memory_type": r["memory_type"],
                "layer": "scratch",
                "score": 0.5,
            })

    hits: list[dict[str, Any]] = []
    if context_depth == "shallow":
        # L0 + scratch only
        all_cards = l0_cards + scratch_cards
        token_est = sum(_estimate_tokens(c["summary"]) for c in all_cards)
        return success_payload(
            {
                "query": query,
                "hits": all_cards,
                "hit_count": len(all_cards),
                "token_estimate": token_est,
                "mode": "shallow",
                "note": "Summaries only. Call expand_memory_detail(id) for full text.",
            },
            message=f"Shallow recall: {len(all_cards)} cards.",
        )

    # ── Hybrid retrieval ──
    vector_ids: list[str] = []
    fts_ids: list[str] = []

    # Vector branch
    if embed_provider and chroma:
        try:
            qvec = await embed_provider.embed(query)
            where: dict[str, Any] = {"user_id": user_id}
            if tenant_id:
                where = {
                    "$and": [
                        {"user_id": user_id},
                        {"tenant_id": tenant_id},
                    ]
                }
            vres = chroma.query(query_embedding=qvec, top_k=limit * 3, where=where)
            vector_ids = [r["id"] for r in vres if r.get("id")]
        except Exception:
            vector_ids = []

    # FTS branch
    try:
        fres = store.fts_search(query, tenant_id=tenant_id, user_id=user_id, limit=limit * 3)
        fts_ids = [r["id"] for r in fres]
    except Exception:
        fts_ids = []

    fused = _rrf_fuse([vector_ids, fts_ids])
    # Fall back to importance order if both empty
    if not fused:
        fallback = store.list_active(
            tenant_id=tenant_id,
            user_id=user_id,
            layers=["L1", "L2"],
            limit=limit,
        )
        fused = [(r["id"], 0.1) for r in fallback]

    seen = {c["id"] for c in l0_cards}
    for mid, score in fused:
        if mid in seen:
            continue
        row = store.get_by_id(mid)
        if not row or row.get("status") != "active":
            continue
        if row.get("is_scratch") and row.get("session_id") != session_id:
            continue
        summary = row.get("summary") or row["fact_claim"][:240]
        if row.get("is_negative_schema") and config.cbt.enabled:
            if config.cbt.mode == "active":
                continue  # hide in active mode
            if config.cbt.mode == "passive":
                summary = cbt.defusion_frame(summary)
        hits.append({
            "id": mid,
            "summary": summary[:400],
            "memory_type": row["memory_type"],
            "layer": row["layer"],
            "score": round(score, 4),
            "is_negative_schema": bool(row.get("is_negative_schema")),
        })
        seen.add(mid)
        store.touch(mid)
        if len(hits) >= limit:
            break

    all_cards = l0_cards + scratch_cards + hits
    # Cap total payload tokens
    max_tokens = config.l0_token_budget + config.l2_token_budget
    trimmed: list[dict[str, Any]] = []
    used = 0
    for c in all_cards:
        cost = _estimate_tokens(c["summary"])
        if used + cost > max_tokens:
            break
        trimmed.append(c)
        used += cost

    store.audit(
        "recall_context",
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        target=user_id,
        summary=f"q={query[:80]} hits={len(trimmed)} tokens~{used}",
    )

    return success_payload(
        {
            "query": query,
            "hits": trimmed,
            "hit_count": len(trimmed),
            "token_estimate": used,
            "mode": "deep",
            "fusion": {
                "vector_hits": len(vector_ids),
                "fts_hits": len(fts_ids),
            },
            "note": (
                "Progressive disclosure: only id+summary+score returned. "
                "Call expand_memory_detail(memory_id=...) for full detail on a hit."
            ),
        },
        message=f"Recall funnel returned {len(trimmed)} cards (~{used} tokens).",
    )


def expand_memory_detail(
    *,
    store: TruthStore,
    memory_id: str,
    user_id: str,
    tenant_id: str = "",
    config: Optional[Config] = None,
) -> dict[str, Any]:
    """Stage-2 detail expansion — scope-checked."""
    if not memory_id:
        raise ToolError(
            "MISSING_MEMORY_ID",
            "memory_id is required.",
            fix="Pass an id from recall_context hits, e.g. memory_id='a1b2c3d4e5f6'.",
        )
    row = store.get_by_id(memory_id)
    if not row:
        raise ToolError(
            "MEMORY_NOT_FOUND",
            f"No memory with id={memory_id!r}.",
            fix="Re-run recall_context and use an id from the hits list.",
            retry_safe=True,
        )
    # Scope isolation — hard fail on cross-user access
    if row["user_id"] != user_id:
        raise ToolError(
            "SCOPE_VIOLATION",
            "Memory does not belong to this user_id.",
            fix="Use the same user_id that owns the memory. Cross-principal expand is forbidden.",
            retry_safe=False,
        )
    tid = tenant_id or (config.tenant_id if config else "") or ""
    if (row.get("tenant_id") or "") != (tid or ""):
        # Allow empty-empty; otherwise block
        if row.get("tenant_id") or tid:
            raise ToolError(
                "SCOPE_VIOLATION",
                "Memory tenant_id does not match.",
                fix="Pass the correct tenant_id for this principal.",
                retry_safe=False,
            )

    store.touch(memory_id)
    detail = row.get("detail") or row.get("fact_claim") or ""
    # Cap detail dump
    MAX_DETAIL = 4000
    truncated = len(detail) > MAX_DETAIL
    if truncated:
        detail = detail[:MAX_DETAIL] + "\n\n[truncated at 4000 chars]"

    if row.get("is_negative_schema") and config and config.cbt.enabled:
        cbt = CBTMiddleware(enabled=True)
        detail = cbt.defusion_frame(detail)

    store.audit(
        "expand_memory_detail",
        tenant_id=tid,
        user_id=user_id,
        target=memory_id,
        summary=f"expanded chars={len(detail)}",
    )

    return success_payload(
        {
            "memory_id": memory_id,
            "memory_type": row["memory_type"],
            "layer": row["layer"],
            "fact_claim": row["fact_claim"],
            "detail": detail,
            "summary": row.get("summary"),
            "confidence": row.get("confidence"),
            "importance": row.get("importance"),
            "is_negative_schema": bool(row.get("is_negative_schema")),
            "context_tags": row.get("context_tags"),
            "created_at": row.get("created_at"),
            "truncated": truncated,
            "tokens_approx": _estimate_tokens(detail),
        },
        message="Full detail loaded under progressive disclosure.",
    )
