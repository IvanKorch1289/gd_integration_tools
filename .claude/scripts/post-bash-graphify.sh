#!/bin/sh
set -eu

CMD=$(
python3 - <<'PY'
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get("tool_input", {}).get("command", ""))
except Exception:
    print("")
PY
)

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$ROOT" ] || exit 0

case "$CMD" in
  git\ commit*|make\ commit*|make\ bump*|uv\ run\ semantic-release\ version*)
    cd "$ROOT"
    graphify update . >/dev/null 2>&1 || true
    printf '✅ graphify updated after commit/release\n'
    ;;
  *)
    ;;
esac

exit 0