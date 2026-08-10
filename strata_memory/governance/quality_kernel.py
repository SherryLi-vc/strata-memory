"""Quality Kernel — deterministic write-time interception.

LLM never writes raw rows. Every commit_memory call is intercepted here:
  - content hash + dedup
  - confidence / type validation
  - fuzzy-time rejection
  - secret / credential rejection
  - TTL + layer assignment
  - summary compression

Philosophy: deterministic Python owns all metadata; LLM only proposes claims.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .errors import ToolError
from .type_defaults import MEMORY_TYPES, defaults_for

VALID_MEMORY_TYPES = MEMORY_TYPES

# Relative / fuzzy temporal language that must be grounded before commit.
FUZZY_TIME_PATTERNS = re.compile(
    r"(刚才|刚刚|昨天|今天|明天|上周|下周|最近|不久前|"
    r"\bjust now\b|\byesterday\b|\btoday\b|\btomorrow\b|"
    r"\blast week\b|\brecently\b|\ba while ago\b|\bearlier\b)",
    re.IGNORECASE,
)

# Credential / secret patterns — hard reject (never store).
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(password|passwd|pwd)\s+is\s+\S+"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\b-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
]

# Speculative / non-fact language that should not be written as truth.
SPECULATION_PATTERNS = re.compile(
    r"(也许|可能|大概|猜测|假设|我觉得可能|should be|might be|probably|I guess|hypothetically)",
    re.IGNORECASE,
)

# Temporary emotional venting without durable fact.
EMOTION_ONLY_PATTERNS = re.compile(
    r"^(我好累|好烦|郁闷|难受|开心|哈哈+|lol+|haha+|[.。!！?？\s]+)$",
    re.IGNORECASE,
)

MAX_CLAIM_CHARS = 1200
MIN_CLAIM_CHARS = 8


@dataclass
class QualityVerdict:
    accepted: bool
    fact_claim: str = ""
    summary: str = ""
    content_hash: str = ""
    memory_type: str = ""
    confidence: float = 0.0
    importance: float = 0.5
    ttl_seconds: Optional[int] = None
    layer: str = "L2"
    is_scratch: bool = False
    reject_code: str = ""
    reject_message: str = ""
    fix: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def raise_if_rejected(self) -> None:
        if not self.accepted:
            raise ToolError(
                self.reject_code or "QUALITY_REJECTED",
                self.reject_message or "Memory rejected by Quality Kernel.",
                fix=self.fix or "Rewrite fact_claim as a grounded third-person fact.",
                retry_safe=True,
            )


class QualityKernel:
    """Deterministic gate between LLM proposal and Truth Store insert."""

    def __init__(
        self,
        *,
        min_confidence: float = 0.4,
        allow_scratch_low_confidence: bool = True,
    ):
        self.min_confidence = min_confidence
        self.allow_scratch_low_confidence = allow_scratch_low_confidence

    @staticmethod
    def content_hash(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]

    def validate(
        self,
        *,
        memory_type: str,
        fact_claim: str,
        confidence_score: float,
        is_scratch: bool = False,
        importance: Optional[float] = None,
    ) -> QualityVerdict:
        claim = (fact_claim or "").strip()
        mtype = (memory_type or "").strip()

        if mtype not in VALID_MEMORY_TYPES:
            return QualityVerdict(
                accepted=False,
                reject_code="INVALID_MEMORY_TYPE",
                reject_message=f"memory_type={mtype!r} is not allowed.",
                fix=(
                    "Use one of: factual_truth | user_preference | "
                    "procedure_rule | episodic_event | decision_record."
                ),
            )

        if not claim or len(claim) < MIN_CLAIM_CHARS:
            return QualityVerdict(
                accepted=False,
                reject_code="CLAIM_TOO_SHORT",
                reject_message=f"fact_claim must be ≥ {MIN_CLAIM_CHARS} characters.",
                fix="Write a compressed third-person fact, e.g. "
                    "'User prefers dark mode in VS Code with Monokai Pro.'",
            )

        if len(claim) > MAX_CLAIM_CHARS:
            return QualityVerdict(
                accepted=False,
                reject_code="CLAIM_TOO_LONG",
                reject_message=f"fact_claim exceeds {MAX_CLAIM_CHARS} chars.",
                fix="Compress to a single atomic fact. Put narrative in a later expand if needed.",
            )

        try:
            conf = float(confidence_score)
        except (TypeError, ValueError):
            return QualityVerdict(
                accepted=False,
                reject_code="INVALID_CONFIDENCE",
                reject_message="confidence_score must be a number in [0.1, 1.0].",
                fix="Pass confidence_score as a float, e.g. 0.85.",
            )

        if conf < 0.1 or conf > 1.0:
            return QualityVerdict(
                accepted=False,
                reject_code="CONFIDENCE_OUT_OF_RANGE",
                reject_message=f"confidence_score={conf} outside [0.1, 1.0].",
                fix="Clamp to [0.1, 1.0]. Low certainty → do not commit durable truth.",
            )

        for pat in SECRET_PATTERNS:
            if pat.search(claim):
                return QualityVerdict(
                    accepted=False,
                    reject_code="SECRET_DETECTED",
                    reject_message="fact_claim appears to contain credentials or secrets.",
                    fix="Redact secrets. Store only non-sensitive facts "
                        "(e.g. 'User uses SiliconFlow for embeddings' — never the key).",
                    metadata={"retry_safe": False},
                )

        if EMOTION_ONLY_PATTERNS.match(claim):
            return QualityVerdict(
                accepted=False,
                reject_code="EMOTION_ONLY",
                reject_message="Temporary emotion without durable fact is rejected.",
                fix="Only commit if there is a lasting preference, procedure, or event fact.",
            )

        if mtype == "factual_truth" and SPECULATION_PATTERNS.search(claim):
            return QualityVerdict(
                accepted=False,
                reject_code="SPECULATION_AS_TRUTH",
                reject_message="Speculative language cannot be stored as factual_truth.",
                fix="Either reclassify as episodic_event with lower confidence, "
                    "or rewrite as verified third-person fact without 也许/可能/probably.",
            )

        if FUZZY_TIME_PATTERNS.search(claim):
            return QualityVerdict(
                accepted=False,
                reject_code="FUZZY_TIME",
                reject_message="fact_claim contains relative/fuzzy time references.",
                fix="Replace '刚才/昨天/today' with absolute anchors "
                    "(ISO date or explicit event name). Example: "
                    "'On 2026-08-04 user decided to migrate storage to SQLite.'",
            )

        # Low confidence → scratch only (session buffer), not durable L0/L2.
        force_scratch = is_scratch
        if conf < self.min_confidence:
            if self.allow_scratch_low_confidence:
                force_scratch = True
            else:
                return QualityVerdict(
                    accepted=False,
                    reject_code="LOW_CONFIDENCE",
                    reject_message=f"confidence_score={conf} < min={self.min_confidence}.",
                    fix="Do not persist uncertain claims. Re-verify with user, then retry.",
                )

        # Typed defaults injected at write boundary (LLM may omit)
        td = defaults_for(mtype)
        imp = float(importance) if importance is not None else float(td.get("importance", 0.5))
        imp = max(0.0, min(1.0, imp))

        ttl = td.get("ttl_seconds")
        ttl_days = td.get("ttl_days")
        layer = "scratch" if force_scratch else td.get("layer", "L2")

        summary = claim if len(claim) <= 240 else claim[:237] + "..."
        chash = self.content_hash(claim)

        return QualityVerdict(
            accepted=True,
            fact_claim=claim,
            summary=summary,
            content_hash=chash,
            memory_type=mtype,
            confidence=conf,
            importance=imp,
            ttl_seconds=ttl,
            layer=layer,
            is_scratch=force_scratch,
            metadata={
                "min_confidence": self.min_confidence,
                "status": td.get("status", "active"),
                "ttl_days": ttl_days,
                "validator_kind": td.get("validator_kind", "quality_kernel"),
                "authority": td.get("authority", "agent"),
                "sensitivity": td.get("sensitivity", "normal"),
            },
        )
