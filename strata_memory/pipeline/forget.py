"""Forget memories in scope and drop them from the rebuildable vector index.

SQLite is the source of truth. Rows are deleted, which fires the FTS5
delete trigger. Chroma ids are removed in the same call. A later
``strata_rebuild_index`` reads only active SQLite rows, so a deleted id
cannot come back.
"""

from __future__ import annotations

from typing import Any, Optional

from ..governance import ToolError, success_payload
from ..storage.chroma import ChromaStore
from ..storage.truth_store import TruthStore


def _scope_tenant(row_tenant: str, tenant_id: str) -> bool:
    return (row_tenant or "") == (tenant_id or "")


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
    chroma: Optional[ChromaStore] = None,
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
        deleted = store.delete_memories(user_id=user_id, tenant_id=tenant_id, memory_id=memory_id)
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
        matches = store.find_memories_for_forget(
            user_id=user_id,
            tenant_id=tenant_id,
            memory_type=memory_type,
            layer=layer,
            session_id=session_id,
            query=query,
            match_all=match_all,
        )
        if not confirm:
            return {
                "status": "error",
                "error_code": "CONFIRMATION_REQUIRED",
                "message": f"Filter matches {len(matches)} memories. Nothing was deleted.",
                "how_to_fix": "Re-call forget_memory with confirm=true to delete those rows.",
                "retry_safe": True,
                "matched_count": len(matches),
                "matched_ids": [row["id"] for row in matches],
            }
        deleted = store.delete_memories(
            user_id=user_id,
            tenant_id=tenant_id,
            memory_type=memory_type,
            layer=layer,
            session_id=session_id,
            query=query,
            match_all=match_all,
        )

    ids = [row["id"] for row in deleted]
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
        },
        message=f"Forgot {len(ids)} memories.",
    )
