"""Configuration management for Strata Memory 2.0.

Design laws:
  - SQLite Truth Store is Single Source of Truth
  - Vector index is rebuildable companion
  - Markdown is read-only projection
  - Dual-mode: personal (CBT) / company (tenant isolation + audit)

Secrets never persisted: use STRATA_API_KEY env var.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


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
    provider: str = "siliconflow"
    model: str = "BAAI/bge-m3"
    api_key: str = Field(default="", exclude=True)
    base_url: str = "https://api.siliconflow.cn/v1"
    dimension: int = 384
    mode: str = "cloud"  # cloud | local_onnx | self_hosted


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
    version: str = "2.1.0"

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


def resolve_api_key(explicit: str = "") -> str:
    """Resolve embedding API key with env precedence.

    Order:
      1. explicit argument (e.g. tool param)
      2. STRATA_API_KEY
      3. SILICONFLOW_API_KEY
      4. OPENAI_API_KEY (last resort for compatible gateways)

    Unusable / redacted values are ignored so a truncated openclaw key
    does not shadow a valid env var later in the chain... actually we
    only have one env per name; truncation usually *is* the env value.
    """
    candidates = [
        explicit,
        os.environ.get("STRATA_API_KEY", ""),
        os.environ.get("SILICONFLOW_API_KEY", ""),
        os.environ.get("OPENAI_API_KEY", ""),
    ]
    for c in candidates:
        if is_usable_api_key(c):
            return c.strip()
    # Return first non-empty raw for diagnostics (caller checks usable)
    for c in candidates:
        if c and str(c).strip():
            return str(c).strip()
    return ""


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
        cfg = Config(**{k: v for k, v in raw.items() if k in Config.model_fields})
        cfg.palace_path = str(palace)
    else:
        cfg = Config(palace_path=str(palace))
    # Env / resolved key always wins over empty persisted config
    resolved = resolve_api_key(cfg.embedding.api_key or "")
    if resolved:
        cfg.embedding.api_key = resolved
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
