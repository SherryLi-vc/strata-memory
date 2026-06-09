"""Enhanced Triples schema — psych-validated semantic memory network.

Implements the expanded triples table from the cognitive psychology review:
  - emotional_salience (0.0–1.0)
  - is_negative_schema (CBT isolation flag)
  - context_tags (state-dependent retrieval)
  - episode_index (links to original episodic sequence)
  - valid_from / valid_to (Inhibitory Control — mark stale, don't delete)
  - decontextualized_proposition (for L0 promotion)

Psych foundation: Collins & Quillian (1969) Semantic Network model.
"""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

TRIPLES_DDL = """
CREATE TABLE IF NOT EXISTS triples (
    id                  TEXT PRIMARY KEY,
    subject             TEXT NOT NULL,
    predicate           TEXT NOT NULL,
    object              TEXT NOT NULL,
    confidence          REAL DEFAULT 1.0,
    importance          REAL DEFAULT 0.5,
    emotional_salience  REAL DEFAULT 0.0,
    usage_count         INTEGER DEFAULT 0,
    last_accessed       TEXT,
    valid_from          TEXT,
    valid_to            TEXT,
    source_drawer       TEXT,
    category            TEXT DEFAULT 'event',
    context_tags        TEXT DEFAULT '[]',
    episode_index       TEXT,
    is_negative_schema  BOOLEAN DEFAULT FALSE,
    decontextualized    TEXT DEFAULT '',
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
CREATE INDEX IF NOT EXISTS idx_triples_neg_schema ON triples(is_negative_schema);
CREATE INDEX IF NOT EXISTS idx_triples_category ON triples(category);
"""

AUDIT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    target      TEXT NOT NULL,
    summary     TEXT,
    before_snap TEXT,
    after_snap  TEXT,
    ip_source   TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
"""


class TripleStore:
    """SQLite-backed semantic memory network (enhanced V2 schema)."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript(TRIPLES_DDL)
            conn.executescript(AUDIT_LOG_DDL)
            conn.commit()

    def upsert(self, subject: str, predicate: str, object_: str, **kwargs) -> str:
        """Insert or update a triple. Returns the triple id."""
        import uuid
        triple_id = kwargs.pop("id", None) or uuid.uuid4().hex[:16]

        with sqlite3.connect(str(self.db_path)) as conn:
            existing = conn.execute(
                "SELECT id, usage_count FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                (subject, predicate, object_)
            ).fetchone()

            if existing:
                triple_id = existing[0]
                usage = existing[1] + 1
                conn.execute(
                    """UPDATE triples SET
                       confidence=?, importance=?, emotional_salience=?,
                       usage_count=?, last_accessed=?, context_tags=?,
                       decontextualized=?
                       WHERE id=?""",
                    (
                        kwargs.get("confidence", 1.0),
                        kwargs.get("importance", 0.5),
                        kwargs.get("emotional_salience", 0.0),
                        usage,
                        datetime.now().isoformat(),
                        json.dumps(kwargs.get("context_tags", [])),
                        kwargs.get("decontextualized", ""),
                        triple_id,
                    )
                )
            else:
                conn.execute(
                    """INSERT INTO triples (id, subject, predicate, object,
                       confidence, importance, emotional_salience,
                       usage_count, last_accessed, valid_from,
                       source_drawer, category, context_tags,
                       episode_index, is_negative_schema, decontextualized)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        triple_id, subject, predicate, object_,
                        kwargs.get("confidence", 1.0),
                        kwargs.get("importance", 0.5),
                        kwargs.get("emotional_salience", 0.0),
                        1,
                        datetime.now().isoformat(),
                        kwargs.get("valid_from", datetime.now().isoformat()),
                        kwargs.get("source_drawer", ""),
                        kwargs.get("category", "event"),
                        json.dumps(kwargs.get("context_tags", [])),
                        kwargs.get("episode_index", ""),
                        kwargs.get("is_negative_schema", False),
                        kwargs.get("decontextualized", ""),
                    )
                )
            conn.commit()
        return triple_id

    def expire(self, subject: str, predicate: str, object_: str) -> None:
        """Mark a triple as expired (Inhibitory Control — don't delete)."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                (datetime.now().isoformat(), subject, predicate, object_)
            )
            conn.commit()

    def query(self, subject: Optional[str] = None, predicate: Optional[str] = None,
              object_: Optional[str] = None, exclude_negative: bool = True,
              limit: int = 50) -> list[dict]:
        """Query triples with optional filters."""
        parts = ["SELECT * FROM triples WHERE valid_to IS NULL"]
        params: list = []

        if subject:
            parts.append("AND subject = ?")
            params.append(subject)
        if predicate:
            parts.append("AND predicate = ?")
            params.append(predicate)
        if object_:
            parts.append("AND object = ?")
            params.append(object_)
        if exclude_negative:
            parts.append("AND is_negative_schema = 0")

        safe_limit = max(1, min(int(limit or 50), 500))
        parts.append(f"ORDER BY importance DESC, usage_count DESC LIMIT {safe_limit}")

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(" ".join(parts), params).fetchall()

        return [dict(r) for r in rows]

    def audit_log(self, action: str, agent_id: str, target: str,
                  summary: str = "", before: str = "", after: str = "") -> None:
        """Write to the audit_log table."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """INSERT INTO audit_log (action, agent_id, target, summary, before_snap, after_snap)
                   VALUES (?,?,?,?,?,?)""",
                (action, agent_id, target, summary, before, after)
            )
            conn.commit()
