"""Re-export the benchmark probe so tests and the script share one list."""

from probe_facts import FACTS, QUERIES

__all__ = ["FACTS", "QUERIES"]
