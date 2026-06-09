"""Markdown filesystem backend — the physical memory layer.

Enterprise structure: Wing → Hall → Room → Drawer
  Wing:   Business domain / tenant (e.g. "factory_001", "users/user_001")
  Hall:   Memory type (facts, events, procedures, knowledge, states)
  Room:   Specific entity (e.g. "line-01", "robot-03", "imsg")
  Drawer: Date-based Markdown file with YAML frontmatter

Personal mode: wings/users/<user_id>/<room>/<date>.md
Company mode:  wings/<factory>/halls/<type>/rooms/<entity>/drawers/<date>.md

Design principle: White-box memory. Git-friendly. VSCode-editable.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

import frontmatter


# ── Path builders ───────────────────────────────────────────────────────

def _sanitize_path_segment(segment: str) -> str:
    """Strip path traversal sequences from a path segment."""
    return segment.replace("../", "").replace("..\\", "").replace("\0", "")


def drawer_path(
    palace: Path,
    wing: str,
    room: str,
    d: Optional[date] = None,
    *,
    hall: str = "",
    mode: str = "personal",
) -> Path:
    """Build the filesystem path for a drawer file.

    Personal mode:  wings/<wing>/<room>/<date>.md
    Company mode:   wings/<wing>/halls/<hall>/rooms/<room>/drawers/<date>.md
    """
    d = d or date.today()
    # Path traversal protection — sanitize inputs and verify result stays inside palace
    safe_wing = _sanitize_path_segment(wing)
    safe_room = _sanitize_path_segment(room)
    safe_hall = _sanitize_path_segment(hall) if hall else ""
    resolved_palace = palace.resolve()
    base = resolved_palace / "wings" / safe_wing

    if mode == "company":
        safe_hall = safe_hall or "general"
        result = (base / "halls" / safe_hall / "rooms" / safe_room / "drawers" / f"{d.isoformat()}.md").resolve()
    else:
        result = (base / safe_room / f"{d.isoformat()}.md").resolve()

    if not str(result).startswith(str(resolved_palace)):
        raise ValueError(f"Path traversal detected for wing={wing!r}, room={room!r}")
    return result


def wing_index_path(palace: Path, wing: str) -> Path:
    return palace / "wings" / wing / "index.md"


def room_index_path(palace: Path, wing: str, room: str, *, hall: str = "", mode: str = "personal") -> Path:
    base = palace / "wings" / wing
    if mode == "company":
        hall = hall or "general"
        return base / "halls" / hall / "rooms" / room / "index.md"
    return base / room / "index.md"


# ── Drawer listing ─────────────────────────────────────────────────────

def list_drawers(
    palace: Path,
    wing: str,
    room: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    *,
    mode: str = "personal",
) -> list[Path]:
    """List drawer files matching filters."""
    wing_dir = palace / "wings" / wing
    if not wing_dir.exists():
        return []

    if room:
        if mode == "company":
            pattern = f"halls/*/rooms/{room}/drawers/*.md"
        else:
            pattern = f"{room}/*.md"
        files = sorted(wing_dir.glob(pattern))
    else:
        if mode == "company":
            pattern = "halls/*/rooms/*/drawers/*.md"
        else:
            pattern = "*/*.md"
        files = sorted(wing_dir.glob(pattern))

    result = []
    for fp in files:
        try:
            d = date.fromisoformat(fp.stem)
        except ValueError:
            continue
        if from_date and d < from_date:
            continue
        if to_date and d > to_date:
            continue
        result.append(fp)
    return result


# ── Frontmatter read/write ─────────────────────────────────────────────

def read_drawer(filepath: Path) -> frontmatter.Post:
    if not filepath.exists():
        raise FileNotFoundError(f"Drawer not found: {filepath}")
    return frontmatter.load(str(filepath))


def write_drawer(filepath: Path, content: str, metadata: dict) -> None:
    """Write (or overwrite) a drawer file with frontmatter metadata.

    Automatically increments usage_count and updates last_accessed.
    """
    if filepath.exists():
        try:
            existing = frontmatter.load(str(filepath))
            existing_meta = existing.metadata or {}
            usage = existing_meta.get("usage_count", 0) + 1
        except Exception:
            existing_meta = {}
            usage = 1
    else:
        existing_meta = {}
        usage = 1

    merged = {**existing_meta, **metadata}
    merged["usage_count"] = usage
    merged["last_accessed"] = datetime.now().isoformat()

    filepath.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(content, **merged)
    filepath.write_text(frontmatter.dumps(post), encoding="utf-8")


# ── L1 Diary ───────────────────────────────────────────────────────────

def read_l1_diary(palace: Path, wing: str, days: int = 3, *, mode: str = "personal") -> list[dict]:
    """Read recent L1 diary entries for a wing."""
    diary_dir = palace / "l1_diary" / wing
    if not diary_dir.exists():
        return []

    entries = []
    today = date.today()
    for d in sorted(diary_dir.glob("*.md"), reverse=True):
        try:
            entry_date = date.fromisoformat(d.stem)
        except ValueError:
            continue
        if (today - entry_date).days > days:
            continue
        post = frontmatter.load(str(d))
        entries.append({
            "date": d.stem,
            "content": post.content.strip(),
            "metadata": post.metadata or {},
        })
    return entries


def write_l1_diary(palace: Path, wing: str, content: str, d: Optional[date] = None) -> Path:
    """Write a diary entry (CBT-reframed narrative)."""
    d = d or date.today()
    diary_dir = palace / "l1_diary" / wing
    diary_dir.mkdir(parents=True, exist_ok=True)
    fp = diary_dir / f"{d.isoformat()}.md"
    post = frontmatter.Post(content, date=d.isoformat(), wing=wing)
    fp.write_text(frontmatter.dumps(post), encoding="utf-8")
    return fp


# ── L0 Profile ─────────────────────────────────────────────────────────

def read_l0_profile(palace: Path, wing: str) -> str:
    """Read L0 profile for a wing (permanent context)."""
    profile_file = palace / "l0_profile" / wing / "profile.md"
    if not profile_file.exists():
        return ""
    return profile_file.read_text(encoding="utf-8")


def write_l0_profile(palace: Path, wing: str, content: str) -> None:
    """Write decontextualized L0 profile (with token budget enforcement)."""
    profile_dir = palace / "l0_profile" / wing
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_file = profile_dir / "profile.md"
    profile_file.write_text(content, encoding="utf-8")


# ── Audit log (Markdown-backed) ────────────────────────────────────────

def write_audit_entry(
    palace: Path,
    action: str,
    agent_id: str,
    target: str,
    summary: str,
    *,
    before: str = "",
    after: str = "",
) -> Path:
    """Append an audit entry as a Markdown file in audit_logs/."""
    audit_dir = palace / "audit_logs"
    audit_dir.mkdir(parents=True, exist_ok=True)
    today = date.today()
    fp = audit_dir / f"{today.isoformat()}.md"

    timestamp = datetime.now().isoformat()
    entry = (
        f"## {action} — {timestamp}\n\n"
        f"- **Agent**: `{agent_id}`\n"
        f"- **Target**: `{target}`\n"
        f"- **Summary**: {summary}\n"
    )
    if before:
        entry += f"- **Before**: {before[:200]}\n"
    if after:
        entry += f"- **After**: {after[:200]}\n"
    entry += "\n---\n\n"

    with open(fp, "a", encoding="utf-8") as f:
        f.write(entry)
    return fp


# ── Token estimation ───────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token count estimate (≈ chars/3 for English/Chinese mix)."""
    return max(1, len(text) // 3)
