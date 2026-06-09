"""Wake-up pipeline — the read path (enhanced).

Flow:
  1. Load L0 profile (permanent decontextualized facts, procedures)
  2. Load L1 diary (recent N days, CBT-reframed narratives)
  3. Embed the user's query
  4. Semantic search ChromaDB for relevant L2 memories
  5. Apply defusion for negative schemas (CBT passive mode)
  6. Format results as flat Markdown string

V2 adds: intent classification, SQLite KG, RRF fusion, state-dependent boosting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..config import Config
from ..embedding import EmbeddingProvider
from ..storage.chroma import ChromaStore
from ..storage.markdown import estimate_tokens, read_l0_profile, read_l1_diary

MAX_DOC_CHARS = 1500  # Hard cap per L2 document to prevent context window blowout


async def wake_up(
    config: Config,
    embed_provider: EmbeddingProvider,
    chroma: ChromaStore,
    user_id: str,
    query: str,
    context_depth: str = "shallow",
    limit: int = 5,
) -> dict:
    """Wake up the memory system for a new session."""
    palace = Path(config.palace_path)
    wing = f"users/{user_id}"
    parts: list[str] = []

    # 0. L0 Profile (permanent context — decontextualized facts, procedures)
    l0 = read_l0_profile(palace, wing)
    if l0:
        l0_trimmed = l0[:config.l0_token_budget * 3]  # Rough char budget
        parts.append("## Core Profile (L0 — Permanent)\n")
        parts.append(l0_trimmed)
        parts.append("")

    # 1. L1 diary — recent N days
    diary_entries = read_l1_diary(palace, wing, config.l1_days, mode=config.mode)
    if diary_entries:
        parts.append("## Recent Context (L1 Diary)\n")
        for entry in diary_entries:
            parts.append(f"### {entry['date']}\n{entry['content']}\n")
        parts.append("")

    # 2. L2 semantic search (deep mode)
    l2_results = []
    negative_count = 0
    if context_depth == "deep":
        query_vec = await embed_provider.embed(query)
        l2_results = chroma.query(
            query_embedding=query_vec,
            top_k=limit * 2,  # Oversample to account for negative schema filtering
            where={"wing": wing},
        )
        if l2_results:
            parts.append("## Related Memories (L2 Semantic)\n")
            shown = 0
            for r in l2_results:
                if shown >= limit:
                    break
                dist = r.get("distance", 0.0)
                sim = max(0.0, 1.0 - dist)
                meta = r.get("metadata", {})

                # Cognitive safety: handle negative schemas
                is_neg = meta.get("is_negative_schema", False)
                raw_doc = r.get("document", "") or ""
                doc = raw_doc[:MAX_DOC_CHARS]
                if len(raw_doc) > MAX_DOC_CHARS:
                    doc += "\n\n*[truncated — use `search` for full text]*"
                if is_neg and config.cbt.enabled:
                    negative_count += 1
                    if config.cbt.mode == "passive":
                        # Defusion: inject with reframed framing
                        parts.append(
                            f"### Memory {shown + 1} (relevance: {sim:.2f}) [reframed]\n"
                            f"- Date: {meta.get('date', 'unknown')}\n"
                            f"- Category: {meta.get('category', 'unknown')}\n"
                            f"\n*Note: This memory contains self-critical content that may be distorted. "
                            f"Consider alternative interpretations.*\n"
                            f"\n{doc}\n"
                        )
                    elif config.cbt.mode == "off":
                        parts.append(
                            f"### Memory {shown + 1} (relevance: {sim:.2f})\n"
                            f"- Date: {meta.get('date', 'unknown')}\n"
                            f"\n{doc}\n"
                        )
                    # active mode: skip negative schemas, coach separately
                    if config.cbt.mode == "active":
                        continue
                else:
                    parts.append(
                        f"### Memory {shown + 1} (relevance: {sim:.2f})\n"
                        f"- Date: {meta.get('date', 'unknown')}\n"
                        f"- Category: {meta.get('category', 'unknown')}\n"
                        f"- Room: {meta.get('room', 'unknown')}\n"
                        f"\n{doc}\n"
                    )
                shown += 1
            parts.append("")

    context = "\n".join(parts).strip()
    token_estimate = estimate_tokens(context)

    return {
        "context": context if context else "(No relevant memories found.)",
        "token_estimate": token_estimate,
        "l0_loaded": bool(l0),
        "l1_entries": len(diary_entries),
        "l2_results": len(l2_results),
        "negative_filtered": negative_count,
        "cbt_mode": config.cbt.mode if config.cbt.enabled else "off",
        "context_depth": context_depth,
        "wing": wing,
    }
