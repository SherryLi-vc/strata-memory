"""Write-time secret handling: on_secret=redact (default) or reject.

Fake tokens are assembled at runtime so no token-shaped literal sits in the repo.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from strata_memory.config import Config, ensure_palace, load_config, save_config, truth_db_path
from strata_memory.governance import ToolError
from strata_memory.governance.secrets import find_secrets, redact_secrets
from strata_memory.pipeline.commit import commit_memory
from strata_memory.storage.sqlite_vectors import SqliteVectorStore
from strata_memory.storage.truth_store import TruthStore

AWS = "AKIA" + "QX7RT2ML9PZ4KD3W"
GH = "ghp" + "_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
SK = "sk-" + "proj-" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2"
SLACK = "xoxb" + "-" + "123456789012-abcdefABCDEF"
STRIPE = "sk" + "_live_" + "4eC39HqLyjWDarjtT1zdp7dc"
GOOGLE = "AIza" + "SyD3x9Kq0Lm2Np4Qr6St8Uv0Wx2Yz4Ab6Cd8"
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA7\n-----END " + "RSA PRIVATE KEY-----"


@pytest.mark.parametrize(
    ("text", "secret", "kind"),
    [
        (f"Deploy uses AWS key {AWS} for uploads.", AWS, "aws_access_key_id"),
        (f"The CI bot token is {GH} on the org.", GH, "github_token"),
        (f"OpenAI project key {SK} lives in the vault.", SK, "api_key"),
        (f"Slack bot uses {SLACK} for alerts.", SLACK, "slack_token"),
        (f"Stripe production key {STRIPE} is rotated monthly.", STRIPE, "stripe_key"),
        (f"Maps widget key {GOOGLE} is restricted.", GOOGLE, "google_api_key"),
        (f"Session cookie {JWT} expires hourly.", JWT, "jwt"),
        (f"Server key:\n{PEM}\nkept offline.", PEM, "private_key"),
        ("Staging db password: hunter2-staging-77 for the admin user.", "hunter2-staging-77", "password"),
        ("测试库密码是 Abc123xyz!! 不要外传", "Abc123xyz!!", "password"),
        ("config api_key = 'q8w7e6r5t4y3u2i1' for staging", "q8w7e6r5t4y3u2i1", "assigned_secret"),
        (
            "Clone from https://deploy:s3cr3tPassw0rd@git.example.com/repo.git daily",
            "s3cr3tPassw0rd",
            "url_credentials",
        ),
        ("Call the API with Authorization: Bearer abcDEF1234567890xyzXYZ", "abcDEF1234567890xyzXYZ", "bearer_token"),
    ],
)
def test_redact_replaces_secret_with_kind_marker(text, secret, kind):
    out, counts = redact_secrets(text)
    assert secret not in out
    assert f"[redacted:{kind}]" in out
    assert counts == {kind: 1}


def test_redaction_keeps_the_surrounding_fact_and_is_idempotent():
    out, _ = redact_secrets("config api_key = 'q8w7e6r5t4y3u2i1' for staging")
    assert out.startswith("config api_key = ")
    assert out.endswith(" for staging")
    again, counts = redact_secrets(out)
    assert again == out and counts == {}
    assert find_secrets(out) == []


@pytest.mark.parametrize(
    "text",
    [
        "User prefers bearer tokens over cookies for the mobile app.",
        "The password policy requires 12 characters.",
        "Commit 3f9a1c2 fixed the token refresh bug.",
        "Deploy to sk-cluster on Fridays.",
    ],
)
def test_plain_facts_are_not_flagged(text):
    assert find_secrets(text) == []


def _env(tmp_path: Path, **cfg_kwargs):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(palace_path=str(palace), mode="personal", **cfg_kwargs)
    save_config(cfg)
    return cfg, TruthStore(truth_db_path(palace)), SqliteVectorStore(palace / "l2_vector")


class _RecordingEmbed:
    provider_name = "local"
    model_name = "hash-test"
    backend = "hash"
    dimension = 8

    def __init__(self):
        self.texts: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.texts.append(text)
        return [float((len(text) + i) % 7) + 1.0 for i in range(8)]


def _commit(cfg, store, chroma, embed, claim):
    return asyncio.run(
        commit_memory(
            config=cfg,
            store=store,
            embed_provider=embed,
            chroma=chroma,
            user_id="user_a",
            memory_type="factual_truth",
            fact_claim=claim,
            confidence_score=0.9,
        )
    )


def _palace_bytes(palace: Path) -> bytes:
    blob = b""
    for path in palace.rglob("*"):
        if path.is_file():
            blob += path.read_bytes()
    return blob


def test_default_is_redact_and_the_secret_never_reaches_disk_or_index(tmp_path: Path):
    cfg, store, chroma = _env(tmp_path)
    assert cfg.on_secret == "redact"
    embed = _RecordingEmbed()

    out = _commit(cfg, store, chroma, embed, f"Deploy uses AWS key {AWS} for the uploads bucket.")

    assert out["status"] == "ok"
    assert out["secrets_redacted"] == {"aws_access_key_id": 1}
    row = store.get_by_id(out["memory_id"])
    assert AWS not in json.dumps(row, default=str)
    assert "[redacted:aws_access_key_id]" in row["fact_claim"]
    assert all(AWS not in t for t in embed.texts) and embed.texts
    del store, chroma
    blob = _palace_bytes(Path(cfg.palace_path))  # SQLite db + WAL + chroma files + audit
    assert AWS.encode() not in blob


def test_reject_mode_refuses_and_stores_nothing(tmp_path: Path):
    cfg, store, chroma = _env(tmp_path, on_secret="reject")
    embed = _RecordingEmbed()
    with pytest.raises(ToolError) as exc:
        _commit(cfg, store, chroma, embed, f"Deploy uses AWS key {AWS} for the uploads bucket.")
    assert exc.value.code == "SECRET_DETECTED"
    assert store.iter_for_index(tenant_id="") == []
    assert embed.texts == []
    assert AWS not in str(exc.value.to_dict() if hasattr(exc.value, "to_dict") else exc.value)


def test_on_secret_env_override_and_validation(tmp_path: Path, monkeypatch):
    cfg, _store, _chroma = _env(tmp_path)
    monkeypatch.setenv("STRATA_ON_SECRET", "reject")
    assert load_config(cfg.palace_path).on_secret == "reject"
    monkeypatch.setenv("STRATA_ON_SECRET", "ignore")
    with pytest.raises(ValueError):
        load_config(cfg.palace_path)
    monkeypatch.delenv("STRATA_ON_SECRET")
    with pytest.raises(ValueError):
        Config(palace_path=cfg.palace_path, on_secret="ignore")


def test_hygiene_preview_does_not_echo_a_secret(tmp_path: Path):
    from strata_memory.ops.hygiene import strata_hygiene

    cfg, store, _chroma = _env(tmp_path)
    store.insert_memory(
        tenant_id="",
        user_id="user_a",
        session_id="",
        memory_type="factual_truth",
        fact_claim=f"Legacy row with key {AWS} imported before redaction.",
        content_hash="legacy-1",
        confidence=0.9,
        importance=0.5,
    )
    report = strata_hygiene(config=cfg, store=store, user_id="user_a", dry_run=True)
    assert report["secret_hit_count"] == 1
    assert AWS not in json.dumps(report, default=str)
