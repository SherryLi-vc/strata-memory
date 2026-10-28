"""JSON export of memories inside one tenant/user scope."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..governance import ToolError, success_payload
from ..storage.truth_store import TruthStore

EXPORT_FORMAT = "strata-memory-export-v1"

_COLUMNS = (
    "id",
    "tenant_id",
    "user_id",
    "session_id",
    "memory_type",
    "fact_claim",
    "summary",
    "detail",
    "layer",
    "status",
    "confidence",
    "importance",
    "is_scratch",
    "entity",
    "supersedes_id",
    "superseded_by",
    "authority",
    "context_tags",
    "provenance",
    "created_at",
    "updated_at",
    "valid_from",
    "valid_to",
)


def _cell(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if key in {"context_tags", "provenance"} and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if key == "is_scratch":
        return bool(value)
    return value


def export_memories(
    *,
    store: TruthStore,
    user_id: str,
    tenant_id: str = "",
    session_id: str = "",
    include_archived: bool = False,
    limit: int = 500,
) -> dict[str, Any]:
    if not user_id or not str(user_id).strip():
        raise ToolError(
            "MISSING_USER_ID",
            "user_id is required.",
            fix="Pass the user_id whose memories should be exported.",
        )
    user_id = str(user_id).strip()
    tenant_id = tenant_id or ""
    rows = store.list_for_export(
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=(session_id or "").strip(),
        include_archived=include_archived,
        limit=limit,
    )
    memories = [{key: _cell(row, key) for key in _COLUMNS} for row in rows]
    store.audit(
        "export_memories",
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id or "",
        target=user_id,
        summary=f"exported={len(memories)}",
    )
    return success_payload(
        {
            "format": EXPORT_FORMAT,
            "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "scope": {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "session_id": session_id or "",
                "include_archived": include_archived,
            },
            "count": len(memories),
            "memories": memories,
        },
        message=f"Exported {len(memories)} memories.",
    )
