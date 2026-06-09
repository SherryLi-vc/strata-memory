"""Audit logging — all MCP operations tracked.

Enterprise requirement: every memorize / wake_up / search / update
operation must be recorded with before/after snapshots and agent identity.

Two backends:
  - Markdown:    human-readable, Git-auditable (always on)
  - PostgreSQL:  structured, queryable (company mode, V2)
"""

from __future__ import annotations

from pathlib import Path

from ..storage.markdown import write_audit_entry


class AuditLogger:
    """Transparent audit logger — writes Markdown + optionally DB."""

    def __init__(self, palace: Path, agent_id: str = "strata-mcp"):
        self.palace = palace
        self.agent_id = agent_id

    def log(
        self, action: str, target: str, summary: str, *,
        before: str = "", after: str = "",
    ) -> None:
        write_audit_entry(
            palace=self.palace, action=action, agent_id=self.agent_id,
            target=target, summary=summary, before=before, after=after,
        )

    def log_memorize(self, user_id: str, content_preview: str, result: dict) -> None:
        self.log("memorize", f"wing=users/{user_id}",
                 f"Recorded {result.get('characters', 0)} chars to {result.get('drawer', '?')}",
                 after=content_preview[:200])

    def log_wake_up(self, user_id: str, query: str, result: dict) -> None:
        self.log("wake_up", f"wing=users/{user_id}",
                 f"Depth={result.get('context_depth')} L1={result.get('l1_entries')} L2={result.get('l2_results')} tokens={result.get('token_estimate')}",
                 after=query[:200])

    def log_search(self, user_id: str, query: str, result_count: int) -> None:
        self.log("search", f"wing=users/{user_id}",
                 f"Query: {query[:100]} → {result_count} results")

    def log_init(self, mode: str, provider: str) -> None:
        self.log("strata_init", f"mode={mode}",
                 f"Initialized with provider={provider}, mode={mode}")
