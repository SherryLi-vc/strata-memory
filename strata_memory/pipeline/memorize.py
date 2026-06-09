"""Memorize pipeline — the write path (enhanced).

Flow:
  1. Fast emotional_salience screening (keyword-based)
  2. Write raw content to Drawer with enhanced YAML frontmatter
     (emotional_salience, context_tags, episode_index, is_negative_schema)
  3. Generate embedding via provider
  4. Upsert into ChromaDB vector store

V2 adds: LLM triple extraction, nightly scoring, CBT detection, audit logging.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from ..config import Config
from ..embedding import EmbeddingProvider
from ..storage.chroma import ChromaStore, _doc_id
from ..storage.markdown import drawer_path, write_drawer
from ..pipeline.scoring import estimate_emotional_salience


async def memorize(
    config: Config,
    embed_provider: EmbeddingProvider,
    chroma: ChromaStore,
    user_id: str,
    content: str,
    metadata: dict | None = None,
    context_tags: list[str] | None = None,
) -> dict:
    """Record a conversation/fact into memory.

    Enhanced with emotional_salience screening, context_tags, and
    category-specific metadata for psych-validated scoring.
    """
    palace = Path(config.palace_path)
    wing = f"users/{user_id}"
    room = metadata.get("room", "general") if metadata else "general"
    category = metadata.get("category", "event") if metadata else "event"
    today = date.today()

    fp = drawer_path(palace, wing, room, today, mode=config.mode)

    # Fast emotional salience screening (V2: LLM-powered)
    emotional_salience = estimate_emotional_salience(content)

    # CBT fast screening
    is_negative_schema = False
    if config.cbt.enabled and config.cbt.detect_distortions:
        from ..safety import detect_distortions
        distortions = detect_distortions(content)
        is_negative_schema = len(distortions) > 0

    # Build enhanced frontmatter
    fm = {
        "date": today.isoformat(),
        "wing": wing,
        "room": room,
        "category": category,
        "importance": metadata.get("importance", 0.5) if metadata else 0.5,
        "emotional_salience": emotional_salience,
        "context_tags": context_tags or [],
        "is_negative_schema": is_negative_schema,
        "tenant_id": config.tenant_id or "",
    }
    if metadata:
        fm.update({k: v for k, v in metadata.items() if k not in fm})

    # 1. Write raw drawer
    write_drawer(fp, content, fm)

    # 2. Generate embedding
    full_text = f"[{wing}/{room}] {content[:2000]}"
    vec = await embed_provider.embed(full_text)

    # 3. Upsert into ChromaDB with enhanced metadata
    doc_id = _doc_id(wing, room, today.isoformat())
    chroma.add(
        documents=[full_text],
        metadatas=[{
            "wing": wing,
            "room": room,
            "date": today.isoformat(),
            "category": category,
            "importance": fm["importance"],
            "emotional_salience": emotional_salience,
            "is_negative_schema": is_negative_schema,
            "context_tags": ",".join(context_tags or []),
            "tenant_id": config.tenant_id or "",
        }],
        ids=[doc_id],
        embeddings=[vec],
    )

    return {
        "status": "ok",
        "drawer": str(fp),
        "doc_id": doc_id,
        "wing": wing,
        "room": room,
        "date": today.isoformat(),
        "category": category,
        "emotional_salience": emotional_salience,
        "is_negative_schema": is_negative_schema,
        "context_tags": context_tags or [],
        "characters": len(content),
        "tokens_approx": len(content) // 3,
    }
