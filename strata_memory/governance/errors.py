"""LLM-facing error reshaping.

Traditional stack traces are useless to a probabilistic model.
Every error MUST tell the model:
  1. what went wrong (code + short reason)
  2. how to fix parameters (concrete next action)
  3. whether retry is safe
"""

from __future__ import annotations

from typing import Any, Optional


class ToolError(Exception):
    """Structured error for MCP tool responses."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        fix: str,
        retry_safe: bool = True,
        fields: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fix = fix
        self.retry_safe = retry_safe
        self.fields = fields or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "error",
            "error_code": self.code,
            "message": self.message,
            "how_to_fix": self.fix,
            "retry_safe": self.retry_safe,
            "fields": self.fields,
        }


def error_payload(
    code: str,
    message: str,
    *,
    fix: str,
    retry_safe: bool = True,
    fields: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return ToolError(
        code, message, fix=fix, retry_safe=retry_safe, fields=fields
    ).to_dict()


def success_payload(data: dict[str, Any], *, message: str = "ok") -> dict[str, Any]:
    out = {"status": "ok", "message": message}
    out.update(data)
    return out
