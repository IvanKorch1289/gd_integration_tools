#!/bin/bash
# session-close.sh — закрыть последнюю открытую запись в vault/SESSIONS.md.
# Использование: AGENT=<claude|kimi> [MSG="..."] [CONTEXT="..."] [DECISIONS="..."] [FILES="..."] [NEXT="..."] ./session-close.sh
#
# Находит последнюю запись "### ... | <agent> | <slug>" с "**Close:** in progress"
# и заменяет на "**Close:** <timestamp> — <msg>". Также обновляет Context/Decisions/Files/Next.
#
# Exit codes: 0 OK, 1 invalid args, 2 no open entry found

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SESSIONS_FILE="$PROJECT_ROOT/vault/SESSIONS.md"

# Validate AGENT
if [ -z "$AGENT" ]; then
    printf '\033[31m[ERROR] AGENT=<claude|kimi> обязателен\033[0m\n' >&2
    exit 1
fi
if [ "$AGENT" != "claude" ] && [ "$AGENT" != "kimi" ]; then
    printf '\033[31m[ERROR] AGENT должен быть claude или kimi (получено: %s)\033[0m\n' "$AGENT" >&2
    exit 1
fi

# Ensure SESSIONS.md exists
if [ ! -f "$SESSIONS_FILE" ]; then
    printf '\033[31m[ERROR] %s не найден\033[0m\n' "$SESSIONS_FILE" >&2
    exit 2
fi

# Optional fields
MSG="${MSG:-сессия закрыта}"

# Update last open entry for AGENT using python (safe UTF-8, atomic)
TS=$(date +'%Y-%m-%d %H:%M')

python3 <<PYEOF
import os, re, sys
from pathlib import Path

agent = os.environ["AGENT"]
msg = os.environ["MSG"]
context = os.environ.get("CONTEXT", "")
decisions = os.environ.get("DECISIONS", "")
files = os.environ.get("FILES", "")
next_step = os.environ.get("NEXT", "")
ts = os.environ["TS"]

sessions_path = Path("$SESSIONS_FILE")
text = sessions_path.read_text(encoding="utf-8")
lines = text.split("\n")

# Find last open entry for AGENT
# Format: "### YYYY-MM-DD HH:MM | <agent> | <slug>"
# Close field: "**Close:** in progress" (or "in progress)")
entry_start = -1
entry_end = -1
close_line_idx = -1

for i, line in enumerate(lines):
    m = re.match(r"^### (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \| (\w+) \| (.*)$", line)
    if m and m.group(2) == agent:
        # Find **Close:** line in next 6 lines
        for j in range(i + 1, min(i + 8, len(lines))):
            if lines[j].startswith("**Close:**"):
                if "in progress" in lines[j]:
                    entry_start = i
                    close_line_idx = j
                break

if entry_start < 0:
    print(f"[ERROR] Не найдено открытой записи для agent={agent}", file=sys.stderr)
    sys.exit(2)

# Find end of entry (next "### " or end of file)
for k in range(entry_start + 1, len(lines)):
    if lines[k].startswith("### "):
        entry_end = k
        break
if entry_end < 0:
    entry_end = len(lines)

# Update **Close:** line
lines[close_line_idx] = f"**Close:** {ts} — {msg.replace(chr(10), ' | ')}"

# Update other fields if provided
for j in range(entry_start + 1, entry_end):
    if context and lines[j].startswith("**Context:**"):
        if lines[j].endswith("**Context:**"):
            lines[j] = f"**Context:** {context}"
        else:
            lines[j] = f"**Context:** {context}"
    elif decisions and lines[j].startswith("**Decisions:**"):
        if lines[j].endswith("**Decisions:**"):
            lines[j] = f"**Decisions:** {decisions}"
    elif files and lines[j].startswith("**Files:**"):
        if lines[j].endswith("**Files:**"):
            lines[j] = f"**Files:** {files}"
    elif next_step and lines[j].startswith("**Next:**"):
        if lines[j].endswith("**Next:**"):
            lines[j] = f"**Next:** {next_step}"

# Write back atomically
new_text = "\n".join(lines)
sessions_path.write_text(new_text, encoding="utf-8")

# Print summary
slug_m = re.match(r"^### \S+ \S+ \| \S+ \| (.*)$", lines[entry_start])
slug = slug_m.group(1) if slug_m else "?"
print(f"\033[32m[OK] Закрыта запись в vault/SESSIONS.md:\033[0m")
print(f"  agent={agent}, slug={slug}")
print(f"  close: {ts} — {msg}")
PYEOF
