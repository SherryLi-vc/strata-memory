"""CBT Middleware — pure-Python write/read safety gate.

NOT delegated to the LLM's "good judgment".
  - Detect cognitive distortion patterns
  - Redact residual secrets (defense-in-depth after Quality Kernel)
  - Force 48h cooling sandbox for negative schemas (no L0 promotion)

Returns structured results for the pipeline to enforce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Extended distortion patterns (CN + EN)
DISTORTION_RULES: list[tuple[str, str]] = [
    (r"全搞砸了|彻底完了|永远不行|完全没用|一无是处|catastrophe|ruined everything", "catastrophizing"),
    (r"从来都|每次都|永远不会|总是失败|always fail|never succeed|every single time", "overgeneralization"),
    (r"我就是个?废物|我这个人就|我太(笨|差|烂)|I'?m (worthless|a failure|stupid)", "negative_self_labeling"),
    (r"要么.*要么|不是.*就是|all or nothing|black and white", "black_and_white"),
]

SECRET_REDACT = [
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key|secret[_-]?key)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
]


@dataclass
class RedactionResult:
    text: str
    redacted: bool = False
    redaction_count: int = 0


@dataclass
class CBTAssessment:
    is_negative_schema: bool = False
    distortions: list[dict] = field(default_factory=list)
    force_cooling: bool = False
    block_l0_promotion: bool = False
    reframed_hint: str = ""
    redacted_text: str = ""


class CBTMiddleware:
    """Deterministic CBT + redaction middleware."""

    def __init__(self, *, enabled: bool = True, cooling_hours: int = 48):
        self.enabled = enabled
        self.cooling_hours = cooling_hours
        self._compiled = [
            (re.compile(pat, re.IGNORECASE), name) for pat, name in DISTORTION_RULES
        ]

    def redact(self, text: str) -> RedactionResult:
        out = text
        count = 0
        for pat, repl in SECRET_REDACT:
            new_out, n = pat.subn(repl, out)
            if n:
                count += n
                out = new_out
        return RedactionResult(text=out, redacted=count > 0, redaction_count=count)

    def assess(self, text: str) -> CBTAssessment:
        red = self.redact(text)
        assessment = CBTAssessment(redacted_text=red.text)

        if not self.enabled:
            return assessment

        for cre, name in self._compiled:
            if cre.search(red.text):
                assessment.distortions.append({
                    "detected_distortion": name,
                    "is_negative_schema": True,
                })

        if assessment.distortions:
            assessment.is_negative_schema = True
            assessment.force_cooling = True
            assessment.block_l0_promotion = True
            names = ", ".join(d["detected_distortion"] for d in assessment.distortions)
            assessment.reframed_hint = (
                f"Content flagged for cognitive patterns ({names}). "
                f"Held in cooling sandbox for {self.cooling_hours}h; "
                "not eligible for L0 core promotion."
            )
        return assessment

    def defusion_frame(self, summary: str) -> str:
        """Passive-mode framing for recall of negative schemas."""
        return (
            f"[reframed] {summary}\n"
            "*Note: This memory may contain self-critical distortion. "
            "Prefer alternative, specific interpretations over global self-judgment.*"
        )
