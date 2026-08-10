"""Quality Kernel + CBT middleware unit tests."""

from __future__ import annotations

import pytest

from strata_memory.governance.cbt_middleware import CBTMiddleware
from strata_memory.governance.quality_kernel import QualityKernel


def test_accepts_clean_preference():
    k = QualityKernel()
    v = k.validate(
        memory_type="user_preference",
        fact_claim="User prefers dark mode in VS Code with Monokai Pro theme.",
        confidence_score=0.9,
    )
    assert v.accepted
    assert v.content_hash
    assert v.layer == "L0"


def test_rejects_secret():
    k = QualityKernel()
    v = k.validate(
        memory_type="factual_truth",
        fact_claim="User API key is sk-abcdefghijklmnopqrstuvwxyz123456",
        confidence_score=0.99,
    )
    assert not v.accepted
    assert v.reject_code == "SECRET_DETECTED"


def test_rejects_fuzzy_time():
    k = QualityKernel()
    v = k.validate(
        memory_type="episodic_event",
        fact_claim="昨天用户决定迁移存储到 SQLite",
        confidence_score=0.8,
    )
    assert not v.accepted
    assert v.reject_code == "FUZZY_TIME"


def test_rejects_speculation_as_truth():
    k = QualityKernel()
    v = k.validate(
        memory_type="factual_truth",
        fact_claim="用户可能喜欢用 Rust 重写这个模块",
        confidence_score=0.7,
    )
    assert not v.accepted
    assert v.reject_code == "SPECULATION_AS_TRUTH"


def test_low_confidence_forces_scratch():
    k = QualityKernel(min_confidence=0.4)
    v = k.validate(
        memory_type="episodic_event",
        fact_claim="User mentioned trying a new editor layout once.",
        confidence_score=0.2,
    )
    assert v.accepted
    assert v.is_scratch
    assert v.layer == "scratch"


def test_invalid_type():
    k = QualityKernel()
    v = k.validate(
        memory_type="random_junk",
        fact_claim="Something durable enough to pass length checks here.",
        confidence_score=0.5,
    )
    assert not v.accepted
    assert v.reject_code == "INVALID_MEMORY_TYPE"


def test_cbt_detects_catastrophizing():
    m = CBTMiddleware(enabled=True)
    a = m.assess("这次全搞砸了，我永远不行")
    assert a.is_negative_schema
    assert a.block_l0_promotion
    assert a.force_cooling


def test_cbt_redacts_key():
    m = CBTMiddleware(enabled=True)
    r = m.redact("token sk-abcdefghijklmnopqrstuvwxyz99")
    assert r.redacted
    assert "sk-" not in r.text
