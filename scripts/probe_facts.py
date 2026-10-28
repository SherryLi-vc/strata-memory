"""Shared L0 recall probe: 6 memories and 4 queries.

The markers are distinctive phrases. A correct top-1 hit contains the marker
in the card summary. Queries reuse surface forms from the claims so ranking
does not depend on a stemmer.
"""

from __future__ import annotations

FACTS: list[dict[str, str]] = [
    {
        "memory_type": "factual_truth",
        "fact_claim": "The API gateway listens on port 8017 in the production environment.",
        "marker": "port 8017",
    },
    {
        "memory_type": "user_preference",
        "fact_claim": "User prefers the Monokai Pro theme with dark mode in VS Code.",
        "marker": "Monokai Pro",
    },
    {
        "memory_type": "procedure_rule",
        "fact_claim": "Deploy procedure runs uv sync and then restarts the worker process.",
        "marker": "uv sync",
    },
    {
        "memory_type": "factual_truth",
        "fact_claim": "The dog named Mochi enjoys morning walks in the park.",
        "marker": "Mochi",
    },
    {
        "memory_type": "procedure_rule",
        "fact_claim": "Backup procedure copies the palace directory onto an encrypted disk.",
        "marker": "encrypted disk",
    },
    {
        "memory_type": "factual_truth",
        "fact_claim": "Staging database hostname is db-staging.internal.example for reports.",
        "marker": "db-staging.internal.example",
    },
]

QUERIES: list[tuple[str, str]] = [
    ("API gateway listens on port 8017", "port 8017"),
    ("Monokai Pro theme dark mode", "Monokai Pro"),
    ("Deploy procedure uv sync worker", "uv sync"),
    ("dog named Mochi morning walks", "Mochi"),
]
