# Memory 3.0 Roadmap (from memory3.0.pages)

Aligned with **Slice C** shipped in `2.1.0`.

## Shipped (2.1.0 / Slice C)

| Item | Status |
|------|--------|
| Typed Freshness/TTL defaults + `decision_record` | ✅ |
| Forced `validator_kind` / status / ttl_days at write boundary | ✅ |
| Near-dup → supersede version chain | ✅ |
| Provenance JSON on insert | ✅ |
| Multi-signal rerank + `score_breakdown` | ✅ |
| `current_turn_only` session filter | ✅ |
| `strata_hygiene` (expired / dups / secrets / FTS) | ✅ |
| Doctor: hash dups + secret residual | ✅ |
| Schema v3 ALTER-safe migration | ✅ |

## Next (not in Slice C)

- Entity graph traversal / related-memory edges
- Journal-first full evidence chain UI
- Eval harness + gold set
- Enterprise viewer / kill switch
- Bi-temporal Graphiti-class validity intervals beyond supersede

## References

- Spec: `docs/superpowers/specs/2026-08-10-memory-3.0-slice-c-design.md`
- Upstream brief: Desktop `memory3.0.pages`
