"""Progressive Recall Funnel (2.0 + 3.0 multi-signal rerank).

L0 used to be prepended with a hardcoded score of 1.0, ahead of the ranked
list, so ``limit`` only trimmed hybrid hits. Every active row now competes
on query relevance. ``limit`` is applied to that single list. ``include_l0``
drops the L0 layer from the candidate pool when false.
"""

from __future__ import annotations

from typing import Any, Optional

from ..config import Config
from ..embedder_stamp import identity_for, incompatibility, mismatch_fix, mismatch_message
from ..embedding import EmbeddingProvider
from ..governance import CBTMiddleware, ToolError, success_payload
from ..pipeline.lexical import fts_or_query, lexical_scores, squash_lexical
from ..pipeline.scoring_signals import multi_signal_score
from ..storage.chroma import ChromaStore
from ..storage.truth_store import TruthStore

_CANDIDATE_LIMIT = 300

_RELEVANCE_FLOOR = 0.05


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


# Appended to a card summary that was cut short; expand_memory_detail returns the full text.
TRUNCATION_MARK = " …[truncated]"
_SUMMARY_FROM_CLAIM = 240
_SUMMARY_MAX = 400


def _card_summary(row: dict[str, Any], cbt: CBTMiddleware, config: Config) -> tuple[str, bool]:
    """Card summary and whether it was cut short."""
    claim = row.get("fact_claim") or ""
    stored = row.get("summary") or ""
    if stored:
        # The write path cuts long claims to 237 chars + "..." (or 240 chars after redaction).
        body = stored.removesuffix("...")
        truncated = stored != claim and len(claim) > len(body)
        summary = body if truncated else stored
    else:
        summary = claim[:_SUMMARY_FROM_CLAIM]
        truncated = len(claim) > _SUMMARY_FROM_CLAIM
    if row.get("is_negative_schema") and config.cbt.enabled and config.cbt.mode == "passive":
        summary = cbt.defusion_frame(summary)
    limit = _SUMMARY_MAX - len(TRUNCATION_MARK)
    if len(summary) > _SUMMARY_MAX:
        summary, truncated = summary[:limit], True
    if truncated:
        summary = summary.rstrip() + TRUNCATION_MARK
    return summary, truncated


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
    shallow = context_depth == "shallow"
    cbt = CBTMiddleware(
        enabled=config.cbt.enabled,
        cooling_hours=config.cbt.cooling_hours,
    )
    filter_log: list[dict[str, str]] = []

    rows = store.list_active(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        include_scratch=bool(session_id),
        limit=_CANDIDATE_LIMIT,
    )
    # Only the newest _CANDIDATE_LIMIT active rows are scanned; say so when there may be more.
    scan_limit_reached = len(rows) >= _CANDIDATE_LIMIT
    by_id: dict[str, dict[str, Any]] = {row["id"]: row for row in rows}

    vector_ids: list[str] = []
    fts_ids: list[str] = []
    vector_sim: dict[str, float] = {}
    vector_skipped = ""
    warnings: list[str] = []

    if not shallow:
        or_query = fts_or_query(query)
        if or_query:
            try:
                fres = store.fts_search(
                    query,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    limit=max(limit * 4, 20),
                    fts_query=or_query,
                )
                for row in fres:
                    fts_ids.append(row["id"])
                    by_id.setdefault(row["id"], row)
            except Exception:
                fts_ids = []

        if embed_provider and chroma:
            try:
                vector_count = chroma.count()
            except Exception:
                vector_count = 0
            probe = None
            if vector_count:
                ident = identity_for(config.embedding, embed_provider)
                problem = incompatibility(chroma.persist_dir, ident, vector_count=vector_count)
                if problem == "EMBEDDER_UNSTAMPED":
                    # Index from before stamps existed (upgrade from main). Its
                    # embedder is unknown, so do not mix vectors; keep recall
                    # working on the lexical path until a rebuild stamps it.
                    vector_skipped = problem
                    warnings.append(
                        "Vector recall skipped: the index has no embedder stamp (upgraded from an older "
                        "version). Results are lexical only. Run strata_rebuild_index(confirm=true) once "
                        "to restore semantic recall."
                    )
                elif problem:
                    raise ToolError(
                        problem,
                        mismatch_message(problem, ident),
                        fix=mismatch_fix(),
                        retry_safe=True,
                    )
                else:
                    probe = await embed_provider.embed(query)
            if not vector_skipped:
                try:
                    qvec = probe if probe is not None else await embed_provider.embed(query)
                    # An empty tenant is the default tenant, not a wildcard (H2).
                    where: dict[str, Any] = {"$and": [{"user_id": user_id}, {"tenant_id": tenant_id}]}
                    vres = chroma.query(query_embedding=qvec, top_k=limit * 4, where=where)
                    for hit in vres:
                        mid = hit.get("id")
                        if not mid:
                            continue
                        vector_ids.append(mid)
                        distance = float(hit.get("distance") or 0.0)
                        vector_sim[mid] = max(0.0, min(1.0, 1.0 - distance))
                        if mid not in by_id:
                            row = store.get_by_id(mid)
                            if row:
                                by_id[mid] = row
                except ToolError:
                    raise
                except Exception:
                    vector_ids = []

    candidates: list[dict[str, Any]] = []
    for row in by_id.values():
        # SoT is authoritative for scope: lexical and vector paths both filter
        # tenant only when it is non-empty, so enforce an exact match here.
        if (row.get("tenant_id") or "") != tenant_id or row.get("user_id") != user_id:
            filter_log.append({"id": row["id"], "reason": "out_of_scope"})
            continue
        if row.get("status") != "active":
            filter_log.append({"id": row["id"], "reason": "inactive_or_missing"})
            continue
        if not include_l0 and row.get("layer") == "L0":
            filter_log.append({"id": row["id"], "reason": "include_l0_false"})
            continue
        if current_turn_only and row.get("layer") == "L0":
            filter_log.append({"id": row["id"], "reason": "current_turn_skips_l0"})
            continue
        if row.get("is_scratch") and row.get("session_id") != session_id:
            filter_log.append({"id": row["id"], "reason": "scratch_other_session"})
            continue
        if current_turn_only and session_id:
            if row.get("session_id") and row.get("session_id") != session_id:
                filter_log.append({"id": row["id"], "reason": "not_current_session"})
                continue
        if shallow and row.get("layer") not in {"L0", "scratch"}:
            continue
        if row.get("is_negative_schema") and config.cbt.enabled and config.cbt.mode == "active":
            filter_log.append({"id": row["id"], "reason": "cbt_active_hidden"})
            continue
        candidates.append(row)

    lexical = lexical_scores(
        query,
        [(row["id"], f"{row.get('fact_claim') or ''} {row.get('summary') or ''}") for row in candidates],
    )

    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in candidates:
        raw_lex = float(lexical.get(row["id"], 0.0))
        lex_norm = squash_lexical(raw_lex)
        vsim = vector_sim.get(row["id"])
        if lex_norm > 0 and vsim is not None:
            relevance = 0.75 * lex_norm + 0.25 * vsim
        elif lex_norm > 0:
            relevance = lex_norm
        elif vsim is not None:
            relevance = 0.25 * vsim
        else:
            relevance = 0.0
        if relevance < _RELEVANCE_FLOOR:
            filter_log.append({"id": row["id"], "reason": "below_relevance"})
            continue

        final, breakdown = multi_signal_score(row, rrf_score=raw_lex, relevance=relevance)
        if session_id and row.get("session_id") == session_id and not row.get("is_scratch"):
            final *= 1.15
            breakdown["session_boost"] = 1.15
        breakdown["lexical"] = round(raw_lex, 4)
        breakdown["why"] = _why_selected(breakdown, row)
        breakdown["final"] = round(final, 4)
        summary, summary_truncated = _card_summary(row, cbt, config)
        card = {
            "id": row["id"],
            "summary": summary,
            "summary_truncated": summary_truncated,
            "memory_type": row["memory_type"],
            "layer": row["layer"],
            "score": round(final, 4),
            "score_breakdown": breakdown,
            "is_negative_schema": bool(row.get("is_negative_schema")),
            "entity": row.get("entity") or None,
            "supersedes_id": row.get("supersedes_id") or None,
        }
        ranked.append((final, card))

    ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
    for _score, card in ranked[limit:]:
        filter_log.append({"id": card["id"], "reason": "below_top_k"})
    selected = [card for _score, card in ranked[:limit]]

    max_tokens = config.l0_token_budget if shallow else config.l0_token_budget + config.l2_token_budget
    trimmed: list[dict[str, Any]] = []
    used = 0
    waterline_dropped = 0
    for card in selected:
        cost = _estimate_tokens(card["summary"])
        if used + cost > max_tokens:
            filter_log.append({"id": card["id"], "reason": "token_waterline"})
            waterline_dropped += 1
            continue
        trimmed.append(card)
        used += cost
        store.touch(card["id"])

    store.audit(
        "recall_context",
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        target=user_id,
        # Do not keep the query text: it is user content that forget cannot reach (N5).
        summary=f"q_len={len(query)} hits={len(trimmed)} tokens~{used}",
    )

    payload: dict[str, Any] = {
        "query": query,
        "hits": trimmed,
        "hit_count": len(trimmed),
        "token_estimate": used,
        "mode": "shallow" if shallow else "deep",
        "include_l0": bool(include_l0),
        "filtered": filter_log[:30],
        "note": (
            "Summaries only. Call expand_memory_detail(id) for full text."
            if shallow
            else "Progressive disclosure: id+summary+score+score_breakdown. Call expand_memory_detail for full detail."
        ),
    }
    truncation = {
        "scan_limit": _CANDIDATE_LIMIT,
        "scan_limit_reached": scan_limit_reached,
        "token_waterline_dropped": waterline_dropped,
        "summaries_truncated": sum(1 for card in trimmed if card["summary_truncated"]),
    }
    payload["truncated"] = bool(
        truncation["scan_limit_reached"] or truncation["token_waterline_dropped"] or truncation["summaries_truncated"]
    )
    payload["truncation"] = truncation
    if not shallow:
        payload["fusion"] = {
            "vector_hits": len(vector_ids),
            "fts_hits": len(fts_ids),
            "rerank": "lexical_bm25+multi_signal_v3",
        }
        if vector_skipped:
            payload["fusion"]["vector_skipped"] = vector_skipped
    if warnings:
        payload["warnings"] = warnings
    message = (
        f"Shallow recall: {len(trimmed)} cards."
        if shallow
        else f"Recall funnel returned {len(trimmed)} cards (~{used} tokens)."
    )
    return success_payload(payload, message=message)


def _why_selected(breakdown: dict[str, Any], row: dict[str, Any]) -> str:
    parts = []
    if breakdown.get("relevance", 0) >= 0.5:
        parts.append("high relevance")
    if breakdown.get("recency", 0) >= 0.7:
        parts.append("recent")
    if breakdown.get("importance", 0) >= 0.7:
        parts.append("important")
    if breakdown.get("usage_boost", 0) >= 0.3:
        parts.append("frequently used")
    if row.get("layer") == "L0" and breakdown.get("relevance", 0) >= 0.5:
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
