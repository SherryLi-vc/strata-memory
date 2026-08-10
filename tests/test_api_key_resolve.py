"""API key resolution + redaction rejection."""

from __future__ import annotations

import os

import pytest

from strata_memory.config import api_key_status, is_usable_api_key, resolve_api_key


def test_rejects_redacted_ellipsis():
    assert not is_usable_api_key("sk-tqz...wxiu")
    assert api_key_status("sk-tqz...wxiu")["reason"] == "redacted_or_truncated_ellipsis"


def test_rejects_too_short():
    assert not is_usable_api_key("sk-short")
    assert "too_short" in api_key_status("sk-short")["reason"]


def test_accepts_full_key():
    full = "sk-tqzvhjtrtpyjzhhnlhwromdvxxptvkpuuwxealnetdnlwxiu"
    assert is_usable_api_key(full)
    assert api_key_status(full)["usable"] is True
    assert api_key_status(full)["length"] == len(full)


def test_resolve_prefers_env(monkeypatch):
    monkeypatch.setenv("STRATA_API_KEY", "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    k = resolve_api_key("")
    assert k.startswith("sk-aaaa")


def test_resolve_skips_redacted_env_for_fallback(monkeypatch):
    # Redacted env is unusable; fall through to siliconflow env
    monkeypatch.setenv("STRATA_API_KEY", "sk-tqz...wxiu")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    k = resolve_api_key("")
    assert k.startswith("sk-bbbb")


def test_resolve_returns_bad_if_all_bad(monkeypatch):
    monkeypatch.setenv("STRATA_API_KEY", "sk-tqz...wxiu")
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    k = resolve_api_key("")
    assert k == "sk-tqz...wxiu"
    assert not is_usable_api_key(k)
