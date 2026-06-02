#!/bin/bash
# session-start.sh — append новую запись в vault/SESSIONS.md (открытая).
# Использование: AGENT=<claude|kimi> MSG="..." [SLUG="..."] ./session-start.sh
# Если MSG не указан — будет prompt.
#
# Записывает в формате:
#   ### YYYY-MM-DD HH:MM | <agent> | <slug>
#   **Start:** <msg>
#   **Close:** in progress
#   **Context:** (пусто — заполняется по ходу сессии)
#   **Decisions:** (пусто)
#   **Files:** (пусто)
#   **Next:** (пусто)
#
# Exit codes: 0 OK, 1 invalid args, 2 vault not writable

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SESSIONS_FILE="$PROJECT_ROOT/vault/SESSIONS.md"

# Validate AGENT
if [ -z "$AGENT" ]; then
    printf '\033[31m[ERROR] AGENT=<claude|kimi> обязателен\033[0m\n' >&2
    printf 'Пример: AGENT=claude MSG="refactor sync-permissions" %s\n' "$0" >&2
    exit 1
fi

if [ "$AGENT" != "claude" ] && [ "$AGENT" != "kimi" ]; then
    printf '\033[31m[ERROR] AGENT должен быть claude или kimi (получено: %s)\033[0m\n' "$AGENT" >&2
    exit 1
fi

# MSG optional
if [ -z "$MSG" ]; then
    MSG="(без описания)"
fi

# SLUG optional
if [ -z "$SLUG" ]; then
    SLUG=$(echo "$MSG" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '-' | sed 's/^-//;s/-$//' | head -c 40)
    if [ -z "$SLUG" ]; then
        SLUG="session"
    fi
fi

# Ensure vault dir
if [ ! -d "$PROJECT_ROOT/vault" ]; then
    printf '\033[31m[ERROR] vault/ не найден в %s\033[0m\n' "$PROJECT_ROOT" >&2
    exit 2
fi

# Ensure SESSIONS.md exists
if [ ! -f "$SESSIONS_FILE" ]; then
    printf '\033[31m[ERROR] %s не найден\033[0m\n' "$SESSIONS_FILE" >&2
    exit 2
fi

# Get timestamp
TS=$(date +'%Y-%m-%d %H:%M')

# Build entry (use python for proper UTF-8 + escaping)
ENTRY=$(AGENT="$AGENT" MSG="$MSG" SLUG="$SLUG" TS="$TS" python3 <<'PYEOF'
import os
agent = os.environ["AGENT"]
msg = os.environ["MSG"]
slug = os.environ["SLUG"]
ts = os.environ["TS"]

# Format: "### TS | agent | slug" + fields
# Replace newlines in msg with " | "
msg_clean = msg.replace("\n", " | ")

entry = f"""
### {ts} | {agent} | {slug}
**Start:** {msg_clean}
**Close:** in progress
**Context:**
**Decisions:**
**Files:**
**Next:**
"""
print(entry, end="")
PYEOF
)

# Append to SESSIONS.md
printf '%s' "$ENTRY" >> "$SESSIONS_FILE"

printf '\033[32m[OK] Записано в vault/SESSIONS.md:\033[0m\n'
printf '  %s | %s | %s\n' "$TS" "$AGENT" "$SLUG"
printf '  msg: %s\n' "$MSG"
