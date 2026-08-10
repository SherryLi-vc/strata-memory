"""Truth Store — Single Source of Truth (SQLite).

Strata Memory 2.0 design law:
  - SQLite is the only authoritative write surface.
  - ChromaDB / graph indexes are rebuildable companions.
  - Markdown is a read-only projection generated from this store.

Scope key (3-axis isolation):
  tenant_id + user_id + session_id
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA_VERSION = 2

MEMORIES_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id                  TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL DEFAULT '',
    user_id             TEXT NOT NULL,
    session_id          TEXT NOT NULL DEFAULT '',
    memory_type         TEXT NOT NULL,
    fact_claim          TEXT NOT NULL,
    summary             TEXT NOT NULL DEFAULT '',
    detail              TEXT NOT NULL DEFAULT '',
    confidence          REAL NOT NULL DEFAULT 0.5,
    importance          REAL NOT NULL DEFAULT 0.5,
    emotional_salience  REAL NOT NULL DEFAULT 0.0,
    content_hash        TEXT NOT NULL,
    layer               TEXT NOT NULL DEFAULT 'L2',
    status              TEXT NOT NULL DEFAULT 'active',
    is_negative_schema  INTEGER NOT NULL DEFAULT 0,
    is_scratch          INTEGER NOT NULL DEFAULT 0,
    usage_count         INTEGER NOT NULL DEFAULT 0,
    context_tags        TEXT NOT NULL DEFAULT '[]',
    room                TEXT NOT NULL DEFAULT 'general',
    ttl_seconds         INTEGER,
    expires_at          TEXT,
    valid_from          TEXT,
    valid_to            TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    last_accessed       TEXT,
    source              TEXT NOT NULL DEFAULT 'commit_memory'
);

CREATE INDEX IF NOT EXISTS idx_mem_scope
    ON memories(tenant_id, user_id, session_id);
CREATE INDEX IF NOT EXISTS idx_mem_user_status
    ON memories(user_id, status, layer);
CREATE INDEX IF NOT EXISTS idx_mem_hash
    ON memories(tenant_id, user_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_mem_type
    ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_mem_expires
    ON memories(expires_at);
CREATE INDEX IF NOT EXISTS idx_mem_scratch
    ON memories(is_scratch, session_id);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED,
    fact_claim,
    summary,
    detail,
    context_tags,
    content='memories',
    content_rowid='rowid'
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    tenant_id   TEXT NOT NULL DEFAULT '',
    user_id     TEXT NOT NULL DEFAULT '',
    session_id  TEXT NOT NULL DEFAULT '',
    target      TEXT NOT NULL,
    summary     TEXT,
    before_snap TEXT,
    after_snap  TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_scope
    ON audit_log(tenant_id, user_id);

CREATE TABLE IF NOT EXISTS trajectory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name    TEXT NOT NULL,
    tenant_id    TEXT NOT NULL DEFAULT '',
    user_id      TEXT NOT NULL DEFAULT '',
    session_id   TEXT NOT NULL DEFAULT '',
    args_digest  TEXT,
    result_status TEXT,
    error_code   TEXT,
    latency_ms   INTEGER,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_traj_tool ON trajectory(tool_name);
CREATE INDEX IF NOT EXISTS idx_traj_created ON trajectory(created_at);
"""

# Default TTL (seconds) by memory_type — deterministic, not LLM-chosen.
DEFAULT_TTL: dict[str, Optional[int]] = {
    "factual_truth": None,          # permanent until superseded
    "user_preference": None,
    "procedure_rule": None,
    "episodic_event": 90 * 24 * 3600,  # 90 days
}

LAYER_DEFAULT: dict[str, str] = {
    "factual_truth": "L0",
    "user_preference": "L0",
    "procedure_rule": "L0",
    "episodic_event": "L2",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class TruthStore:
    """SQLite Single Source of Truth for all durable + scratch memories."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(MEMORIES_DDL)
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key='version'"
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO schema_meta(key, value) VALUES ('version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            # FTS triggers (idempotent via IF NOT EXISTS not available for triggers —
            # drop+recreate is safe for empty companion index tables)
            conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
              INSERT INTO memories_fts(rowid, id, fact_claim, summary, detail, context_tags)
              VALUES (new.rowid, new.id, new.fact_claim, new.summary, new.detail, new.context_tags);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
              INSERT INTO memories_fts(memories_fts, rowid, id, fact_claim, summary, detail, context_tags)
              VALUES ('delete', old.rowid, old.id, old.fact_claim, old.summary, old.detail, old.context_tags);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
              INSERT INTO memories_fts(memories_fts, rowid, id, fact_claim, summary, detail, context_tags)
              VALUES ('delete', old.rowid, old.id, old.fact_claim, old.summary, old.detail, old.context_tags);
              INSERT INTO memories_fts(rowid, id, fact_claim, summary, detail, context_tags)
              VALUES (new.rowid, new.id, new.fact_claim, new.summary, new.detail, new.context_tags);
            END;
            """)

    # ── Writes ──────────────────────────────────────────────────────────

    def insert_memory(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        memory_type: str,
        fact_claim: str,
        content_hash: str,
        confidence: float,
        importance: float = 0.5,
        emotional_salience: float = 0.0,
        summary: str = "",
        detail: str = "",
        is_negative_schema: bool = False,
        is_scratch: bool = False,
        context_tags: Optional[list[str]] = None,
        room: str = "general",
        ttl_seconds: Optional[int] = None,
        layer: Optional[str] = None,
        source: str = "commit_memory",
    ) -> dict[str, Any]:
        """Insert a new memory row. Caller must run Quality Kernel first."""
        now = _utcnow()
        mid = _new_id()
        tags = context_tags or []
        if ttl_seconds is None:
            ttl_seconds = DEFAULT_TTL.get(memory_type)
        expires_at = None
        if ttl_seconds is not None:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
            ).replace(microsecond=0).isoformat()
        layer = layer or ("scratch" if is_scratch else LAYER_DEFAULT.get(memory_type, "L2"))
        if is_scratch:
            layer = "scratch"

        summary = summary or fact_claim[:240]
        detail = detail or fact_claim

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO memories (
                    id, tenant_id, user_id, session_id, memory_type, fact_claim,
                    summary, detail, confidence, importance, emotional_salience,
                    content_hash, layer, status, is_negative_schema, is_scratch,
                    usage_count, context_tags, room, ttl_seconds, expires_at,
                    valid_from, created_at, updated_at, last_accessed, source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    mid, tenant_id or "", user_id, session_id or "", memory_type,
                    fact_claim, summary, detail, confidence, importance,
                    emotional_salience, content_hash, layer, "active",
                    1 if is_negative_schema else 0, 1 if is_scratch else 0,
                    0, json.dumps(tags, ensure_ascii=False), room,
                    ttl_seconds, expires_at, now, now, now, now, source,
                ),
            )
        return self.get_by_id(mid)  # type: ignore[return-value]

    def find_by_hash(
        self, tenant_id: str, user_id: str, content_hash: str
    ) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM memories
                   WHERE tenant_id=? AND user_id=? AND content_hash=?
                     AND status='active' AND valid_to IS NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (tenant_id or "", user_id, content_hash),
            ).fetchone()
        return dict(row) if row else None

    def get_by_id(self, memory_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
        return dict(row) if row else None

    def touch(self, memory_id: str) -> None:
        now = _utcnow()
        with self._conn() as conn:
            conn.execute(
                """UPDATE memories
                   SET usage_count = usage_count + 1,
                       last_accessed = ?,
                       updated_at = ?
                   WHERE id=?""",
                (now, now, memory_id),
            )

    def archive(self, memory_id: str, reason: str = "superseded") -> bool:
        now = _utcnow()
        with self._conn() as conn:
            cur = conn.execute(
                """UPDATE memories
                   SET status='archived', valid_to=?, updated_at=?,
                       detail = detail || ?
                   WHERE id=? AND status='active'""",
                (now, now, f"\n\n[archived:{reason}]", memory_id),
            )
            return cur.rowcount > 0

    def demote(self, memory_id: str, target_layer: str = "L3") -> bool:
        now = _utcnow()
        with self._conn() as conn:
            cur = conn.execute(
                """UPDATE memories SET layer=?, updated_at=? WHERE id=?""",
                (target_layer, now, memory_id),
            )
            return cur.rowcount > 0

    def promote_scratch(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> list[str]:
        """Promote all scratch memories for a session into durable layers."""
        now = _utcnow()
        promoted: list[str] = []
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, memory_type FROM memories
                   WHERE tenant_id=? AND user_id=? AND session_id=?
                     AND is_scratch=1 AND status='active'""",
                (tenant_id or "", user_id, session_id),
            ).fetchall()
            for row in rows:
                layer = LAYER_DEFAULT.get(row["memory_type"], "L2")
                conn.execute(
                    """UPDATE memories
                       SET is_scratch=0, layer=?, session_id='',
                           updated_at=?
                       WHERE id=?""",
                    (layer, now, row["id"]),
                )
                promoted.append(row["id"])
        return promoted

    # ── Reads ───────────────────────────────────────────────────────────

    def list_active(
        self,
        *,
        tenant_id: str = "",
        user_id: str,
        session_id: str = "",
        layers: Optional[list[str]] = None,
        include_scratch: bool = False,
        exclude_negative: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        parts = [
            "SELECT * FROM memories WHERE status='active' AND valid_to IS NULL",
            "AND user_id=?",
            "AND tenant_id=?",
        ]
        params: list[Any] = [user_id, tenant_id or ""]
        if not include_scratch:
            parts.append("AND is_scratch=0")
        elif session_id:
            parts.append("AND (is_scratch=0 OR session_id=?)")
            params.append(session_id)
        if layers:
            placeholders = ",".join("?" * len(layers))
            parts.append(f"AND layer IN ({placeholders})")
            params.extend(layers)
        if exclude_negative:
            parts.append("AND is_negative_schema=0")
        # Soft-expire check
        parts.append("AND (expires_at IS NULL OR expires_at > ?)")
        params.append(_utcnow())
        safe_limit = max(1, min(int(limit), 500))
        parts.append(f"ORDER BY importance DESC, last_accessed DESC LIMIT {safe_limit}")
        with self._conn() as conn:
            rows = conn.execute(" ".join(parts), params).fetchall()
        return [dict(r) for r in rows]

    def fts_search(
        self,
        query: str,
        *,
        tenant_id: str = "",
        user_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Full-text search via FTS5. Returns id + bm25 rank."""
        # Escape FTS special chars lightly — quote each token
        tokens = [t for t in query.replace('"', " ").split() if t]
        if not tokens:
            return []
        fts_q = " ".join(f'"{t}"' for t in tokens[:12])
        safe_limit = max(1, min(int(limit), 100))
        sql = f"""
            SELECT m.*, bm25(memories_fts) AS fts_rank
            FROM memories_fts
            JOIN memories m ON m.id = memories_fts.id
            WHERE memories_fts MATCH ?
              AND m.status='active' AND m.valid_to IS NULL
              AND m.user_id=? AND m.tenant_id=?
              AND m.is_scratch=0
              AND (m.expires_at IS NULL OR m.expires_at > ?)
            ORDER BY fts_rank
            LIMIT {safe_limit}
        """
        with self._conn() as conn:
            try:
                rows = conn.execute(
                    sql, (fts_q, user_id, tenant_id or "", _utcnow())
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        return [dict(r) for r in rows]

    def iter_for_index(
        self, *, tenant_id: str = "", user_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """All active durable memories for vector rebuild."""
        parts = [
            "SELECT * FROM memories WHERE status='active' AND valid_to IS NULL",
            "AND is_scratch=0",
            "AND (expires_at IS NULL OR expires_at > ?)",
        ]
        params: list[Any] = [_utcnow()]
        if tenant_id:
            parts.append("AND tenant_id=?")
            params.append(tenant_id)
        if user_id:
            parts.append("AND user_id=?")
            params.append(user_id)
        parts.append("ORDER BY created_at ASC")
        with self._conn() as conn:
            rows = conn.execute(" ".join(parts), params).fetchall()
        return [dict(r) for r in rows]

    def count_by_layer(
        self, *, tenant_id: str = "", user_id: Optional[str] = None
    ) -> dict[str, int]:
        parts = [
            "SELECT layer, COUNT(*) AS n FROM memories",
            "WHERE status='active' AND valid_to IS NULL",
        ]
        params: list[Any] = []
        if tenant_id:
            parts.append("AND tenant_id=?")
            params.append(tenant_id)
        if user_id:
            parts.append("AND user_id=?")
            params.append(user_id)
        parts.append("GROUP BY layer")
        with self._conn() as conn:
            rows = conn.execute(" ".join(parts), params).fetchall()
        return {r["layer"]: r["n"] for r in rows}

    def stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE status='active'"
            ).fetchone()["n"]
            archived = conn.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE status='archived'"
            ).fetchone()["n"]
            scratch = conn.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE is_scratch=1 AND status='active'"
            ).fetchone()["n"]
            neg = conn.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE is_negative_schema=1 AND status='active'"
            ).fetchone()["n"]
            by_type = {
                r["memory_type"]: r["n"]
                for r in conn.execute(
                    """SELECT memory_type, COUNT(*) AS n FROM memories
                       WHERE status='active' GROUP BY memory_type"""
                ).fetchall()
            }
            tokens_approx = conn.execute(
                """SELECT COALESCE(SUM(LENGTH(fact_claim)+LENGTH(summary)+LENGTH(detail)),0) AS chars
                   FROM memories WHERE status='active'"""
            ).fetchone()["chars"]
        layers = self.count_by_layer()
        return {
            "active": total,
            "archived": archived,
            "scratch": scratch,
            "negative_schema": neg,
            "by_type": by_type,
            "by_layer": layers,
            "chars_approx": tokens_approx,
            "tokens_approx": max(0, int(tokens_approx) // 3),
            "db_path": str(self.db_path),
            "schema_version": SCHEMA_VERSION,
        }

    def candidates_for_digest(self, older_than_days: int = 30) -> list[dict[str, Any]]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=older_than_days)
        ).replace(microsecond=0).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memories
                   WHERE status='active' AND is_scratch=0
                     AND layer IN ('L1','L2')
                     AND (last_accessed IS NULL OR last_accessed < ?)
                   ORDER BY last_accessed ASC NULLS FIRST
                   LIMIT 500""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Audit / trajectory ──────────────────────────────────────────────

    def audit(
        self,
        action: str,
        *,
        agent_id: str = "strata-mcp",
        tenant_id: str = "",
        user_id: str = "",
        session_id: str = "",
        target: str = "",
        summary: str = "",
        before: str = "",
        after: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO audit_log
                   (action, agent_id, tenant_id, user_id, session_id,
                    target, summary, before_snap, after_snap, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    action, agent_id, tenant_id or "", user_id or "",
                    session_id or "", target, summary, before[:2000],
                    after[:2000], _utcnow(),
                ),
            )

    def log_trajectory(
        self,
        tool_name: str,
        *,
        tenant_id: str = "",
        user_id: str = "",
        session_id: str = "",
        args_digest: str = "",
        result_status: str = "ok",
        error_code: str = "",
        latency_ms: int = 0,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO trajectory
                   (tool_name, tenant_id, user_id, session_id, args_digest,
                    result_status, error_code, latency_ms, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    tool_name, tenant_id or "", user_id or "", session_id or "",
                    args_digest[:500], result_status, error_code, latency_ms,
                    _utcnow(),
                ),
            )

    def trajectory_summary(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT tool_name, result_status, COUNT(*) AS n
                    FROM trajectory
                    GROUP BY tool_name, result_status
                    ORDER BY n DESC LIMIT {safe_limit}"""
            ).fetchall()
        return [dict(r) for r in rows]
