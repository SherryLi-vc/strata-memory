"""Remember which embedder built the vector index.

Vectors from different providers or models are not comparable, even when the
dimension matches. The stamp sits next to the Chroma directory. A mismatch
refuses vector reads and writes until ``strata_rebuild_index(confirm=true)``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("strata_memory.embedding")

STAMP_NAME = "embedder.json"


def expected_backend(provider: str, model: str) -> str:
    """Backend we will use, without downloading weights."""
    if provider != "local":
        return "http"
    choice = (os.environ.get("STRATA_LOCAL_EMBED_BACKEND") or "").strip().lower()
    if choice in {"hash", "hashing"} or (model or "").strip().lower() in {"hash", "hashing"}:
        return "hashing"
    try:
        import fastembed  # noqa: F401

        return "fastembed"
    except ImportError:
        pass
    try:
        import sentence_transformers  # noqa: F401

        return "sentence_transformers"
    except ImportError:
        pass
    return "hashing"


def identity_dict(
    *,
    provider: str,
    model: str,
    dimension: int,
    backend: str,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "dimension": int(dimension),
        "backend": backend,
    }


def current_identity(provider: str, model: str, dimension: int, backend: str = "") -> dict[str, Any]:
    return identity_dict(
        provider=provider,
        model=model,
        dimension=dimension,
        backend=backend or expected_backend(provider, model),
    )


def identity_for(embedding: Any, provider_obj: Any) -> dict[str, Any]:
    """Identity from resolved settings plus the loaded provider backend."""
    provider = embedding.provider
    model = embedding.model
    backend = getattr(provider_obj, "backend", "") or ""
    if provider == "local" and backend in {"", "http"}:
        backend = expected_backend(provider, model)
    elif not backend:
        backend = expected_backend(provider, model)
    return current_identity(provider, model, embedding.dimension, backend)


def log_effective_embedding(provider: str, model: str, dimension: int, backend: str, base_url: str = "") -> None:
    logger.info(
        "effective embedding provider=%s model=%s dimension=%s backend=%s base_url=%s",
        provider,
        model,
        dimension,
        backend,
        base_url or "-",
    )


def stamp_path(persist_dir: Path) -> Path:
    return Path(persist_dir) / STAMP_NAME


def read_stamp(persist_dir: Path) -> Optional[dict[str, Any]]:
    path = stamp_path(persist_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_stamp(persist_dir: Path, ident: dict[str, Any]) -> None:
    path = stamp_path(persist_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(ident, indent=2, sort_keys=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(path)


def incompatibility(persist_dir: Path, ident: dict[str, Any], *, vector_count: int) -> Optional[str]:
    """Return a machine code when the index must not be mixed with ``ident``.

    An empty index with no stamp is compatible. A non-empty index with no
    stamp is not: those vectors have an unknown embedder.
    """
    if vector_count <= 0:
        return None
    stored = read_stamp(persist_dir)
    if stored is None:
        return "EMBEDDER_UNSTAMPED"
    for key in ("provider", "model", "dimension", "backend"):
        if str(stored.get(key)) != str(ident.get(key)):
            return "EMBEDDER_MISMATCH"
    return None


def mismatch_message(code: str, ident: dict[str, Any]) -> str:
    if code == "EMBEDDER_UNSTAMPED":
        return (
            "The vector index has no embedder stamp, so its vectors cannot be "
            f"mixed with {ident['provider']}/{ident['model']} ({ident['backend']})."
        )
    return (
        "The vector index was built with a different embedder than "
        f"{ident['provider']}/{ident['model']} backend={ident['backend']} "
        f"dimension={ident['dimension']}."
    )


def mismatch_fix() -> str:
    return (
        "Run strata_rebuild_index with confirm=true after the embedding provider "
        "and model you want are selected. Do not query or add vectors until the stamp matches."
    )
