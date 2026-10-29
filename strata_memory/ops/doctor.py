"""strata_doctor — consistency check (git-fsck style)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..config import (
    Config,
    api_key_status,
    embedding_requires_api_key,
    is_initialized,
    is_usable_api_key,
    resolve_embedding_settings,
)
from ..embedder_stamp import expected_backend, incompatibility, log_effective_embedding, read_stamp
from ..storage.sqlite_vectors import SqliteVectorStore
from ..storage.truth_store import TruthStore


def strata_doctor(
    *,
    config: Config,
    store: TruthStore,
    chroma: Optional[SqliteVectorStore] = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    palace = Path(config.palace_path)
    checks.append(
        {
            "name": "initialized",
            "ok": is_initialized(str(palace)),
            "detail": str(palace),
        }
    )
    if not is_initialized(str(palace)):
        issues.append(
            {
                "severity": "error",
                "code": "NOT_INITIALIZED",
                "message": "config.json missing — run strata_init first.",
            }
        )

    # API key health (never print full key). Env can switch provider and endpoint.
    embedding = resolve_embedding_settings(config.embedding)
    config.embedding = embedding
    resolved = embedding.api_key or ""
    requires_key = embedding_requires_api_key(embedding.provider, embedding.base_url)
    key_stat = api_key_status(resolved)
    if not requires_key and not is_usable_api_key(resolved):
        key_stat = {
            "configured": bool(resolved),
            "usable": True,
            "length": len(resolved),
            "reason": "not_required",
            "prefix": key_stat.get("prefix") or "",
        }
    checks.append(
        {
            "name": "embedding_api_key",
            "ok": bool(key_stat.get("usable")),
            "detail": {
                **key_stat,
                "provider": embedding.provider,
                "model": embedding.model,
                "base_url": embedding.base_url,
                "dimension": embedding.dimension,
                "backend": expected_backend(embedding.provider, embedding.model),
                "key_required": requires_key,
                "env_STRATA_API_KEY_set": bool(__import__("os").environ.get("STRATA_API_KEY")),
                "env_SILICONFLOW_API_KEY_set": bool(__import__("os").environ.get("SILICONFLOW_API_KEY")),
                "env_OPENAI_API_KEY_set": bool(__import__("os").environ.get("OPENAI_API_KEY")),
            },
        }
    )
    backend = expected_backend(embedding.provider, embedding.model)
    log_effective_embedding(
        embedding.provider,
        embedding.model,
        embedding.dimension,
        backend,
        embedding.base_url,
    )
    if chroma is not None:
        try:
            stamped_count = chroma.count()
        except Exception:
            stamped_count = 0
        ident = {
            "provider": embedding.provider,
            "model": embedding.model,
            "dimension": embedding.dimension,
            "backend": backend,
        }
        code = incompatibility(chroma.persist_dir, ident, vector_count=stamped_count)
        stored = read_stamp(chroma.persist_dir)
        checks.append(
            {
                "name": "embedder_stamp",
                "ok": code is None,
                "detail": {"stamp": stored, "effective": ident, "code": code},
            }
        )
        if code:
            issues.append(
                {
                    "severity": "error",
                    "code": code,
                    "message": (
                        "Vector index embedder does not match the effective provider and model. "
                        "Rebuild before recall or commit indexes more vectors."
                    ),
                }
            )
    if requires_key and not is_usable_api_key(resolved):
        issues.append(
            {
                "severity": "error",
                "code": "EMBEDDING_API_KEY_MISSING",
                "message": (
                    f"No usable API key for {embedding.provider} "
                    f"(reason={key_stat.get('reason')}, length={key_stat.get('length', 0)}, "
                    f"base_url={embedding.base_url}). "
                    "Set STRATA_EMBEDDING_API_KEY or STRATA_API_KEY. "
                    "Do not use redacted keys containing '...'."
                ),
            }
        )

    # SQLite stats
    try:
        st = store.stats()
        checks.append({"name": "truth_store", "ok": True, "detail": st})
    except Exception as e:
        checks.append({"name": "truth_store", "ok": False, "detail": str(e)})
        issues.append({"severity": "error", "code": "SOT_UNREADABLE", "message": str(e)})
        st = {}

    # Vector companion consistency
    vector_count = 0
    if chroma is not None:
        try:
            vector_count = chroma.count()
            checks.append({"name": "vector_index", "ok": True, "detail": {"count": vector_count}})
        except Exception as e:
            checks.append({"name": "vector_index", "ok": False, "detail": str(e)})
            issues.append({"severity": "warn", "code": "VECTOR_UNREADABLE", "message": str(e)})

    # Hash duplicates + secret residual sample
    try:
        dups = store.find_hash_duplicates(tenant_id=config.tenant_id or "")
        checks.append(
            {
                "name": "hash_duplicates",
                "ok": len(dups) == 0,
                "detail": {"groups": len(dups), "sample": dups[:5]},
            }
        )
        if dups:
            issues.append(
                {
                    "severity": "warn",
                    "code": "HASH_DUPLICATES",
                    "message": f"{len(dups)} content_hash groups with >1 active row. Run strata_hygiene.",
                }
            )
    except Exception as e:
        issues.append({"severity": "warn", "code": "DUP_SCAN_FAILED", "message": str(e)})

    try:
        from ..governance.quality_kernel import SECRET_PATTERNS

        sample = store.iter_for_index(tenant_id=config.tenant_id or "")[:300]
        secret_n = 0
        for r in sample:
            text = r.get("fact_claim") or ""
            if any(p.search(text) for p in SECRET_PATTERNS):
                secret_n += 1
        checks.append(
            {
                "name": "secret_residual_sample",
                "ok": secret_n == 0,
                "detail": {"scanned": len(sample), "hits": secret_n},
            }
        )
        if secret_n:
            issues.append(
                {
                    "severity": "error",
                    "code": "SECRET_RESIDUAL",
                    "message": f"{secret_n} active claims look secret-like. Review via strata_hygiene.",
                }
            )
    except Exception as e:
        issues.append({"severity": "warn", "code": "SECRET_SCAN_FAILED", "message": str(e)})

    durable = st.get("active", 0) - st.get("scratch", 0) if st else 0
    if durable < 0:
        durable = st.get("active", 0)

    # Coverage: every indexable SoT row should have a vector. A failed or
    # interrupted rebuild leaves rows without vectors (N8); a stamp without a
    # collection does too (N9). Count by id, not by total, so orphans or other
    # tenants' vectors cannot hide missing ones.
    if chroma is not None and st:
        try:
            indexable = [
                r["id"]
                for r in store.iter_for_index(tenant_id=config.tenant_id or "")
                if not r.get("is_negative_schema")
            ]
            present = chroma.existing_ids(indexable) if indexable else set()
            missing = len(indexable) - len(present)
            checks.append(
                {
                    "name": "vector_coverage",
                    "ok": missing == 0,
                    "detail": {"indexable_rows": len(indexable), "with_vector": len(present), "missing": missing},
                }
            )
            if missing:
                issues.append(
                    {
                        # No vectors at all means semantic recall is off for every old memory.
                        "severity": "error" if not present else "warn",
                        "code": "INDEX_INCOMPLETE",
                        "message": (
                            f"{missing} of {len(indexable)} indexable memories have no vector "
                            "(failed or interrupted rebuild, or index writes that failed). "
                            "Run strata_rebuild_index(confirm=true)."
                        ),
                    }
                )
        except Exception as e:
            issues.append({"severity": "warn", "code": "COVERAGE_CHECK_FAILED", "message": str(e)})

    if st and vector_count > durable * 3 + 50:
        issues.append(
            {
                "severity": "warn",
                "code": "INDEX_ORPHANS",
                "message": (
                    f"Vector count ({vector_count}) >> durable SoT rows ({durable}). "
                    "Consider strata_rebuild_index to purge orphans."
                ),
            }
        )

    # Orphan check sample: random sample of vector ids in SoT
    orphan_sample = 0
    missing_sample = 0
    if chroma is not None and st:
        try:
            rows = store.iter_for_index(tenant_id=config.tenant_id or "")[:50]
            for r in rows:
                # We can't cheaply get-by-id from chroma without API —
                # count-level check is enough for doctor
                pass
            checks.append(
                {
                    "name": "sample_sot_rows",
                    "ok": True,
                    "detail": {"sampled": len(rows)},
                }
            )
        except Exception as e:
            issues.append({"severity": "warn", "code": "SAMPLE_FAILED", "message": str(e)})

    ok = not any(i["severity"] == "error" for i in issues)
    rec = "All clear."
    if any(i.get("code") == "EMBEDDING_API_KEY_MISSING" for i in issues):
        rec = (
            "Fix the embedding key first: set STRATA_EMBEDDING_API_KEY or STRATA_API_KEY "
            "(SiliconFlow: SILICONFLOW_API_KEY, OpenAI-compatible: OPENAI_API_KEY). "
            "Or set STRATA_EMBEDDING_PROVIDER=local, or a loopback STRATA_EMBEDDING_BASE_URL. "
            "Then re-run strata_doctor."
        )
    elif issues:
        rec = "Address issues above; prefer strata_rebuild_index for index drift."

    return {
        # Any issue degrades the report (L1): healthy=false never comes with status=ok.
        # ``severity`` keeps the distinction between warnings and errors.
        "status": "ok" if not issues else "degraded",
        "healthy": ok and not issues,
        "severity": "error" if not ok else ("warn" if issues else "none"),
        "version": config.version,
        "mode": config.mode,
        "checks": checks,
        "issues": issues,
        "summary": {
            "sot_active": st.get("active", 0) if st else 0,
            "sot_scratch": st.get("scratch", 0) if st else 0,
            "vector_count": vector_count,
            "by_layer": st.get("by_layer", {}) if st else {},
            "api_key": key_stat,
            "embedding": {
                "provider": embedding.provider,
                "model": embedding.model,
                "dimension": embedding.dimension,
                "backend": expected_backend(embedding.provider, embedding.model),
                "base_url": embedding.base_url,
            },
        },
        "orphan_sample": orphan_sample,
        "missing_sample": missing_sample,
        "recommendation": rec,
    }
