"""Tests for 0.2 Markdown → 2.0 SQLite migration."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.ops.migrate_v02 import (
    _category_to_type,
    _ground_fuzzy_time,
    _split_claims,
    migrate_palace,
)
from strata_memory.storage.truth_store import TruthStore


def _write_drawer(path: Path, content: str, **meta) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(content, **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


@pytest.fixture
def palace_v02(tmp_path: Path) -> Path:
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(palace_path=str(palace), version="2.0.0", mode="personal")
    save_config(cfg)

    # Personal drawer
    _write_drawer(
        palace / "wings" / "users" / "alice" / "general" / "2026-06-09.md",
        "User prefers dark mode in VS Code with Monokai Pro theme.",
        date="2026-06-09",
        wing="users/alice",
        room="general",
        category="preference",
        importance=0.8,
        context_tags=["ide", "theme"],
        usage_count=3,
    )
    # Multi-paragraph event
    _write_drawer(
        palace / "wings" / "users" / "alice" / "work" / "2026-06-08.md",
        "昨天讨论了 Q3 路线图。\n\nSprint 优先项是 auth 重构与记忆系统集成。",
        date="2026-06-08",
        wing="users/alice",
        room="work",
        category="event",
        importance=0.6,
    )
    # L0 profile
    (palace / "l0_profile" / "users" / "alice").mkdir(parents=True)
    (palace / "l0_profile" / "users" / "alice" / "profile.md").write_text(
        "---\nwing: users/alice\n---\n\n"
        "User is a senior backend engineer. Prefers Python and Go.\n",
        encoding="utf-8",
    )
    # Secret should be skipped
    _write_drawer(
        palace / "wings" / "users" / "alice" / "secrets" / "2026-06-01.md",
        "Production password is hunter2_should_never_store_this_value",
        date="2026-06-01",
        wing="users/alice",
        room="secrets",
        category="fact",
    )
    return palace


def test_category_mapping():
    assert _category_to_type("preference") == "user_preference"
    assert _category_to_type("procedure") == "procedure_rule"
    assert _category_to_type("event") == "episodic_event"
    assert _category_to_type("fact") == "factual_truth"


def test_split_claims_paragraphs():
    body = "First durable fact about tooling.\n\nSecond durable fact about deploy."
    claims = _split_claims(body)
    assert len(claims) == 2


def test_ground_fuzzy_time():
    out = _ground_fuzzy_time("昨天用户开会讨论迁移", "2026-06-08")
    assert "2026-06-08" in out or "day before" in out


def test_dry_run_does_not_write(palace_v02: Path):
    store = TruthStore(truth_db_path(palace_v02))
    before = store.stats()["active"]
    report = migrate_palace(palace_v02, dry_run=True, store=store)
    assert report.files_scanned >= 3
    assert report.claims_found >= 2
    assert report.imported >= 1  # would-import count
    after = store.stats()["active"]
    assert after == before


def test_apply_imports_and_dedup(palace_v02: Path):
    store = TruthStore(truth_db_path(palace_v02))
    r1 = migrate_palace(palace_v02, dry_run=False, store=store)
    assert r1.imported >= 2
    assert r1.skipped >= 1  # secret

    rows = store.list_active(user_id="alice", limit=50)
    assert any("dark mode" in r["fact_claim"] for r in rows)
    # L0 profile should land
    assert any(r["layer"] == "L0" for r in rows)

    # Idempotent second run
    r2 = migrate_palace(palace_v02, dry_run=False, store=store)
    assert r2.deduped >= r1.imported
    assert r2.imported == 0


def test_user_filter(palace_v02: Path):
    store = TruthStore(truth_db_path(palace_v02))
    report = migrate_palace(
        palace_v02, dry_run=False, store=store, user_id_filter="nobody"
    )
    assert report.imported == 0
    assert store.stats()["active"] == 0
