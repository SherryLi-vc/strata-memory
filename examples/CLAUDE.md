# Strata Memory 2.0 — Claude Desktop / Agent notes

## Env

- `STRATA_API_KEY` — embedding provider key (preferred over tool args)
- `STRATA_PALACE` — data root (default `~/.strata/palace`)

## Tool flow

1. `strata_init(mode="personal")` once
2. `strata_doctor()` self-check
3. Session start: `recall_context(user_id, query)`
4. Need detail: `expand_memory_detail(user_id, memory_id)`
5. Persist fact: `commit_memory(user_id, memory_type, fact_claim, confidence_score)`
6. End of session: `promote_session(user_id, session_id)` if scratch was used

## Never

- Write secrets into memory
- Use relative time in fact_claim
- Dump full search results into the prompt — expand selectively
