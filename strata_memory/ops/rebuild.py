"""strata_rebuild_index — destroy & rebuild vector companion from SQLite SoT."""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..embedder_stamp import identity_for, incompatibility, read_stamp, stamp_path, write_stamp
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
    Re-embed active durable memories from SoT into the vector index.

    Without a tenant: replace the whole collection. With a tenant (argument or
    config): delete and re-add only that tenant's vectors, keeping the rest.
    If the existing index is unstamped or stamped by another embedder, a
    tenant-scoped request is escalated to a full rebuild (``scope="all"``).

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

    requested_tenant = tenant_id or config.tenant_id or ""
    persist = chroma.persist_dir
    stamp = stamp_path(persist)
    ident = identity_for(config.embedding, embed_provider)

    # A tenant-scoped rebuild may only touch that tenant's vectors. It is only
    # safe when every other vector was built by the current embedder (matching
    # stamp, or an empty index). Otherwise the other tenants' vectors are
    # unusable anyway, so rebuild everything instead of silently dropping them.
    scope = "all"
    escalated_from = ""
    if requested_tenant:
        try:
            total_before = chroma.count()
        except Exception:
            total_before = 0
        if total_before == 0 or (
            read_stamp(persist) is not None and incompatibility(persist, ident, vector_count=total_before) is None
        ):
            scope = "tenant"
        else:
            escalated_from = requested_tenant

    index_tenant = requested_tenant if scope == "tenant" else ""
    rows = store.iter_for_index(tenant_id=index_tenant)
    others_before: int | None = None

    try:
        if scope == "tenant":
            # Keep the stamp: the vectors that stay were built by this embedder.
            chroma.delete_where({"tenant_id": requested_tenant})
            # Legacy vectors may lack tenant metadata; drop this tenant's ids too.
            row_ids = [row["id"] for row in rows]
            if row_ids:
                chroma.delete_by_ids(row_ids)
            others_before = chroma.count()
        else:
            # Invalidate the old identity before replacing vectors. Keep the persistent
            # client alive and replace its collection instead of deleting its open DB.
            stamp.unlink(missing_ok=True)
            chroma.reset()
    except Exception as e:
        return {
            "status": "error",
            "error_code": "RESET_FAILED",
            "message": str(e),
            "how_to_fix": "Ensure no other process is writing to the Chroma index, then retry.",
            "retry_safe": True,
        }

    ok = 0
    failed = 0
    errors: list[str] = []

    for row in rows:
        if row.get("is_negative_schema"):
            continue  # keep negative schemas out of hot index
        try:
            claim = row["fact_claim"]
            text = f"[{row['user_id']}/{row.get('room', 'general')}] {claim[:2000]}"
            vec = await embed_provider.embed(text)
            chroma.add(
                documents=[text],
                metadatas=[
                    {
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
                    }
                ],
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
        tenant_id=requested_tenant,
        summary=f"rebuilt scope={scope} ok={ok} failed={failed} source_rows={len(rows)}",
    )
    try:
        vector_count = chroma.count()
    except Exception:
        vector_count = None

    expected = sum(1 for row in rows if not row.get("is_negative_schema"))
    if scope == "tenant":
        # Others must be untouched; this tenant's vectors must equal its SoT rows.
        expected_total = None if others_before is None else others_before + expected
    else:
        expected_total = expected
    scope_info: dict[str, Any] = {"scope": scope, "tenant_id": requested_tenant}
    if escalated_from:
        scope_info["escalated_from_tenant"] = escalated_from
        scope_info["escalation_reason"] = (
            "Vectors of other tenants were missing a matching embedder stamp, so all tenants were rebuilt."
        )
    if failed or ok != expected or vector_count != expected_total:
        return {
            "status": "error",
            "error_code": "REBUILD_INCOMPLETE",
            "message": f"Vector index rebuild incomplete: {ok} indexed, {failed} failed (expected {expected}).",
            "source_rows": len(rows),
            "indexed": ok,
            "failed": failed,
            "errors_sample": errors,
            "vector_count": vector_count,
            "embedder": ident,
            "persist_dir": str(persist),
            "retry_safe": True,
            **scope_info,
        }

    write_stamp(persist, ident)

    return {
        "status": "ok",
        "message": f"Vector index rebuilt from SQLite SoT: {ok} indexed, {failed} failed.",
        "source_rows": len(rows),
        "indexed": ok,
        "failed": failed,
        "errors_sample": errors,
        "vector_count": vector_count,
        "embedder": ident,
        "persist_dir": str(persist),
        **scope_info,
    }
