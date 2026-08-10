"""Typed default Freshness / TTL / layer / validator — deterministic injection.

LLM may omit optional fields; Python always fills these at the write boundary.
"""

from __future__ import annotations

from typing import Any, Optional

# Canonical types (3.0 adds decision_record)
MEMORY_TYPES = frozenset({
    "factual_truth",
    "user_preference",
    "procedure_rule",
    "episodic_event",
    "decision_record",
})

# ttl_days: None = permanent until superseded
TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "factual_truth": {
        "status": "active",
        "ttl_days": None,
        "ttl_seconds": None,
        "layer": "L0",
        "importance": 0.70,
        "validator_kind": "quality_kernel",
        "authority": "agent",
        "sensitivity": "normal",
    },
    "user_preference": {
        "status": "active",
        "ttl_days": None,
        "ttl_seconds": None,
        "layer": "L0",
        "importance": 0.75,
        "validator_kind": "quality_kernel",
        "authority": "user",
        "sensitivity": "normal",
    },
    "procedure_rule": {
        "status": "active",
        "ttl_days": None,
        "ttl_seconds": None,
        "layer": "L0",
        "importance": 0.80,
        "validator_kind": "quality_kernel",
        "authority": "agent",
        "sensitivity": "normal",
    },
    "episodic_event": {
        "status": "active",
        "ttl_days": 90,
        "ttl_seconds": 90 * 24 * 3600,
        "layer": "L2",
        "importance": 0.45,
        "validator_kind": "quality_kernel",
        "authority": "agent",
        "sensitivity": "normal",
    },
    "decision_record": {
        "status": "active",
        "ttl_days": 365,
        "ttl_seconds": 365 * 24 * 3600,
        "layer": "L1",
        "importance": 0.85,
        "validator_kind": "quality_kernel",
        "authority": "user",
        "sensitivity": "normal",
    },
}


def defaults_for(memory_type: str) -> dict[str, Any]:
    return dict(TYPE_DEFAULTS.get(memory_type, TYPE_DEFAULTS["episodic_event"]))


def ttl_seconds_for(memory_type: str) -> Optional[int]:
    d = defaults_for(memory_type)
    return d.get("ttl_seconds")
