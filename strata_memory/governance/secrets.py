"""Secret detection and redaction for text that is about to be stored.

The rules are written for this project from the publicly documented token
formats of each provider. The rule set was scoped against the families covered
by gitleaks (MIT) and detect-secrets (Apache-2.0); no regex or code is copied
from either project.

Each rule names a ``kind``. Redaction replaces the secret with
``[redacted:<kind>]``. For key=value style rules only the value is replaced, so
the stored fact still says what the secret was for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MARK_PREFIX = "[redacted:"
_NOT_MARK = r"(?!\[redacted:)"


@dataclass(frozen=True)
class SecretRule:
    kind: str
    pattern: re.Pattern[str]
    group: int = 0  # 0 = whole match; otherwise only this group is the secret


def _rule(kind: str, regex: str, group: int = 0, flags: int = 0) -> SecretRule:
    return SecretRule(kind, re.compile(regex, flags), group)


# Order matters only for overlaps: earlier rules win when two spans start together.
SECRET_RULES: tuple[SecretRule, ...] = (
    _rule(
        "private_key",
        r"-----BEGIN ((?:[A-Z0-9]+ )*)PRIVATE KEY-----(?:[\s\S]*?-----END \1PRIVATE KEY-----)?",
    ),
    _rule("aws_access_key_id", r"\b(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}\b"),
    _rule("github_token", r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{22,})"),
    _rule("gitlab_token", r"\bglpat-[A-Za-z0-9_\-]{20,}"),
    _rule("slack_token", r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    _rule("slack_webhook", r"https://hooks\.slack\.com/services/[A-Za-z0-9/_\-]{20,}"),
    _rule("stripe_key", r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}"),
    _rule("google_api_key", r"\bAIza[0-9A-Za-z_\-]{35}"),
    _rule("npm_token", r"\bnpm_[A-Za-z0-9]{36}\b"),
    _rule("pypi_token", r"\bpypi-[A-Za-z0-9_\-]{50,}"),
    # OpenAI, Anthropic, SiliconFlow, DeepSeek and others share the sk- prefix.
    # The body must contain a digit so words like "sk-cluster" stay untouched.
    _rule("api_key", r"\bsk-(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{16,}"),
    _rule(
        "jwt",
        r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",
    ),
    _rule(
        "url_credentials",
        r"\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:(" + _NOT_MARK + r"[^\s/@]+)@",
        group=1,
        flags=re.IGNORECASE,
    ),
    _rule(
        "bearer_token",
        r"\bbearer\s+(" + _NOT_MARK + r"(?=[A-Za-z0-9\-._~+/]*\d)[A-Za-z0-9\-._~+/]{16,}=*)",
        group=1,
        flags=re.IGNORECASE,
    ),
    _rule(
        "password",
        r"(?:\b(?:password|passwd|pwd|passcode)\b|密码|口令)\s*(?:[:=：]|\bis\b|是|为)\s*[\"']?("
        + _NOT_MARK
        + r"[^\s\"',;，。；]{4,})",
        group=1,
        flags=re.IGNORECASE,
    ),
    _rule(
        "assigned_secret",
        r"\b(?:api[_-]?key|apikey|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|refresh[_-]?token"
        r"|client[_-]?secret|private[_-]?key)\s*[:=]\s*[\"']?(" + _NOT_MARK + r"[^\s\"',;]{6,})",
        group=1,
        flags=re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class SecretMatch:
    kind: str
    start: int
    end: int


def find_secrets(text: str) -> list[SecretMatch]:
    """Non-overlapping secret spans in ``text``, in order."""
    if not text:
        return []
    found: list[SecretMatch] = []
    for rule in SECRET_RULES:
        for m in rule.pattern.finditer(text):
            start, end = m.span(rule.group)
            if start < end:
                found.append(SecretMatch(rule.kind, start, end))
    found.sort(key=lambda s: (s.start, -(s.end - s.start)))
    merged: list[SecretMatch] = []
    for span in found:
        if merged and span.start < merged[-1].end:
            continue
        merged.append(span)
    return merged


def contains_secret(text: str) -> bool:
    return bool(find_secrets(text))


def redact_secrets(text: str) -> tuple[str, dict[str, int]]:
    """Replace each secret with ``[redacted:<kind>]``. Returns the text and counts per kind."""
    spans = find_secrets(text)
    if not spans:
        return text, {}
    counts: dict[str, int] = {}
    parts: list[str] = []
    pos = 0
    for span in spans:
        parts.append(text[pos : span.start])
        parts.append(f"{MARK_PREFIX}{span.kind}]")
        counts[span.kind] = counts.get(span.kind, 0) + 1
        pos = span.end
    parts.append(text[pos:])
    return "".join(parts), counts
