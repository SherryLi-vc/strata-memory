# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | ✅ |

## Reporting a Vulnerability

All data stays local by default. We take privacy and security seriously.

If you discover a security issue, please report it privately:

- **GitHub Security Advisories** (preferred)
- **Email**: vizhangkk@gmail.com

Please do NOT open a public issue for security vulnerabilities.

## Security Design

- **Local-first**: All data stored locally; zero external uploads
- **Path traversal protection**: `drawer_path()` validates all paths stay inside the Palace directory
- **SQL injection hardened**: All queries use parameterized bindings; dynamic values are type-validated and clamped
- **API key protection**: `api_key` is excluded from serialization and sourced from `STRATA_API_KEY` env var
- **Multi-tenant isolation**: Wings + tenant_id provide strict namespace separation
- **Audit trail**: Every memorize/wake_up/search operation is logged (Markdown + SQLite)
- **Air-gapped ready**: Works entirely offline; no external API calls except embedding (configurable to local)

## Recent Security Audits

The v0.2.0 release incorporated fixes from a full security audit (June 2026):

- P0-01: SQL injection via `LIMIT` — fixed with `int()` clamping
- P0-02: API key plaintext storage — fixed with env var fallback + serialization exclusion
- P0-03: Path traversal via user/room params — fixed with segment sanitization + `.resolve()` sandbox

Thank you for helping keep Strata Memory secure.
