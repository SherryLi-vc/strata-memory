"""Migrate Strata Memory 0.2 Markdown drawers → 2.0 SQLite Truth Store.

0.2 layout (personal):
  palace/wings/users/<user_id>/<room>/<YYYY-MM-DD>.md
  palace/l0_profile/users/<user_id>/profile.md
  palace/l1_diary/users/<user_id>/<YYYY-MM-DD>.md

0.2 layout (company):
  palace/wings/<tenant>/halls/<hall>/rooms/<room>/drawers/<YYYY-MM-DD>.md

Each Markdown file may contain YAML frontmatter:
  date, wing, room, category, importance, emotional_salience,
  context_tags, is_negative_schema, tenant_id, usage_count, ...

Design:
  - SQLite is write target (SoT). Source Markdown is never deleted.
  - Secrets are redacted or skipped (never re-poison SoT).
  - Relative time is grounded with the drawer date (migration only).
  - Idempotent: content_hash dedup within tenant+user.
  - dry_run previews without writing.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Optional

import frontmatter

from ..config import Config, ensure_palace, is_initialized, load_config, truth_db_path
from ..governance.cbt_middleware import CBTMiddleware
from ..governance.quality_kernel import (
    MAX_CLAIM_CHARS,
    MIN_CLAIM_CHARS,
    QualityKernel,
    SECRET_PATTERNS,
)
from ..storage.truth_store import DEFAULT_TTL, LAYER_DEFAULT, TruthStore

# ── Category → memory_type ──────────────────────────────────────────────

CATEGORY_TO_TYPE: dict[str, str] = {
    "event": "episodic_event",
    "preference": "user_preference",
    "procedure": "procedure_rule",
    "core_identity": "factual_truth",
    "lesson": "episodic_event",
    "fact": "factual_truth",
    "goal": "user_preference",
    "relationship": "factual_truth",
    # already 2.0 names
    "factual_truth": "factual_truth",
    "user_preference": "user_preference",
    "procedure_rule": "procedure_rule",
    "episodic_event": "episodic_event",
}

SKIP_NAMES = frozenset({"index.md", "readme.md", ".ds_store"})

# Soft fuzzy time — for migration we replace rather than reject
FUZZY_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"刚才|刚刚", re.I), "earlier that day"),
    (re.compile(r"\btoday\b|今天", re.I), "on {date}"),
    (re.compile(r"\byesterday\b|昨天", re.I), "the day before {date}"),
    (re.compile(r"\btomorrow\b|明天", re.I), "the day after {date}"),
    (re.compile(r"上周|last week", re.I), "the week before {date}"),
    (re.compile(r"下周|next week", re.I), "the week after {date}"),
    (re.compile(r"最近|recently|不久前|a while ago|earlier", re.I), "around {date}"),
]


@dataclass
class MigratedItem:
    source_path: str
    user_id: str
    tenant_id: str
    room: str
    memory_type: str
    fact_claim: str
    content_hash: str
    status: str  # imported | deduped | skipped | error
    reason: str = ""
    memory_id: str = ""


@dataclass
class MigrationReport:
    palace: str
    dry_run: bool
    files_scanned: int = 0
    claims_found: int = 0
    imported: int = 0
    deduped: int = 0
    skipped: int = 0
    errors: int = 0
    items: list[MigratedItem] = field(default_factory=list)
    vector_rebuild: Optional[dict[str, Any]] = None

    def summary(self) -> dict[str, Any]:
        return {
            "palace": self.palace,
            "dry_run": self.dry_run,
            "files_scanned": self.files_scanned,
            "claims_found": self.claims_found,
            "imported": self.imported,
            "deduped": self.deduped,
            "skipped": self.skipped,
            "errors": self.errors,
            "vector_rebuild": self.vector_rebuild,
            "sample_items": [asdict(i) for i in self.items[:40]],
        }


def _category_to_type(category: str | None) -> str:
    if not category:
        return "episodic_event"
    return CATEGORY_TO_TYPE.get(str(category).strip().lower(), "episodic_event")


def _ground_fuzzy_time(text: str, anchor: str) -> str:
    out = text
    for pat, repl in FUZZY_REPLACEMENTS:
        out = pat.sub(repl.format(date=anchor), out)
    return out


def _split_claims(body: str) -> list[str]:
    """Split drawer body into atomic-ish claims.

    Prefer blank-line paragraphs; fall back to whole body.
    """
    body = (body or "").strip()
    if not body:
        return []
    # Strip common heading lines
    lines = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    if not cleaned:
        return []

    parts = re.split(r"\n\s*\n+", cleaned)
    claims: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Bullet lists → one claim per bullet if short enough
        bullets = re.findall(r"^[\-\*\u2022]\s+(.+)$", p, re.M)
        if bullets and len(bullets) >= 2:
            for b in bullets:
                b = b.strip()
                if len(b) >= MIN_CLAIM_CHARS:
                    claims.append(b[:MAX_CLAIM_CHARS])
            continue
        # Long block → hard-split by sentence-ish boundaries under max chars
        if len(p) <= MAX_CLAIM_CHARS:
            claims.append(p)
        else:
            chunks = re.split(r"(?<=[。.!！?？])\s+", p)
            buf = ""
            for c in chunks:
                if len(buf) + len(c) + 1 <= MAX_CLAIM_CHARS:
                    buf = f"{buf} {c}".strip()
                else:
                    if buf:
                        claims.append(buf[:MAX_CLAIM_CHARS])
                    buf = c[:MAX_CLAIM_CHARS]
            if buf and len(buf) >= MIN_CLAIM_CHARS:
                claims.append(buf)
    return [c for c in claims if len(c.strip()) >= MIN_CLAIM_CHARS]


def _contains_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def _parse_user_from_wing(wing: str, path: Path, palace: Path) -> tuple[str, str]:
    """Return (user_id, tenant_id) from wing meta or path."""
    wing = (wing or "").strip()
    if wing.startswith("users/"):
        return wing.split("/", 1)[1] or "unknown", ""
    # path: wings/users/<uid>/...
    try:
        rel = path.resolve().relative_to(palace.resolve())
        parts = rel.parts
        if len(parts) >= 3 and parts[0] == "wings" and parts[1] == "users":
            return parts[2], ""
        if len(parts) >= 2 and parts[0] == "wings":
            # company: wings/<tenant>/...
            return parts[1], parts[1]
        if len(parts) >= 3 and parts[0] == "l0_profile" and parts[1] == "users":
            return parts[2], ""
        if len(parts) >= 3 and parts[0] == "l1_diary" and parts[1] == "users":
            return parts[2], ""
    except ValueError:
        pass
    return wing or "unknown", ""


def _date_from_path_or_meta(path: Path, meta: dict) -> str:
    d = meta.get("date")
    if d:
        return str(d)[:10]
    try:
        return date.fromisoformat(path.stem).isoformat()
    except ValueError:
        return date.today().isoformat()


def iter_markdown_sources(palace: Path) -> Iterator[Path]:
    """Yield candidate Markdown files under a 0.2 palace."""
    roots = [
        palace / "wings",
        palace / "l0_profile",
        palace / "l1_diary",
        palace / "l3_cold",
    ]
    for root in roots:
        if not root.exists():
            continue
        for fp in sorted(root.rglob("*.md")):
            if fp.name.lower() in SKIP_NAMES:
                continue
            if "projection" in fp.parts:
                continue
            if "audit_logs" in fp.parts:
                continue
            yield fp


def _load_post(path: Path) -> tuple[dict, str]:
    try:
        post = frontmatter.load(str(path))
        meta = dict(post.metadata or {})
        content = (post.content or "").strip()
        return meta, content
    except Exception:
        text = path.read_text(encoding="utf-8", errors="replace")
        return {}, text.strip()


def migrate_palace(
    palace: Path | str,
    *,
    dry_run: bool = True,
    tenant_id_override: str = "",
    user_id_filter: str = "",
    skip_secrets: bool = True,
    relax_fuzzy: bool = True,
    min_confidence: float = 0.7,
    rebuild_vectors: bool = False,
    embed_provider: Any = None,
    chroma: Any = None,
    store: Optional[TruthStore] = None,
    config: Optional[Config] = None,
) -> MigrationReport:
    """Scan 0.2 Markdown under palace and import into SQLite SoT."""
    palace = Path(palace).expanduser().resolve()
    report = MigrationReport(palace=str(palace), dry_run=dry_run)

    if not palace.exists():
        report.errors += 1
        report.items.append(MigratedItem(
            source_path=str(palace), user_id="", tenant_id="", room="",
            memory_type="", fact_claim="", content_hash="",
            status="error", reason="Palace path does not exist",
        ))
        return report

    if config is None:
        if is_initialized(str(palace)):
            config = load_config(str(palace))
        else:
            config = Config(palace_path=str(palace), version="2.0.0")
            ensure_palace(palace)

    if store is None and not dry_run:
        ensure_palace(palace)
        store = TruthStore(truth_db_path(palace))
    elif store is None and dry_run:
        # ephemeral in-memory-ish: still open real path but we won't write if dry_run
        ensure_palace(palace)
        store = TruthStore(truth_db_path(palace))

    cbt = CBTMiddleware(enabled=True)
    kernel = QualityKernel(min_confidence=0.1)  # migration uses own confidence floor

    for fp in iter_markdown_sources(palace):
        report.files_scanned += 1
        meta, body = _load_post(fp)
        if not body:
            report.skipped += 1
            report.items.append(MigratedItem(
                source_path=str(fp), user_id="", tenant_id="", room=str(meta.get("room", "")),
                memory_type="", fact_claim="", content_hash="",
                status="skipped", reason="empty body",
            ))
            continue

        wing = str(meta.get("wing") or "")
        user_id, tenant_from_path = _parse_user_from_wing(wing, fp, palace)
        tenant_id = (
            tenant_id_override
            or str(meta.get("tenant_id") or "")
            or tenant_from_path
            or (config.tenant_id if config else "")
            or ""
        )
        if user_id_filter and user_id != user_id_filter:
            report.skipped += 1
            continue

        room = str(meta.get("room") or "general")
        # Company path: extract room from .../rooms/<room>/drawers/
        if "rooms" in fp.parts:
            try:
                idx = fp.parts.index("rooms")
                if idx + 1 < len(fp.parts):
                    room = fp.parts[idx + 1]
            except ValueError:
                pass

        # L0 profile → factual_truth preference boost
        is_l0 = "l0_profile" in fp.parts
        is_l1 = "l1_diary" in fp.parts
        category = meta.get("category")
        if is_l0 and not category:
            category = "core_identity"
        if is_l1 and not category:
            category = "event"
        memory_type = _category_to_type(str(category) if category else None)

        anchor = _date_from_path_or_meta(fp, meta)
        importance = float(meta.get("importance", 0.5) or 0.5)
        emotional = float(meta.get("emotional_salience", 0.0) or 0.0)
        is_neg = bool(meta.get("is_negative_schema", False))
        tags = meta.get("context_tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = [t.strip() for t in tags.split(",") if t.strip()]
        usage = int(meta.get("usage_count", 0) or 0)

        claims = _split_claims(body)
        if not claims:
            report.skipped += 1
            report.items.append(MigratedItem(
                source_path=str(fp), user_id=user_id, tenant_id=tenant_id, room=room,
                memory_type=memory_type, fact_claim="", content_hash="",
                status="skipped", reason="no claims extracted",
            ))
            continue

        for claim in claims:
            report.claims_found += 1
            raw = claim.strip()

            # Secrets
            if _contains_secret(raw):
                red = cbt.redact(raw)
                if skip_secrets and (red.redacted is False or _contains_secret(red.text)):
                    report.skipped += 1
                    report.items.append(MigratedItem(
                        source_path=str(fp), user_id=user_id, tenant_id=tenant_id,
                        room=room, memory_type=memory_type, fact_claim=raw[:120],
                        content_hash="", status="skipped",
                        reason="SECRET_DETECTED — not migrated",
                    ))
                    continue
                raw = red.text

            # Ground fuzzy time for historical drawers
            if relax_fuzzy:
                grounded = _ground_fuzzy_time(raw, anchor)
                if grounded != raw:
                    raw = f"[{anchor}] {grounded}"
                elif not re.search(r"\d{4}-\d{2}-\d{2}", raw):
                    # stamp anchor for episodic events to avoid future fuzzy rejects
                    if memory_type == "episodic_event":
                        raw = f"[{anchor}] {raw}"
            else:
                grounded = raw

            # CBT assessment (migration: keep negative but flag)
            assessment = cbt.assess(raw)
            if assessment.redacted_text:
                raw = assessment.redacted_text
            if assessment.is_negative_schema:
                is_neg = True

            # Map through kernel for hash / layer / type check (but bypass fuzzy reject)
            # Use a migration-safe claim that already has absolute date stamps
            conf = max(min_confidence, min(1.0, 0.5 + importance * 0.5))
            # Soft length clamp
            if len(raw) < MIN_CLAIM_CHARS:
                report.skipped += 1
                report.items.append(MigratedItem(
                    source_path=str(fp), user_id=user_id, tenant_id=tenant_id,
                    room=room, memory_type=memory_type, fact_claim=raw,
                    content_hash="", status="skipped", reason="CLAIM_TOO_SHORT",
                ))
                continue
            if len(raw) > MAX_CLAIM_CHARS:
                raw = raw[: MAX_CLAIM_CHARS - 3] + "..."

            chash = QualityKernel.content_hash(raw)
            layer = LAYER_DEFAULT.get(memory_type, "L2")
            if is_l0:
                layer = "L0"
            if is_neg:
                # historical negative → L2, not L0 (cooling already passed for old data)
                if layer == "L0":
                    layer = "L2"

            # Dedup
            existing = store.find_by_hash(tenant_id, user_id, chash) if store else None
            if existing:
                report.deduped += 1
                if not dry_run and store:
                    store.touch(existing["id"])
                report.items.append(MigratedItem(
                    source_path=str(fp), user_id=user_id, tenant_id=tenant_id,
                    room=room, memory_type=memory_type, fact_claim=raw[:200],
                    content_hash=chash, status="deduped",
                    reason="content_hash already in SoT",
                    memory_id=existing["id"],
                ))
                continue

            if dry_run:
                report.imported += 1  # would import
                report.items.append(MigratedItem(
                    source_path=str(fp), user_id=user_id, tenant_id=tenant_id,
                    room=room, memory_type=memory_type, fact_claim=raw[:200],
                    content_hash=chash, status="imported",
                    reason="dry_run preview",
                ))
                continue

            assert store is not None
            try:
                row = store.insert_memory(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id="",
                    memory_type=memory_type,
                    fact_claim=raw,
                    content_hash=chash,
                    confidence=conf,
                    importance=importance,
                    emotional_salience=emotional,
                    summary=raw[:240],
                    detail=raw,
                    is_negative_schema=is_neg,
                    is_scratch=False,
                    context_tags=list(tags) if tags else [],
                    room=room,
                    ttl_seconds=DEFAULT_TTL.get(memory_type),
                    layer=layer,
                    source="migrate_v02",
                )
                # preserve usage_count if present
                if usage > 0:
                    with store._conn() as conn:
                        conn.execute(
                            "UPDATE memories SET usage_count=?, last_accessed=COALESCE(last_accessed, created_at) WHERE id=?",
                            (usage, row["id"]),
                        )
                report.imported += 1
                report.items.append(MigratedItem(
                    source_path=str(fp), user_id=user_id, tenant_id=tenant_id,
                    room=room, memory_type=memory_type, fact_claim=raw[:200],
                    content_hash=chash, status="imported",
                    memory_id=row["id"],
                    reason=f"layer={layer}",
                ))
            except Exception as e:
                report.errors += 1
                report.items.append(MigratedItem(
                    source_path=str(fp), user_id=user_id, tenant_id=tenant_id,
                    room=room, memory_type=memory_type, fact_claim=raw[:200],
                    content_hash=chash, status="error", reason=str(e),
                ))

    if not dry_run and store:
        store.audit(
            "migrate_v02",
            summary=(
                f"files={report.files_scanned} claims={report.claims_found} "
                f"imported={report.imported} deduped={report.deduped} "
                f"skipped={report.skipped} errors={report.errors}"
            ),
            target=str(palace),
        )

    # Optional vector rebuild (async-friendly caller can pass providers)
    if rebuild_vectors and not dry_run and embed_provider is not None and chroma is not None and store is not None:
        import asyncio
        from .rebuild import strata_rebuild_index

        async def _rebuild():
            return await strata_rebuild_index(
                config=config or load_config(str(palace)),
                store=store,
                embed_provider=embed_provider,
                chroma=chroma,
                confirm=True,
                tenant_id=tenant_id_override or (config.tenant_id if config else ""),
            )

        try:
            report.vector_rebuild = asyncio.get_event_loop().run_until_complete(_rebuild())
        except RuntimeError:
            report.vector_rebuild = asyncio.run(_rebuild())
        except Exception as e:
            report.vector_rebuild = {"status": "error", "message": str(e)}

    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate Strata Memory 0.2 Markdown drawers into 2.0 SQLite SoT.",
    )
    parser.add_argument(
        "--palace",
        default="",
        help="Path to 0.2 palace (default: STRATA_PALACE or ~/.strata/palace)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write to SQLite. Default is dry-run preview.",
    )
    parser.add_argument("--tenant-id", default="", help="Force tenant_id on all rows")
    parser.add_argument("--user-id", default="", help="Only migrate this user_id")
    parser.add_argument(
        "--import-secrets",
        action="store_true",
        help="Attempt redaction import of secret-like text (default: skip)",
    )
    parser.add_argument(
        "--strict-fuzzy",
        action="store_true",
        help="Do not auto-ground relative time with drawer date",
    )
    parser.add_argument(
        "--rebuild-vectors",
        action="store_true",
        help="After apply, rebuild Chroma index from SQLite (needs STRATA_API_KEY)",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Write JSON report to this path",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.7,
        help="Confidence stamped on migrated rows (default 0.7)",
    )
    args = parser.parse_args(argv)

    import os

    palace = args.palace or os.environ.get("STRATA_PALACE") or str(Path.home() / ".strata" / "palace")
    palace_path = Path(palace).expanduser()

    embed_provider = None
    chroma = None
    config = None
    if args.rebuild_vectors and args.apply:
        from ..config import load_config as lc
        from ..embedding import EmbeddingProvider
        from ..storage.chroma import ChromaStore

        config = lc(str(palace_path)) if is_initialized(str(palace_path)) else Config(palace_path=str(palace_path))
        if not config.embedding.api_key and not os.environ.get("STRATA_API_KEY"):
            print("ERROR: --rebuild-vectors requires STRATA_API_KEY", flush=True)
            return 2
        if os.environ.get("STRATA_API_KEY"):
            config.embedding.api_key = os.environ["STRATA_API_KEY"]
        embed_provider = EmbeddingProvider.create(
            provider=config.embedding.provider,
            model=config.embedding.model,
            base_url=config.embedding.base_url,
            api_key=config.embedding.api_key,
            dimension=config.embedding.dimension,
        )
        chroma = ChromaStore(palace_path / "l2_vector")

    report = migrate_palace(
        palace_path,
        dry_run=not args.apply,
        tenant_id_override=args.tenant_id,
        user_id_filter=args.user_id,
        skip_secrets=not args.import_secrets,
        relax_fuzzy=not args.strict_fuzzy,
        min_confidence=args.min_confidence,
        rebuild_vectors=args.rebuild_vectors and args.apply,
        embed_provider=embed_provider,
        chroma=chroma,
        config=config,
    )
    summary = report.summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.report:
        Path(args.report).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nReport written to {args.report}", flush=True)

    if not args.apply:
        print(
            "\n[dry-run] No writes performed. Re-run with --apply to import into SQLite.",
            flush=True,
        )
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
