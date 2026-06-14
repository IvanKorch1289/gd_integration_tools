#!/usr/bin/env sh
# S113 W4 — pre-push hook для auto-prune stale layer-allowlist entries.
# Complement к S112 W1 --prune-allowlist flag.
# Не блокирует push, только warn'ит если stale entries удалены.
set -e
LOG=$(uv run python tools/check_layers.py --prune-allowlist 2>&1) || true
echo "$LOG"
echo "$LOG" | grep -q 'stale entries removed' && \
    echo "WARN: stale allowlist entries pruned — recommit с обновлённым allowlist" || \
    echo "OK: allowlist up-to-date (0 stale)"
