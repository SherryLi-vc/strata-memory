# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.0.x   | ✅ |
| 0.2.x   | ⚠️ security fixes only |

## Reporting a Vulnerability

All data stays local by default. We take privacy and security seriously.

If you discover a security issue, please report it privately:

- **GitHub Security Advisories** (preferred)
- **Email**: vizhangkk@gmail.com

Please do NOT open a public issue for security vulnerabilities.

## Security Design (2.0)

- **Local-first SoT**: SQLite Truth Store on disk; no cloud write path
- **Credential isolation**: API keys only via `STRATA_API_KEY` (never persisted full key in config.json)
- **Quality Kernel**: rejects secrets / tokens / private keys at write time
- **CBT redaction**: defense-in-depth secret scrubbing before insert
- **Scope isolation**: hard fail on cross `user_id` / `tenant_id` expand
- **Confirmation gate**: `strata_rebuild_index` requires `confirm=true` (index only; SoT untouched)
- **Parameterized SQL**: all queries bound; LIMIT clamped
- **Path sandbox**: legacy Markdown paths still resolve inside palace
- **Audit + trajectory**: every tool call logged for post-incident review
- **Air-gapped ready**: embedding can be cloud or self-hosted; SoT never requires network

## Zero-trust defaults

| Risk | Mitigation |
|------|------------|
| Prompt injection → illicit write | No raw CRUD tools; Kernel + type enum + confidence floor |
| Prompt injection → index wipe | confirm gate on rebuild |
| Context dump / data exfil via recall | Progressive disclosure (id+summary first) |
| Cross-tenant leak | tenant_id + user_id checks on expand |
| Key leakage into memory | SECRET_DETECTED reject + redaction |

## Recent Audits

v0.2.0 fixed SQL LIMIT injection, API key plaintext, path traversal.

v2.0.0 adds write-time Quality Kernel, scope-checked expand, confirm gates, trajectory audit.
