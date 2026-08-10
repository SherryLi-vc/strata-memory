"""Progressive Recall Funnel (2.0 + 3.0 multi-signal rerank)."""

from __future__ import annotations

from typing import Any, Optional

from ..config import Config
from ..embedding import EmbeddingProvider
from ..governance import CBTMiddleware, ToolError, success_payload
from ..pipeline.scoring_signals import multi_signal_score
from ..storage.chroma import ChromaStore
from ..storage.truth_store import TruthStore


def _rrf_fuse(
    ranked_lists: list[list[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
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
    current_turn_only: bool = False,
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
    filter_log: list[dict[str, str]] = []

    # ── L0 ──
    l0_cards: list[dict[str, Any]] = []
    if include_l0 and not current_turn_only:
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
                "score_breakdown": {
                    "recency": 1.0,
                    "relevance": 1.0,
                    "importance": float(r.get("importance") or 0.7),
                    "usage_boost": 0.0,
                    "freshness": 1.0,
                    "rrf_raw": 1.0,
                    "final": 1.0,
                    "why": "L0 core profile",
                },
                "entity": r.get("entity") or None,
            }
            cost = _estimate_tokens(card["summary"])
            if used + cost > budget:
                filter_log.append({"id": r["id"], "reason": "l0_token_budget"})
                break
            l0_cards.append(card)
            used += cost
            store.touch(r["id"])

    # ── Scratch (this session) ──
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
            if r.get("session_id") != session_id:
                filter_log.append({"id": r["id"], "reason": "scratch_other_session"})
                continue
            scratch_cards.append({
                "id": r["id"],
                "summary": r.get("summary") or r["fact_claim"][:240],
                "memory_type": r["memory_type"],
                "layer": "scratch",
                "score": 0.55,
                "score_breakdown": {
                    "recency": 1.0,
                    "relevance": 0.5,
                    "importance": float(r.get("importance") or 0.5),
                    "usage_boost": 0.0,
                    "freshness": 1.0,
                    "rrf_raw": 0.0,
                    "final": 0.55,
                    "why": "current session scratch",
                },
                "entity": r.get("entity") or None,
            })

    if context_depth == "shallow":
        all_cards = l0_cards + scratch_cards
        token_est = sum(_estimate_tokens(c["summary"]) for c in all_cards)
        return success_payload(
            {
                "query": query,
                "hits": all_cards,
                "hit_count": len(all_cards),
                "token_estimate": token_est,
                "mode": "shallow",
                "filtered": filter_log[:20],
                "note": "Summaries only. Call expand_memory_detail(id) for full text.",
            },
            message=f"Shallow recall: {len(all_cards)} cards.",
        )

    # ── Hybrid RRF ──
    vector_ids: list[str] = []
    fts_ids: list[str] = []

    if embed_provider and chroma:
        try:
            qvec = await embed_provider.embed(query)
            where: dict[str, Any] = {"user_id": user_id}
            if tenant_id:
                where = {"$and": [{"user_id": user_id}, {"tenant_id": tenant_id}]}
            vres = chroma.query(query_embedding=qvec, top_k=limit * 4, where=where)
            vector_ids = [r["id"] for r in vres if r.get("id")]
        except Exception:
            vector_ids = []

    try:
        fres = store.fts_search(query, tenant_id=tenant_id, user_id=user_id, limit=limit * 4)
        fts_ids = [r["id"] for r in fres]
    except Exception:
        fts_ids = []

    fused = _rrf_fuse([vector_ids, fts_ids])
    if not fused:
        fallback = store.list_active(
            tenant_id=tenant_id,
            user_id=user_id,
            layers=["L1", "L2"],
            limit=limit * 2,
        )
        fused = [(r["id"], 0.1) for r in fallback]

    max_rrf = max((s for _, s in fused), default=1.0) or 1.0
    ranked: list[tuple[float, dict[str, Any], dict[str, float]]] = []
    seen = {c["id"] for c in l0_cards}

    for mid, rrf_s in fused:
        if mid in seen:
            continue
        row = store.get_by_id(mid)
        if not row or row.get("status") != "active":
            filter_log.append({"id": mid, "reason": "inactive_or_missing"})
            continue
        # Scratch from other sessions blocked
        if row.get("is_scratch") and row.get("session_id") != session_id:
            filter_log.append({"id": mid, "reason": "scratch_other_session"})
            continue
        # current_turn_only: prefer this session durable + scratch (still allow L0 above)
        if current_turn_only and session_id:
            if row.get("session_id") and row.get("session_id") != session_id:
                filter_log.append({"id": mid, "reason": "not_current_session"})
                continue

        if row.get("is_negative_schema") and config.cbt.enabled and config.cbt.mode == "active":
            filter_log.append({"id": mid, "reason": "cbt_active_hidden"})
            continue

        final, breakdown = multi_signal_score(row, rrf_score=rrf_s, max_rrf=max_rrf)
        # Session boost for same session durable
        if session_id and row.get("session_id") == session_id:
            final *= 1.15
            breakdown["session_boost"] = 1.15
            breakdown["final"] = round(final, 4)
        breakdown["why"] = _why_selected(breakdown, row)

        summary = row.get("summary") or row["fact_claim"][:240]
        if row.get("is_negative_schema") and config.cbt.enabled and config.cbt.mode == "passive":
            summary = cbt.defusion_frame(summary)

        card = {
            "id": mid,
            "summary": summary[:400],
            "memory_type": row["memory_type"],
            "layer": row["layer"],
            "score": round(final, 4),
            "score_breakdown": breakdown,
            "is_negative_schema": bool(row.get("is_negative_schema")),
            "entity": row.get("entity") or None,
            "supersedes_id": row.get("supersedes_id") or None,
        }
        ranked.append((final, card, breakdown))
        seen.add(mid)

    ranked.sort(key=lambda x: x[0], reverse=True)
    hits = [c for _, c, _ in ranked[:limit]]
    for _, c, _ in ranked[limit:]:
        filter_log.append({"id": c["id"], "reason": "below_top_k"})

    for c in hits:
        store.touch(c["id"])

    all_cards = l0_cards + scratch_cards + hits
    max_tokens = config.l0_token_budget + config.l2_token_budget
    trimmed: list[dict[str, Any]] = []
    used = 0
    for c in all_cards:
        cost = _estimate_tokens(c["summary"])
        if used + cost > max_tokens:
            filter_log.append({"id": c["id"], "reason": "token_waterline"})
            continue
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
                "rerank": "multi_signal_v3",
            },
            "filtered": filter_log[:30],
            "note": (
                "Progressive disclosure: id+summary+score+score_breakdown. "
                "Call expand_memory_detail for full detail."
            ),
        },
        message=f"Recall funnel returned {len(trimmed)} cards (~{used} tokens).",
    )


def _why_selected(breakdown: dict[str, float], row: dict[str, Any]) -> str:
    parts = []
    if breakdown.get("relevance", 0) >= 0.5:
        parts.append("high relevance")
    if breakdown.get("recency", 0) >= 0.7:
        parts.append("recent")
    if breakdown.get("importance", 0) >= 0.7:
        parts.append("important")
    if breakdown.get("usage_boost", 0) >= 0.3:
        parts.append("frequently used")
    if row.get("layer") == "L0":
        parts.append("core layer")
    if not parts:
        parts.append("matched query")
    return ", ".join(parts)


def expand_memory_detail(
    *,
    store: TruthStore,
    memory_id: str,
    user_id: str,
    tenant_id: str = "",
    config: Optional[Config] = None,
) -> dict[str, Any]:
    if not memory_id:
        raise ToolError(
            "MISSING_MEMORY_ID",
            "memory_id is required.",
            fix="Pass an id from recall_context hits.",
        )
    row = store.get_by_id(memory_id)
    if not row:
        raise ToolError(
            "MEMORY_NOT_FOUND",
            f"No memory with id={memory_id!r}.",
            fix="Re-run recall_context and use an id from hits.",
            retry_safe=True,
        )
    if row["user_id"] != user_id:
        raise ToolError(
            "SCOPE_VIOLATION",
            "Memory does not belong to this user_id.",
            fix="Use the same user_id that owns the memory.",
            retry_safe=False,
        )
    tid = tenant_id or (config.tenant_id if config else "") or ""
    if (row.get("tenant_id") or "") != (tid or ""):
        if row.get("tenant_id") or tid:
            raise ToolError(
                "SCOPE_VIOLATION",
                "Memory tenant_id does not match.",
                fix="Pass the correct tenant_id.",
                retry_safe=False,
            )

    store.touch(memory_id)
    detail = row.get("detail") or row.get("fact_claim") or ""
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
            "entity": row.get("entity"),
            "supersedes_id": row.get("supersedes_id"),
            "superseded_by": row.get("superseded_by"),
            "authority": row.get("authority"),
            "sensitivity": row.get("sensitivity"),
            "ttl_days": row.get("ttl_days"),
            "validator_kind": row.get("validator_kind"),
            "provenance": row.get("provenance"),
            "created_at": row.get("created_at"),
            "truncated": truncated,
            "tokens_approx": _estimate_tokens(detail),
        },
        message="Full detail loaded under progressive disclosure.",
    )
