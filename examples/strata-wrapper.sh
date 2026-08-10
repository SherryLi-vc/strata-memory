#!/bin/bash
# Example Hermes MCP launcher for Strata Memory 2.0.
# Install: cp examples/strata-wrapper.sh ~/.hermes/scripts/strata-wrapper.sh && chmod +x ...
#
# See docs in repo README / this script header for key resolution order.

set -euo pipefail

STRATA_DIR="${STRATA_DIR:-$HOME/Desktop/个人开发/MCP/strata-memory}"
HERMES_ENV="${HERMES_ENV:-$HOME/.hermes/.env}"
STRATA_KEY_FILE="${STRATA_KEY_FILE:-$HOME/.strata/api_key}"
OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-$HOME/.openclaw/openclaw.json}"

_key_usable() {
  local k="${1:-}"
  [ -n "$k" ] || return 1
  # NOTE: do not use case patterns like *** — * is a glob and rejects all keys
  if [[ "$k" == *"..."* || "$k" == *"…"* ]]; then return 1; fi
  if [[ "$k" == "***" || "$k" == "REDACTED" || "$k" == __OPENCLAW* ]]; then return 1; fi
  [ "${#k}" -ge 20 ] || return 1
  return 0
}

_load_env_file_key() {
  local file="$1" name="$2"
  [ -f "$file" ] || return 0
  local line
  line=$(grep -E "^[[:space:]]*${name}=" "$file" 2>/dev/null | tail -n1 || true)
  [ -n "$line" ] || return 0
  local val="${line#*=}"
  val="${val%$'\r'}"
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  echo -n "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

_pick_best_openclaw_key() {
  python3 - <<'PY'
import json, re, sys
from pathlib import Path
p = Path.home() / ".openclaw" / "openclaw.json"
if not p.exists():
    sys.exit(0)
raw = p.read_text(encoding="utf-8", errors="replace")
cands = re.findall(r"sk-[A-Za-z0-9_-]{8,}", raw)
good = [k for k in cands if "..." not in k and "…" not in k and len(k) >= 20]
if not good:
    try:
        cfg = json.loads(raw)
        k = (cfg.get("agents", {}).get("defaults", {}).get("memorySearch", {})
             .get("remote", {}) or {}).get("apiKey", "") or ""
        if k and "..." not in k and len(k) >= 20:
            good.append(k)
    except Exception:
        pass
if good:
    print(max(good, key=len), end="")
PY
}

RESOLVED=""
SOURCE=""

for cand_name in STRATA_API_KEY SILICONFLOW_API_KEY; do
  cand_val="${!cand_name:-}"
  if _key_usable "$cand_val"; then
    RESOLVED="$cand_val"; SOURCE="env:$cand_name"; break
  fi
done

if [ -z "$RESOLVED" ]; then
  for name in STRATA_API_KEY SILICONFLOW_API_KEY; do
    cand="$(_load_env_file_key "$HERMES_ENV" "$name" || true)"
    if _key_usable "$cand"; then
      RESOLVED="$cand"; SOURCE="file:$HERMES_ENV:$name"; break
    fi
  done
fi

if [ -z "$RESOLVED" ] && [ -f "$STRATA_KEY_FILE" ]; then
  cand="$(tr -d '\r\n' < "$STRATA_KEY_FILE" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  if _key_usable "$cand"; then
    RESOLVED="$cand"; SOURCE="file:$STRATA_KEY_FILE"
  fi
fi

if [ -z "$RESOLVED" ]; then
  cand="$(_pick_best_openclaw_key || true)"
  if _key_usable "$cand"; then
    RESOLVED="$cand"; SOURCE="openclaw:longest-sk"
  fi
fi

if [ -z "$RESOLVED" ]; then
  echo "[STRATA-WRAP] ERROR: no usable API key. Add STRATA_API_KEY to ~/.hermes/.env" >&2
else
  export STRATA_API_KEY="$RESOLVED"
  echo "[STRATA-WRAP] key from ${SOURCE} (len=${#RESOLVED}, prefix=${RESOLVED:0:6}…)" >&2
fi

export STRATA_PALACE="${STRATA_PALACE:-$HOME/.strata/palace}"
cd "$STRATA_DIR"
exec uv run strata-memory-mcp "$@"
