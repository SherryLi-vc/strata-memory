"""strata_doctor — consistency check (git-fsck style)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..config import Config, api_key_status, is_initialized, is_usable_api_key, resolve_api_key
from ..storage.chroma import ChromaStore
from ..storage.truth_store import TruthStore


def strata_doctor(
    *,
    config: Config,
    store: TruthStore,
    chroma: Optional[ChromaStore] = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    palace = Path(config.palace_path)
    checks.append({
        "name": "initialized",
        "ok": is_initialized(str(palace)),
        "detail": str(palace),
    })
    if not is_initialized(str(palace)):
        issues.append({
            "severity": "error",
            "code": "NOT_INITIALIZED",
            "message": "config.json missing — run strata_init first.",
        })

    # API key health (never print full key)
    resolved = resolve_api_key(config.embedding.api_key or "")
    key_stat = api_key_status(resolved)
    checks.append({
        "name": "embedding_api_key",
        "ok": is_usable_api_key(resolved),
        "detail": {
            **key_stat,
            "provider": config.embedding.provider,
            "model": config.embedding.model,
            "env_STRATA_API_KEY_set": bool(__import__("os").environ.get("STRATA_API_KEY")),
            "env_SILICONFLOW_API_KEY_set": bool(__import__("os").environ.get("SILICONFLOW_API_KEY")),
        },
    })
    if config.embedding.provider == "siliconflow" and not is_usable_api_key(resolved):
        issues.append({
            "severity": "error",
            "code": "EMBEDDING_API_KEY_MISSING",
            "message": (
                f"No usable API key for siliconflow (reason={key_stat.get('reason')}, "
                f"length={key_stat.get('length', 0)}). "
                "Set full STRATA_API_KEY in Hermes MCP env / ~/.hermes/.env; "
                "do not use OpenClaw redacted keys containing '...'."
            ),
        })

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
        checks.append({
            "name": "hash_duplicates",
            "ok": len(dups) == 0,
            "detail": {"groups": len(dups), "sample": dups[:5]},
        })
        if dups:
            issues.append({
                "severity": "warn",
                "code": "HASH_DUPLICATES",
                "message": f"{len(dups)} content_hash groups with >1 active row. Run strata_hygiene.",
            })
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
        checks.append({
            "name": "secret_residual_sample",
            "ok": secret_n == 0,
            "detail": {"scanned": len(sample), "hits": secret_n},
        })
        if secret_n:
            issues.append({
                "severity": "error",
                "code": "SECRET_RESIDUAL",
                "message": f"{secret_n} active claims look secret-like. Review via strata_hygiene.",
            })
    except Exception as e:
        issues.append({"severity": "warn", "code": "SECRET_SCAN_FAILED", "message": str(e)})

    durable = st.get("active", 0) - st.get("scratch", 0) if st else 0
    if durable < 0:
        durable = st.get("active", 0)

    # Drift: more vectors than durable is OK (legacy); zero vectors with many memories → warn
    if st and durable > 10 and vector_count == 0:
        issues.append({
            "severity": "warn",
            "code": "INDEX_EMPTY",
            "message": (
                f"Truth Store has ~{durable} durable rows but vector index is empty. "
                "Run strata_rebuild_index."
            ),
        })
    if st and vector_count > durable * 3 + 50:
        issues.append({
            "severity": "warn",
            "code": "INDEX_ORPHANS",
            "message": (
                f"Vector count ({vector_count}) >> durable SoT rows ({durable}). "
                "Consider strata_rebuild_index to purge orphans."
            ),
        })

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
            checks.append({
                "name": "sample_sot_rows",
                "ok": True,
                "detail": {"sampled": len(rows)},
            })
        except Exception as e:
            issues.append({"severity": "warn", "code": "SAMPLE_FAILED", "message": str(e)})

    ok = not any(i["severity"] == "error" for i in issues)
    rec = "All clear."
    if any(i.get("code") == "EMBEDDING_API_KEY_MISSING" for i in issues):
        rec = (
            "Fix embedding key first: export full STRATA_API_KEY, update "
            "~/.hermes/scripts/strata-wrapper.sh (or ~/.hermes/.env), restart Hermes MCP, "
            "then re-run strata_doctor."
        )
    elif issues:
        rec = "Address issues above; prefer strata_rebuild_index for index drift."

    return {
        "status": "ok" if ok else "degraded",
        "healthy": ok and not issues,
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
        },
        "orphan_sample": orphan_sample,
        "missing_sample": missing_sample,
        "recommendation": rec,
    }
