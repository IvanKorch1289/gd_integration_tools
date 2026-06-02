#!/bin/bash
# vault-index.sh — regenerate vault/INDEX.md из:
#   - ls -t vault/session-*.md | head -10
#   - tail -20 vault/DECISIONS-LIVE.md
#   - ls -lt vault/knowledge/ | head -10
#
# Использование: ./vault-index.sh
# Exit codes: 0 OK, 1 vault/ не найден

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VAULT_DIR="$PROJECT_ROOT/vault"
INDEX_FILE="$VAULT_DIR/INDEX.md"

if [ ! -d "$VAULT_DIR" ]; then
    printf '\033[31m[ERROR] vault/ не найден в %s\033[0m\n' "$PROJECT_ROOT" >&2
    exit 1
fi

# Build index
{
    printf '# INDEX — указатель на артефакты vault/\n\n'
    printf '> **Авто-генерируется** через `make vault-index` (Sprint 37 W1, фаза 4).\n'
    printf '> Не редактировать вручную.\n\n'

    printf '## Последние сессии (session-*-summary.md, latest 10)\n\n'
    if ls -t "$VAULT_DIR"/session-*.md 2>/dev/null | head -10 | grep -q .; then
        ls -t "$VAULT_DIR"/session-*.md | head -10 | while read -r f; do
            base=$(basename "$f")
            size=$(stat -c %s "$f" 2>/dev/null || stat -f %z "$f" 2>/dev/null)
            ts=$(stat -c %y "$f" 2>/dev/null | cut -d' ' -f1 || stat -f %Sm "$f" 2>/dev/null | cut -d' ' -f1)
            printf -- '- `%s` (%s, %s bytes)\n' "$base" "$ts" "$size"
        done
    else
        printf '_нет файлов_\n'
    fi
    printf '\n'

    printf '## Live-решения (DECISIONS-LIVE.md, latest 20 строк)\n\n'
    if [ -f "$VAULT_DIR/DECISIONS-LIVE.md" ]; then
        tail -20 "$VAULT_DIR/DECISIONS-LIVE.md" | sed 's/^/    /'
    else
        printf '_нет файла_\n'
    fi
    printf '\n'

    printf '## Знания (knowledge/, latest 10)\n\n'
    if [ -d "$VAULT_DIR/knowledge" ]; then
        # list files in knowledge/ except .gitkeep
        files=$(ls -lt "$VAULT_DIR/knowledge" 2>/dev/null | grep -v "^total" | grep -v "\.gitkeep" | head -10)
        if [ -n "$files" ]; then
            echo "$files" | while read -r line; do
                # parse "perms links owner group size month day time name"
                name=$(echo "$line" | awk '{print $NF}')
                if [ -n "$name" ] && [ "$name" != "." ] && [ "$name" != ".." ]; then
                    printf -- '- `%s`\n' "$name"
                fi
            done
        else
            printf '_нет файлов_\n'
        fi
    else
        printf '_нет папки_\n'
    fi
    printf '\n'

    printf -- '----\n\n_Сгенерировано: %s_\n' "$(date +'%Y-%m-%d %H:%M')"
} > "$INDEX_FILE"

printf '\033[32m[OK] %s обновлён (%s bytes, %s строк)\033[0m\n' \
    "$INDEX_FILE" \
    "$(stat -c %s "$INDEX_FILE" 2>/dev/null || stat -f %z "$INDEX_FILE" 2>/dev/null)" \
    "$(wc -l < "$INDEX_FILE")"
