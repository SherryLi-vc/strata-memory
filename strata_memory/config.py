"""Configuration management for Strata Memory.

Dual-mode architecture:
  - personal: CBT safety, 48h cooling, emotional tracking
  - company:  Multi-tenancy, AuditLog, PostgreSQL, private embedding

Configuration-driven — no hardcoded defaults that can't be overridden.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


# ── Category-specific decay rates (psych-validated) ────────────────────
# From Ebbinghaus forgetting curve research: different memory types decay
# at fundamentally different rates. Episodic memory fades fastest;
# procedural and core identity barely decay at all.
CATEGORY_DECAY_RATES: dict[str, float] = {
    "event":          0.85,   # Episodic events fade fastest
    "lesson":         0.90,   # Learned lessons decay moderately
    "preference":     0.95,   # Tastes/preferences decay slowly
    "procedure":      0.98,   # Procedural knowledge very stable
    "core_identity":  1.00,   # Anchor exemption — no decay
    "fact":           0.93,   # General facts
    "goal":           0.96,   # Active goals persist
    "relationship":   0.92,   # Social relationship info
}


class EmbeddingConfig(BaseModel):
    provider: str = "siliconflow"
    model: str = "BAAI/bge-m3"
    api_key: str = Field(default="", exclude=True)  # Excluded from serialization; prefer STRATA_API_KEY env var
    base_url: str = "https://api.siliconflow.cn/v1"
    dimension: int = 384  # MRL truncated from 1024
    mode: str = "cloud"   # "cloud" | "local_onnx" | "self_hosted"


class CBTConfig(BaseModel):
    enabled: bool = True          # Company mode defaults to False
    mode: str = "passive"         # passive | active | off
    cooling_hours: int = 48       # 48h cooling-off before consolidation
    detect_distortions: bool = True  # Scan for catastrophizing, black-and-white, etc.


class AuditConfig(BaseModel):
    enabled: bool = False         # Company mode defaults to True
    log_to_db: bool = False       # PostgreSQL audit log
    log_to_markdown: bool = True  # Markdown audit trail (always on in personal)
    retention_days: int = 365


class Config(BaseModel):
    # ── Identity ──
    palace_path: str = ""
    version: str = "0.2.0"

    # ── Mode ──
    mode: str = "personal"        # "personal" | "company"
    tenant_id: str = ""           # Multi-tenant identifier (company mode)

    # ── Subsystems ──
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    cbt: CBTConfig = Field(default_factory=CBTConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)

    # ── Memory parameters ──
    l1_days: int = 3
    l2_top_k: int = 10
    l0_token_budget: int = 2000       # Hard cap for L0 context
    l1_token_budget: int = 4000       # Hard cap for L1 diary
    l2_token_budget: int = 6000       # Dynamic cap for L2 results
    promotion_threshold: float = 0.8
    demotion_threshold: float = 0.3
    deletion_threshold: float = 0.1
    promotion_min_usage: int = 5      # Min usage_count for L0 promotion
    l3_demotion_days: int = 30        # Days unaccessed before L3 demotion

    # ── Storage backend ──
    storage_backend: str = "chromadb"  # "chromadb" | "postgres" (V2)


def _default_palace_path() -> Path:
    env = os.environ.get("STRATA_PALACE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".strata" / "palace"


def _config_path(palace: Path) -> Path:
    return palace / "config.json"


def load_config(palace_path: Optional[str] = None) -> Config:
    palace = Path(palace_path) if palace_path else _default_palace_path()
    cfg_file = _config_path(palace)
    if cfg_file.exists():
        raw = json.loads(cfg_file.read_text())
        cfg = Config(**raw)
        cfg.palace_path = str(palace)
    else:
        cfg = Config(palace_path=str(palace))
    # Env var takes precedence over config file (avoids plaintext storage)
    env_key = os.environ.get("STRATA_API_KEY", "")
    if env_key:
        cfg.embedding.api_key = env_key
    return cfg


def save_config(config: Config) -> None:
    palace = Path(config.palace_path)
    palace.mkdir(parents=True, exist_ok=True)
    cfg_file = _config_path(palace)
    data = config.model_dump(exclude={"palace_path"})
    # Strip api_key from persisted config — env var STRATA_API_KEY is the secure path
    if "embedding" in data and "api_key" in data["embedding"]:
        key = data["embedding"]["api_key"]
        data["embedding"]["api_key"] = ""  # Never persist the full key
        # Store prefix for identification only
        if key:
            data["embedding"]["api_key_prefix"] = key[:8]
    cfg_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def is_initialized(palace_path: Optional[str] = None) -> bool:
    palace = Path(palace_path) if palace_path else _default_palace_path()
    return _config_path(palace).exists()


def palace_dirs(palace: Path) -> dict[str, Path]:
    """Return standard palace subdirectory paths (enterprise structure)."""
    return {
        "wings":       palace / "wings",
        "audit_logs":  palace / "audit_logs",
        "l0_profile":  palace / "l0_profile",
        "l1_diary":    palace / "l1_diary",
        "l2_vector":   palace / "l2_vector",
        "l3_cold":     palace / "l3_cold",
        "system":      palace / "system",
        "metadata_db": palace / "metadata_db",
    }


def ensure_palace(palace: Path) -> None:
    for d in palace_dirs(palace).values():
        d.mkdir(parents=True, exist_ok=True)


def decay_rate_for(category: str) -> float:
    """Return the category-specific decay rate."""
    return CATEGORY_DECAY_RATES.get(category, 0.93)
