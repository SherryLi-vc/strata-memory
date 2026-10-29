"""Forget memories in scope and drop them from the rebuildable chroma.

SQLite is the source of truth. Rows are deleted, which fires the FTS5
delete trigger. SQLite chroma ids are removed in the same call. A later
``strata_rebuild_index`` reads only active SQLite rows, so a deleted id
cannot come back.
"""

from __future__ import annotations

from typing import Any, Optional

from ..governance import ToolError, success_payload
from ..storage.sqlite_vectors import SqliteVectorStore
from ..storage.truth_store import TruthStore


def _scope_tenant(row_tenant: str, tenant_id: str) -> bool:
    return (row_tenant or "") == (tenant_id or "")


def _page_bounds(limit: int, offset: int) -> tuple[int, int]:
    page = max(1, min(int(limit or 2000), 2000))
    start = max(0, int(offset or 0))
    return page, start


def forget_memories(
    *,
    store: TruthStore,
    user_id: str,
    tenant_id: str = "",
    memory_id: str = "",
    memory_type: str = "",
    layer: str = "",
    session_id: str = "",
    query: str = "",
    match_all: bool = False,
    confirm: bool = False,
    include_chain: bool = True,
    limit: int = 2000,
    offset: int = 0,
    chroma: Optional[SqliteVectorStore] = None,
) -> dict[str, Any]:
    if not user_id or not str(user_id).strip():
        raise ToolError(
            "MISSING_USER_ID",
            "user_id is required.",
            fix="Pass the user_id that owns the memories.",
        )
    user_id = str(user_id).strip()
    tenant_id = tenant_id or ""
    memory_id = (memory_id or "").strip()
    memory_type = (memory_type or "").strip()
    layer = (layer or "").strip()
    session_id = (session_id or "").strip()
    query = (query or "").strip()

    if memory_id:
        row = store.get_by_id(memory_id)
        if not row:
            raise ToolError(
                "MEMORY_NOT_FOUND",
                f"No memory with id={memory_id!r}.",
                fix="Pass an id from recall_context or export_memories.",
                retry_safe=True,
            )
        if row.get("user_id") != user_id or not _scope_tenant(row.get("tenant_id") or "", tenant_id):
            raise ToolError(
                "SCOPE_VIOLATION",
                "Memory does not belong to this user_id and tenant_id.",
                fix="Use the same user_id and tenant_id that own the memory.",
                retry_safe=False,
            )
        roots = [row]
        total = 1
        page, start = 1, 0
    else:
        has_filter = bool(memory_type or layer or session_id or query or match_all)
        if not has_filter:
            raise ToolError(
                "MISSING_FILTER",
                "Refusing to forget without an id or a filter.",
                fix=(
                    "Pass memory_id, or memory_type / layer / session_id / query. "
                    "To delete every memory in this user scope, pass match_all=true and confirm=true."
                ),
            )
        page, start = _page_bounds(limit, offset)
        total = store.count_memories_for_forget(
            user_id=user_id,
            tenant_id=tenant_id,
            memory_type=memory_type,
            layer=layer,
            session_id=session_id,
            query=query,
            match_all=match_all,
        )
        roots = store.find_memories_for_forget(
            user_id=user_id,
            tenant_id=tenant_id,
            memory_type=memory_type,
            layer=layer,
            session_id=session_id,
            query=query,
            match_all=match_all,
            limit=page,
            offset=start,
        )
        remaining_preview = max(0, total - start - len(roots))
        if not confirm:
            return {
                "status": "error",
                "error_code": "CONFIRMATION_REQUIRED",
                "message": (f"Filter matches {total} memories. This page has {len(roots)}. Nothing was deleted."),
                "how_to_fix": "Re-call forget_memory with confirm=true. Pass offset=next_offset to continue.",
                "retry_safe": True,
                "matched_count": len(roots),
                "matched_ids": [row["id"] for row in roots],
                "total": total,
                "offset": start,
                "limit": page,
                "remaining": remaining_preview,
                "next_offset": (start + len(roots)) if remaining_preview else None,
                "include_chain": include_chain,
            }

    doomed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        rows = store.supersede_chain(root["id"], user_id=user_id, tenant_id=tenant_id) if include_chain else [root]
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            doomed.append(row)
    deleted = store.delete_ids([row["id"] for row in doomed], user_id=user_id, tenant_id=tenant_id)

    ids = [row["id"] for row in deleted]
    store.redact_audit_for_targets(ids)
    remaining = (
        0
        if memory_id
        else store.count_memories_for_forget(
            user_id=user_id,
            tenant_id=tenant_id,
            memory_type=memory_type,
            layer=layer,
            session_id=session_id,
            query=query,
            match_all=match_all,
        )
    )
    index_removed = False
    if chroma is not None and ids:
        try:
            chroma.delete_by_ids(ids)
            index_removed = True
        except Exception:
            index_removed = False

    store.audit(
        "forget_memory",
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        target=",".join(ids[:20]),
        summary=f"deleted={len(ids)} index_removed={index_removed}",
    )
    return success_payload(
        {
            "deleted_count": len(ids),
            "deleted_ids": ids,
            "index_removed": index_removed,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "include_chain": include_chain,
            "total": total if not memory_id else len(ids),
            "offset": 0 if memory_id else start,
            "limit": len(ids) if memory_id else page,
            "remaining": remaining,
            # Deleted rows shift later matches toward the beginning. Keep the
            # cursor at zero so callers following next_offset never skip them.
            "next_offset": None if memory_id or not remaining else 0,
        },
        message=f"Forgot {len(ids)} memories.",
    )
