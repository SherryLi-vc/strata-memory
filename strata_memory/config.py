"""Configuration management for Strata Memory 2.0.

Design laws:
  - SQLite Truth Store is Single Source of Truth
  - Vector index is rebuildable companion
  - Markdown is read-only projection
  - Dual-mode: personal (CBT) / company (tenant isolation + audit)

Secrets never persisted: use STRATA_API_KEY or STRATA_EMBEDDING_API_KEY.
Embedding provider, base URL, and model come from the environment when set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from . import __version__
from .embedder_stamp import expected_backend, log_effective_embedding

# Built-in defaults. Local (offline, no API key) is the default.
# SiliconFlow remains available by setting STRATA_EMBEDDING_PROVIDER=siliconflow.
# A saved config.json that already names a provider is left as-is.
DEFAULT_EMBEDDING_PROVIDER = "local"
_PROVIDER_DEFAULTS: dict[str, dict[str, object]] = {
    "siliconflow": {
        "model": "BAAI/bge-m3",
        "base_url": "https://api.siliconflow.cn/v1",
        "dimension": 384,
    },
    "openai": {
        "model": "text-embedding-3-small",
        "base_url": "https://api.openai.com/v1",
        "dimension": 1536,
    },
    "openai_compatible": {
        "model": "text-embedding-3-small",
        "base_url": "https://api.openai.com/v1",
        "dimension": 1536,
    },
    "local": {
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "base_url": "",
        "dimension": 384,
    },
}
_PROVIDER_ALIASES = {
    "openai-compatible": "openai_compatible",
    "local_onnx": "local",
    "self_hosted": "openai_compatible",
    "cloud": "openai_compatible",
}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


# Category-specific decay (legacy scoring compatibility)
CATEGORY_DECAY_RATES: dict[str, float] = {
    "event": 0.85,
    "lesson": 0.90,
    "preference": 0.95,
    "procedure": 0.98,
    "core_identity": 1.00,
    "fact": 0.93,
    "goal": 0.96,
    "relationship": 0.92,
    # 2.0 memory_type aliases
    "factual_truth": 0.93,
    "user_preference": 0.95,
    "procedure_rule": 0.98,
    "episodic_event": 0.85,
}


class EmbeddingConfig(BaseModel):
    """Blank model, base URL, and dimension mean "use that provider's defaults".

    A saved config that only sets ``provider`` must not inherit another
    provider's model name. ``dimension`` 0 means unset.
    """

    provider: str = ""
    model: str = ""
    api_key: str = Field(default="", exclude=True)
    base_url: str = ""
    dimension: int = 0
    mode: str = ""  # cloud | local; filled when settings are resolved


class CBTConfig(BaseModel):
    enabled: bool = True
    mode: str = "passive"  # passive | active | off
    cooling_hours: int = 48
    detect_distortions: bool = True


class AuditConfig(BaseModel):
    enabled: bool = False
    log_to_db: bool = True  # 2.0: always in SQLite audit_log
    log_to_markdown: bool = True
    retention_days: int = 365


class Config(BaseModel):
    palace_path: str = ""
    version: str = __version__

    mode: str = "personal"  # personal | company
    tenant_id: str = ""

    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    cbt: CBTConfig = Field(default_factory=CBTConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)

    # Memory parameters
    l1_days: int = 3
    l2_top_k: int = 10
    l0_token_budget: int = 2000
    l1_token_budget: int = 4000
    l2_token_budget: int = 6000
    promotion_threshold: float = 0.8
    demotion_threshold: float = 0.3
    deletion_threshold: float = 0.1
    promotion_min_usage: int = 5
    l3_demotion_days: int = 30
    min_confidence: float = 0.4  # below → scratch only
    # What commit_memory does with a detected secret: mask it ("redact") or refuse the write ("reject").
    # Env override: STRATA_ON_SECRET.
    on_secret: str = "redact"

    @field_validator("on_secret")
    @classmethod
    def _check_on_secret(cls, value: str) -> str:
        return normalize_on_secret(value)

    # Storage backend (2.0)
    storage_backend: str = "sqlite"  # sqlite SoT; chromadb is companion index
    require_session_scope: bool = False  # company can set True


def _default_palace_path() -> Path:
    env = os.environ.get("STRATA_PALACE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".strata" / "palace"


def _config_path(palace: Path) -> Path:
    return palace / "config.json"


# Minimum plausible SiliconFlow / OpenAI-style key length (sk- + payload).
_MIN_API_KEY_LEN = 20


def is_usable_api_key(key: Optional[str]) -> bool:
    """Reject empty, redacted, placeholder, or truncated keys.

    Common failure modes:
      - OpenClaw UI redaction: ``sk-tqz...wxiu`` (contains ``...``, ~13 chars)
      - Placeholder: ``***``, ``__OPENCLAW_*``
      - Env not exported → empty string
    """
    if not key or not isinstance(key, str):
        return False
    k = key.strip()
    if len(k) < _MIN_API_KEY_LEN:
        return False
    if "..." in k or "…" in k:
        return False
    if k in {"***", "REDACTED", "YOUR_API_KEY", "sk-xxx"}:
        return False
    if k.startswith("__OPENCLAW"):
        return False
    return True


def api_key_status(key: Optional[str]) -> dict:
    """Safe diagnostic for doctor/stats (never returns the full key)."""
    if not key:
        return {
            "configured": False,
            "usable": False,
            "length": 0,
            "reason": "empty",
            "prefix": "",
        }
    k = key.strip()
    usable = is_usable_api_key(k)
    reason = "ok"
    if not usable:
        if not k:
            reason = "empty"
        elif "..." in k or "…" in k:
            reason = "redacted_or_truncated_ellipsis"
        elif len(k) < _MIN_API_KEY_LEN:
            reason = f"too_short_len_{len(k)}"
        elif k.startswith("__OPENCLAW"):
            reason = "openclaw_placeholder"
        else:
            reason = "rejected_placeholder"
    return {
        "configured": bool(k),
        "usable": usable,
        "length": len(k),
        "reason": reason,
        "prefix": (k[:6] + "…") if len(k) >= 6 else k[:1] + "…",
    }


def normalize_embedding_provider(provider: str) -> str:
    """Map aliases to siliconflow, openai, openai_compatible, or local."""
    raw = (provider or DEFAULT_EMBEDDING_PROVIDER).strip().lower().replace(" ", "_")
    kind = _PROVIDER_ALIASES.get(raw, raw)
    if kind not in _PROVIDER_DEFAULTS:
        known = ", ".join(sorted(_PROVIDER_DEFAULTS))
        raise ValueError(f"Unknown embedding provider: {provider}. Use one of: {known}.")
    return kind


def truncate_embeddings(provider: str, model: str) -> bool:
    """Whether to keep only the first ``dimension`` values of a longer vector.

    Default: SiliconFlow BAAI/bge-m3 (Matryoshka). Override with
    STRATA_EMBEDDING_TRUNCATE=1 or 0.
    """
    flag = (os.environ.get("STRATA_EMBEDDING_TRUNCATE") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    if flag in {"0", "false", "no"}:
        return False
    kind = normalize_embedding_provider(provider)
    return kind == "siliconflow" and "bge-m3" in (model or "").lower()


def embedding_requires_api_key(provider: str, base_url: str = "") -> bool:
    """Cloud endpoints need a key. In-process local models and loopback servers do not."""
    kind = normalize_embedding_provider(provider)
    if kind == "local":
        return False
    flag = (os.environ.get("STRATA_EMBEDDING_ALLOW_EMPTY_KEY") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return False
    host = (urlparse(base_url or "").hostname or "").lower()
    if host in _LOOPBACK_HOSTS:
        return False
    return True


def resolve_api_key(explicit: str = "", provider: str = "") -> str:
    """Resolve embedding API key with env precedence.

    Order:
      1. explicit argument (tool param or already-resolved config value)
      2. STRATA_EMBEDDING_API_KEY
      3. STRATA_API_KEY
      4. provider key: SILICONFLOW_API_KEY for SiliconFlow, OPENAI_API_KEY otherwise
      5. the other of those two, so an existing key still works after a provider change

    Unusable values are skipped until every candidate is unusable. Then the
    first non-empty raw value is returned for diagnostics.
    """
    kind = ""
    if provider:
        try:
            kind = normalize_embedding_provider(provider)
        except ValueError:
            kind = ""
    if kind == "siliconflow":
        provider_keys = ("SILICONFLOW_API_KEY", "OPENAI_API_KEY")
    elif kind in {"openai", "openai_compatible"}:
        provider_keys = ("OPENAI_API_KEY", "SILICONFLOW_API_KEY")
    else:
        provider_keys = ("SILICONFLOW_API_KEY", "OPENAI_API_KEY")
    candidates = [
        explicit,
        os.environ.get("STRATA_EMBEDDING_API_KEY", ""),
        os.environ.get("STRATA_API_KEY", ""),
        *[os.environ.get(name, "") for name in provider_keys],
    ]
    for c in candidates:
        if is_usable_api_key(c):
            return c.strip()
    for c in candidates:
        if c and str(c).strip():
            return str(c).strip()
    return ""


def _env_str(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def resolve_embedding_settings(
    saved: Optional[EmbeddingConfig] = None,
    overrides: Optional[dict] = None,
) -> EmbeddingConfig:
    """Effective embedding settings.

    Precedence for each field: explicit override, then environment, then the
    saved config. Switching provider (override or env) without also setting
    model, base URL, or dimension uses that provider's defaults.
    """
    saved = saved or EmbeddingConfig()
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None and str(v).strip() != ""}
    saved_kind = normalize_embedding_provider(saved.provider or DEFAULT_EMBEDDING_PROVIDER)

    if "provider" in overrides:
        provider = normalize_embedding_provider(str(overrides["provider"]))
    elif _env_str("STRATA_EMBEDDING_PROVIDER"):
        provider = normalize_embedding_provider(_env_str("STRATA_EMBEDDING_PROVIDER"))
    else:
        provider = saved_kind
    spec = _PROVIDER_DEFAULTS[provider]
    switched = provider != saved_kind

    if "model" in overrides:
        model = str(overrides["model"]).strip()
    elif _env_str("STRATA_EMBEDDING_MODEL"):
        model = _env_str("STRATA_EMBEDDING_MODEL")
    elif switched or not (saved.model or "").strip():
        model = str(spec["model"])
    else:
        model = saved.model

    if "base_url" in overrides:
        base_url = str(overrides["base_url"]).strip().rstrip("/")
    elif _env_str("STRATA_EMBEDDING_BASE_URL"):
        base_url = _env_str("STRATA_EMBEDDING_BASE_URL").rstrip("/")
    elif provider == "local":
        base_url = ""
    elif switched or not (saved.base_url or "").strip():
        base_url = str(spec["base_url"]).rstrip("/")
    else:
        base_url = saved.base_url.rstrip("/")

    if "dimension" in overrides:
        dimension = int(overrides["dimension"])
    elif _env_str("STRATA_EMBEDDING_DIMENSION"):
        dimension = int(_env_str("STRATA_EMBEDDING_DIMENSION"))
    elif switched or not saved.dimension:
        dimension = int(spec["dimension"])
    else:
        dimension = int(saved.dimension)
    if dimension < 1:
        raise ValueError("STRATA_EMBEDDING_DIMENSION must be a positive integer.")

    explicit_key = str(overrides.get("api_key") or "")
    if explicit_key:
        key = resolve_api_key(explicit_key, provider=provider)
    else:
        key = resolve_api_key("", provider=provider) or (saved.api_key or "")
    return EmbeddingConfig(
        provider=provider,
        model=model,
        api_key=key,
        base_url=base_url,
        dimension=dimension,
        mode="local" if provider == "local" else "cloud",
    )


ON_SECRET_CHOICES = ("redact", "reject")


def normalize_on_secret(value: str) -> str:
    mode = (value or "").strip().lower()
    if mode not in ON_SECRET_CHOICES:
        raise ValueError(f"on_secret must be one of {', '.join(ON_SECRET_CHOICES)}; got {value!r}.")
    return mode


def load_config(palace_path: Optional[str] = None) -> Config:
    palace = Path(palace_path) if palace_path else _default_palace_path()
    cfg_file = _config_path(palace)
    if cfg_file.exists():
        raw = json.loads(cfg_file.read_text())
        # Migrate 0.x → 2.0 defaults without breaking old keys
        if "version" in raw and str(raw["version"]).startswith("0."):
            raw["version"] = "2.0.0"
        if "storage_backend" not in raw:
            raw["storage_backend"] = "sqlite"
        embedding_raw = raw.get("embedding")
        # Palaces saved before the embedding block existed were SiliconFlow.
        # Do not treat a missing block as the new local default.
        if not isinstance(embedding_raw, dict) or not embedding_raw:
            raw["embedding"] = {"provider": "siliconflow"}
        cfg = Config(**{k: v for k, v in raw.items() if k in Config.model_fields})
        cfg.palace_path = str(palace)
    else:
        cfg = Config(palace_path=str(palace))
    if _env_str("STRATA_ON_SECRET"):
        cfg.on_secret = normalize_on_secret(_env_str("STRATA_ON_SECRET"))
    # Env overrides provider, model, base URL, dimension, and key when set.
    cfg.embedding = resolve_embedding_settings(cfg.embedding)
    log_effective_embedding(
        cfg.embedding.provider,
        cfg.embedding.model,
        cfg.embedding.dimension,
        expected_backend(cfg.embedding.provider, cfg.embedding.model),
        cfg.embedding.base_url,
    )
    return cfg


def save_config(config: Config) -> None:
    palace = Path(config.palace_path)
    palace.mkdir(parents=True, exist_ok=True)
    cfg_file = _config_path(palace)
    data = config.model_dump(exclude={"palace_path"})
    if "embedding" in data and "api_key" in data["embedding"]:
        key = data["embedding"]["api_key"]
        data["embedding"]["api_key"] = ""
        if key:
            data["embedding"]["api_key_prefix"] = key[:8]
    cfg_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def is_initialized(palace_path: Optional[str] = None) -> bool:
    palace = Path(palace_path) if palace_path else _default_palace_path()
    return _config_path(palace).exists()


def palace_dirs(palace: Path) -> dict[str, Path]:
    """Standard palace layout (2.0)."""
    return {
        "wings": palace / "wings",  # legacy markdown (projection target)
        "audit_logs": palace / "audit_logs",
        "l0_profile": palace / "l0_profile",
        "l1_diary": palace / "l1_diary",
        "l2_vector": palace / "l2_vector",
        "l3_cold": palace / "l3_cold",
        "system": palace / "system",
        "metadata_db": palace / "metadata_db",
        "truth": palace / "truth",  # SQLite SoT lives here
        "projection": palace / "projection",  # read-only Markdown views
    }


def ensure_palace(palace: Path) -> None:
    for d in palace_dirs(palace).values():
        d.mkdir(parents=True, exist_ok=True)


def truth_db_path(palace: Path) -> Path:
    return palace / "truth" / "strata.db"


def decay_rate_for(category: str) -> float:
    return CATEGORY_DECAY_RATES.get(category, 0.93)
