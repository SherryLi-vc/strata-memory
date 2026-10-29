# Strata Memory 2.0 — Claude Desktop / Agent notes

## Env

- `STRATA_API_KEY` or `STRATA_EMBEDDING_API_KEY` — embedding key. Set it in the host environment. Never paste it into chat.
- `STRATA_EMBEDDING_PROVIDER` — `local` (default, no API key), `siliconflow`, `openai`, or `openai_compatible`
- `STRATA_EMBEDDING_BASE_URL` — OpenAI-compatible embeddings root
- `STRATA_EMBEDDING_MODEL` — model id
- `STRATA_PALACE` — data root (default `~/.strata/palace`)

The default provider is `local`, so memory text stays on the machine. SiliconFlow (`https://api.siliconflow.cn/v1`, `BAAI/bge-m3`) and other HTTP providers receive memory text and recall queries when selected. SQLite stays local.

Operating procedure and host templates: `skills/strata-memory/SKILL.md`.

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
