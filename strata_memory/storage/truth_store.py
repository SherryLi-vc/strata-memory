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

SCHEMA_VERSION = 3

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
    ttl_days            INTEGER,
    expires_at          TEXT,
    valid_from          TEXT,
    valid_to            TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    last_accessed       TEXT,
    source              TEXT NOT NULL DEFAULT 'commit_memory',
    supersedes_id       TEXT,
    superseded_by       TEXT,
    authority           TEXT NOT NULL DEFAULT 'agent',
    sensitivity         TEXT NOT NULL DEFAULT 'normal',
    entity              TEXT NOT NULL DEFAULT '',
    validator_kind      TEXT NOT NULL DEFAULT 'quality_kernel',
    provenance          TEXT NOT NULL DEFAULT '{}'
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
# Prefer governance.type_defaults for full policy; keep for backward import.
DEFAULT_TTL: dict[str, Optional[int]] = {
    "factual_truth": None,
    "user_preference": None,
    "procedure_rule": None,
    "episodic_event": 90 * 24 * 3600,
    "decision_record": 365 * 24 * 3600,
}

LAYER_DEFAULT: dict[str, str] = {
    "factual_truth": "L0",
    "user_preference": "L0",
    "procedure_rule": "L0",
    "episodic_event": "L2",
    "decision_record": "L1",
}

# Columns added in schema v3 (ALTER TABLE for existing DBs)
_V3_COLUMNS: list[tuple[str, str]] = [
    ("ttl_days", "INTEGER"),
    ("supersedes_id", "TEXT"),
    ("superseded_by", "TEXT"),
    ("authority", "TEXT NOT NULL DEFAULT 'agent'"),
    ("sensitivity", "TEXT NOT NULL DEFAULT 'normal'"),
    ("entity", "TEXT NOT NULL DEFAULT ''"),
    ("validator_kind", "TEXT NOT NULL DEFAULT 'quality_kernel'"),
    ("provenance", "TEXT NOT NULL DEFAULT '{}'"),
]


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
            self._migrate_schema(conn)
            row = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO schema_meta(key, value) VALUES ('version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', ?)",
                    (str(SCHEMA_VERSION),),
                )
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

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()}
        for name, decl in _V3_COLUMNS:
            if name not in cols:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {decl}")

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
        ttl_days: Optional[int] = None,
        layer: Optional[str] = None,
        source: str = "commit_memory",
        supersedes_id: Optional[str] = None,
        authority: str = "agent",
        sensitivity: str = "normal",
        entity: str = "",
        validator_kind: str = "quality_kernel",
        provenance: Optional[dict] = None,
        status: str = "active",
    ) -> dict[str, Any]:
        """Insert a new memory row. Caller must run Quality Kernel first."""
        now = _utcnow()
        mid = _new_id()
        tags = context_tags or []
        if ttl_seconds is None:
            ttl_seconds = DEFAULT_TTL.get(memory_type)
        if ttl_days is None and ttl_seconds is not None:
            ttl_days = max(1, int(ttl_seconds // 86400))
        expires_at = None
        if ttl_seconds is not None:
            expires_at = (
                (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).replace(microsecond=0).isoformat()
            )
        layer = layer or ("scratch" if is_scratch else LAYER_DEFAULT.get(memory_type, "L2"))
        if is_scratch:
            layer = "scratch"

        summary = summary or fact_claim[:240]
        detail = detail or fact_claim
        prov = json.dumps(provenance or {}, ensure_ascii=False)

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO memories (
                    id, tenant_id, user_id, session_id, memory_type, fact_claim,
                    summary, detail, confidence, importance, emotional_salience,
                    content_hash, layer, status, is_negative_schema, is_scratch,
                    usage_count, context_tags, room, ttl_seconds, ttl_days, expires_at,
                    valid_from, created_at, updated_at, last_accessed, source,
                    supersedes_id, authority, sensitivity, entity, validator_kind,
                    provenance
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    mid,
                    tenant_id or "",
                    user_id,
                    session_id or "",
                    memory_type,
                    fact_claim,
                    summary,
                    detail,
                    confidence,
                    importance,
                    emotional_salience,
                    content_hash,
                    layer,
                    status or "active",
                    1 if is_negative_schema else 0,
                    1 if is_scratch else 0,
                    0,
                    json.dumps(tags, ensure_ascii=False),
                    room,
                    ttl_seconds,
                    ttl_days,
                    expires_at,
                    now,
                    now,
                    now,
                    now,
                    source,
                    supersedes_id,
                    authority or "agent",
                    sensitivity or "normal",
                    entity or "",
                    validator_kind or "quality_kernel",
                    prov,
                ),
            )
            if supersedes_id:
                conn.execute(
                    """UPDATE memories
                       SET status='archived', valid_to=?, updated_at=?,
                           superseded_by=?
                       WHERE id=? AND status='active'""",
                    (now, now, mid, supersedes_id),
                )
        return self.get_by_id(mid)  # type: ignore[return-value]

    def find_near_duplicates(
        self,
        tenant_id: str,
        user_id: str,
        claim: str,
        *,
        memory_type: str = "",
        limit: int = 8,
        min_token_overlap: float = 0.55,
    ) -> list[dict[str, Any]]:
        """FTS-assisted near-dup candidates with simple token Jaccard."""
        tokens = {t.lower() for t in claim.split() if len(t) >= 2}
        if len(tokens) < 2:
            return []
        # Use first few significant tokens for FTS
        seed = " ".join(sorted(tokens, key=len, reverse=True)[:6])
        hits = self.fts_search(seed, tenant_id=tenant_id, user_id=user_id, limit=limit)
        out: list[dict[str, Any]] = []
        for h in hits:
            if memory_type and h.get("memory_type") != memory_type:
                continue
            other = {t.lower() for t in (h.get("fact_claim") or "").split() if len(t) >= 2}
            if not other:
                continue
            inter = len(tokens & other)
            union = len(tokens | other) or 1
            jacc = inter / union
            if jacc >= min_token_overlap:
                h = dict(h)
                h["jaccard"] = round(jacc, 4)
                out.append(h)
        out.sort(key=lambda x: x.get("jaccard", 0), reverse=True)
        return out

    def list_expired(
        self,
        *,
        tenant_id: str = "",
        user_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        now = _utcnow()
        parts = [
            "SELECT * FROM memories WHERE status='active' AND valid_to IS NULL",
            "AND expires_at IS NOT NULL AND expires_at <= ?",
            "AND tenant_id=?",
        ]
        params: list[Any] = [now, tenant_id or ""]
        if user_id:
            parts.append("AND user_id=?")
            params.append(user_id)
        safe = max(1, min(int(limit), 500))
        parts.append(f"ORDER BY expires_at ASC LIMIT {safe}")
        with self._conn() as conn:
            rows = conn.execute(" ".join(parts), params).fetchall()
        return [dict(r) for r in rows]

    def find_hash_duplicates(
        self,
        *,
        tenant_id: str = "",
        user_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        parts = [
            """SELECT content_hash, COUNT(*) AS n, GROUP_CONCAT(id) AS ids
               FROM memories
               WHERE status='active' AND valid_to IS NULL AND tenant_id=?""",
        ]
        params: list[Any] = [tenant_id or ""]
        if user_id:
            parts.append("AND user_id=?")
            params.append(user_id)
        parts.append("GROUP BY content_hash HAVING n > 1 ORDER BY n DESC LIMIT 50")
        with self._conn() as conn:
            rows = conn.execute(" ".join(parts), params).fetchall()
        return [{"content_hash": r["content_hash"], "count": r["n"], "ids": (r["ids"] or "").split(",")} for r in rows]

    def rebuild_fts(self) -> dict[str, Any]:
        """Rebuild FTS5 content from memories (companion index hygiene)."""
        with self._conn() as conn:
            try:
                conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
                n = conn.execute("SELECT COUNT(*) AS n FROM memories_fts").fetchone()["n"]
                return {"status": "ok", "fts_rows": n}
            except sqlite3.OperationalError as e:
                # Fallback: delete + reinsert via triggers by touching rows
                try:
                    conn.execute("DELETE FROM memories_fts")
                    rows = conn.execute(
                        "SELECT rowid, id, fact_claim, summary, detail, context_tags FROM memories"
                    ).fetchall()
                    for r in rows:
                        conn.execute(
                            """INSERT INTO memories_fts(rowid, id, fact_claim, summary, detail, context_tags)
                               VALUES (?,?,?,?,?,?)""",
                            (r["rowid"], r["id"], r["fact_claim"], r["summary"], r["detail"], r["context_tags"]),
                        )
                    return {"status": "ok", "fts_rows": len(rows), "mode": "manual_reinsert"}
                except Exception as e2:
                    return {"status": "error", "message": f"{e}; fallback={e2}"}

    def find_by_hash(self, tenant_id: str, user_id: str, content_hash: str) -> Optional[dict[str, Any]]:
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
            row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
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

    def promote_scratch(self, tenant_id: str, user_id: str, session_id: str) -> list[str]:
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
        fts_query: str = "",
    ) -> list[dict[str, Any]]:
        """Full-text search via FTS5. Returns id + bm25 rank.

        The default query AND-s quoted tokens (near-duplicate search).
        ``fts_query`` replaces that, so recall can pass an ``OR`` query and
        still receive FTS5 ``bm25()`` ranks for the rows that match.
        """
        if fts_query.strip():
            fts_q = fts_query.strip()
        else:
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
                rows = conn.execute(sql, (fts_q, user_id, tenant_id or "", _utcnow())).fetchall()
            except sqlite3.OperationalError:
                return []
        return [dict(r) for r in rows]

    def iter_for_index(self, *, tenant_id: str = "", user_id: Optional[str] = None) -> list[dict[str, Any]]:
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

    def count_by_layer(self, *, tenant_id: str = "", user_id: Optional[str] = None) -> dict[str, int]:
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
            total = conn.execute("SELECT COUNT(*) AS n FROM memories WHERE status='active'").fetchone()["n"]
            archived = conn.execute("SELECT COUNT(*) AS n FROM memories WHERE status='archived'").fetchone()["n"]
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
        with self._conn() as conn:
            ver = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
            db_ver = int(ver["value"]) if ver else 0
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
            "db_schema_version": db_ver,
        }

    def _forget_filters(
        self,
        *,
        user_id: str,
        tenant_id: str = "",
        memory_id: str = "",
        memory_type: str = "",
        layer: str = "",
        session_id: str = "",
        query: str = "",
        match_all: bool = False,
    ) -> tuple[list[str], list[Any]] | None:
        parts = ["FROM memories WHERE user_id=? AND tenant_id=?"]
        params: list[Any] = [user_id, tenant_id or ""]
        if memory_id:
            parts.append("AND id=?")
            params.append(memory_id)
        else:
            if memory_type:
                parts.append("AND memory_type=?")
                params.append(memory_type)
            if layer:
                parts.append("AND layer=?")
                params.append(layer)
            if session_id:
                parts.append("AND session_id=?")
                params.append(session_id)
            if query:
                parts.append("AND instr(lower(fact_claim), ?) > 0")
                params.append(query.lower())
            if not any((memory_type, layer, session_id, query, match_all)):
                return None
        return parts, params

    def count_memories_for_forget(self, **kwargs: Any) -> int:
        built = self._forget_filters(**kwargs)
        if built is None:
            return 0
        parts, params = built
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n " + " ".join(parts), params).fetchone()
        return int(row["n"])

    def find_memories_for_forget(
        self,
        *,
        user_id: str,
        tenant_id: str = "",
        memory_id: str = "",
        memory_type: str = "",
        layer: str = "",
        session_id: str = "",
        query: str = "",
        match_all: bool = False,
        limit: int = 2000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """One page of rows in this tenant/user scope that a forget call would delete."""
        built = self._forget_filters(
            user_id=user_id,
            tenant_id=tenant_id,
            memory_id=memory_id,
            memory_type=memory_type,
            layer=layer,
            session_id=session_id,
            query=query,
            match_all=match_all,
        )
        if built is None:
            return []
        parts, params = built
        safe_limit = max(1, min(int(limit), 2000))
        safe_offset = max(0, int(offset))
        sql = "SELECT * " + " ".join(parts) + f" ORDER BY created_at ASC LIMIT {safe_limit} OFFSET {safe_offset}"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def supersede_chain(self, memory_id: str, *, user_id: str, tenant_id: str = "") -> list[dict[str, Any]]:
        """The row and every ancestor or successor linked by supersedes_id, inside scope."""
        seen: set[str] = set()
        ordered: list[dict[str, Any]] = []
        stack = [memory_id]
        while stack:
            mid = stack.pop()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            row = self.get_by_id(mid)
            if not row:
                continue
            if row.get("user_id") != user_id or (row.get("tenant_id") or "") != (tenant_id or ""):
                continue
            ordered.append(row)
            for key in ("supersedes_id", "superseded_by"):
                nxt = row.get(key)
                if nxt:
                    stack.append(nxt)
            with self._conn() as conn:
                extras = conn.execute(
                    """SELECT id FROM memories
                       WHERE user_id=? AND tenant_id=?
                         AND (supersedes_id=? OR superseded_by=?)""",
                    (user_id, tenant_id or "", mid, mid),
                ).fetchall()
            for extra in extras:
                stack.append(extra["id"])
        return ordered

    def delete_ids(self, ids: list[str], *, user_id: str, tenant_id: str = "") -> list[dict[str, Any]]:
        """Delete these ids when they belong to the scope. FTS rows follow the delete trigger."""
        if not ids:
            return []
        deleted: list[dict[str, Any]] = []
        with self._conn() as conn:
            for mid in ids:
                row = conn.execute(
                    "SELECT * FROM memories WHERE id=? AND user_id=? AND tenant_id=?",
                    (mid, user_id, tenant_id or ""),
                ).fetchone()
                if not row:
                    continue
                deleted.append(dict(row))
                conn.execute(
                    "DELETE FROM memories WHERE id=? AND user_id=? AND tenant_id=?",
                    (mid, user_id, tenant_id or ""),
                )
        return deleted

    def redact_audit_for_targets(self, ids: list[str]) -> int:
        """Keep audit rows for forgotten ids, but drop stored fact text."""
        if not ids:
            return 0
        changed = 0
        with self._conn() as conn:
            for mid in ids:
                cur = conn.execute(
                    """UPDATE audit_log
                       SET before_snap='[redacted]',
                           after_snap='[redacted]',
                           summary='[redacted] '||action
                       WHERE target=?""",
                    (mid,),
                )
                changed += cur.rowcount
        return changed

    def delete_memories(
        self,
        *,
        user_id: str,
        tenant_id: str = "",
        memory_id: str = "",
        memory_type: str = "",
        layer: str = "",
        session_id: str = "",
        query: str = "",
        match_all: bool = False,
    ) -> list[dict[str, Any]]:
        """Delete matching rows. The FTS delete trigger drops the index rows."""
        matched = self.find_memories_for_forget(
            user_id=user_id,
            tenant_id=tenant_id,
            memory_id=memory_id,
            memory_type=memory_type,
            layer=layer,
            session_id=session_id,
            query=query,
            match_all=match_all,
        )
        if not matched:
            return []
        ids = [row["id"] for row in matched]
        with self._conn() as conn:
            for mid in ids:
                conn.execute(
                    "DELETE FROM memories WHERE id=? AND user_id=? AND tenant_id=?",
                    (mid, user_id, tenant_id or ""),
                )
        return matched

    def _export_filters(
        self,
        *,
        user_id: str,
        tenant_id: str = "",
        session_id: str = "",
        include_archived: bool = False,
    ) -> tuple[str, list[Any]]:
        parts = ["FROM memories WHERE user_id=? AND tenant_id=?"]
        params: list[Any] = [user_id, tenant_id or ""]
        if session_id:
            parts.append("AND session_id=?")
            params.append(session_id)
        if not include_archived:
            parts.append("AND status='active' AND valid_to IS NULL")
        return " ".join(parts), params

    def count_for_export(self, **kwargs: Any) -> int:
        where, params = self._export_filters(**kwargs)
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n " + where, params).fetchone()
        return int(row["n"])

    def list_for_export(
        self,
        *,
        user_id: str,
        tenant_id: str = "",
        session_id: str = "",
        include_archived: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """One page of memories visible to this user and tenant, oldest first."""
        where, params = self._export_filters(
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            include_archived=include_archived,
        )
        safe = max(1, min(int(limit or 500), 2000))
        safe_offset = max(0, int(offset))
        sql = f"SELECT * {where} ORDER BY created_at ASC LIMIT {safe} OFFSET {safe_offset}"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def candidates_for_digest(self, older_than_days: int = 30) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).replace(microsecond=0).isoformat()
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
                    action,
                    agent_id,
                    tenant_id or "",
                    user_id or "",
                    session_id or "",
                    target,
                    summary,
                    before[:2000],
                    after[:2000],
                    _utcnow(),
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
                    tool_name,
                    tenant_id or "",
                    user_id or "",
                    session_id or "",
                    args_digest[:500],
                    result_status,
                    error_code,
                    latency_ms,
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
