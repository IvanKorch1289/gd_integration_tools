#!/usr/bin/env bash
# SessionStart hook для Claude Code.
#
# Цель: напомнить Claude обновить CLAUDE.md, если в src/ были значимые изменения
# после последнего коммита, в котором менялся сам CLAUDE.md.
#
# Вывод этого скрипта добавляется в контекст стартующей сессии Claude (stdout
# → additionalContext). Мягкий режим: никаких блокировок, только напоминание.
#
# Триггеры (по matcher в .claude/settings.json): startup | resume | clear.

set -euo pipefail

# Перейти в корень репозитория (скрипт лежит в scripts/).
cd "$(dirname "$0")/.."

# Проверки базовой согласованности.
if ! command -v git >/dev/null 2>&1; then
    exit 0
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    exit 0
fi

if [ ! -f CLAUDE.md ]; then
    cat <<'EOF'
## CLAUDE.md отсутствует

В корне репозитория нет CLAUDE.md — knowledge graph проекта. Рекомендация:
пересоздать его по текущему состоянию проекта. Исторический шаблон —
коммит `[phase:H1] knowledge graph для junior-разработчиков`.
EOF
    exit 0
fi

# Последний коммит, в котором менялся CLAUDE.md.
LAST_CLAUDE_COMMIT=$(git log -1 --format='%H' -- CLAUDE.md 2>/dev/null || true)

if [ -z "${LAST_CLAUDE_COMMIT:-}" ]; then
    # CLAUDE.md не в истории (untracked) — отдельное напоминание не нужно,
    # stop-hook git-check сам попросит закоммитить.
    exit 0
fi

LAST_CLAUDE_SHORT="${LAST_CLAUDE_COMMIT:0:7}"
LAST_CLAUDE_DATE=$(git log -1 --format='%cd' --date=short "$LAST_CLAUDE_COMMIT" 2>/dev/null || echo "?")

# Файлы в src/, изменённые после LAST_CLAUDE_COMMIT.
CHANGED_FILES=$(git diff --name-only "$LAST_CLAUDE_COMMIT" HEAD -- src/ 2>/dev/null || true)

if [ -z "${CHANGED_FILES:-}" ]; then
    # Нет изменений в src/ — ничего не вывожу.
    exit 0
fi

FILE_COUNT=$(printf '%s\n' "$CHANGED_FILES" | grep -c . || true)
CHANGED_DIRS=$(printf '%s\n' "$CHANGED_FILES" | awk -F/ 'NF>=2 { print $1"/"$2 }' | sort -u | head -20)

# Сигналы о том, что наверняка потребует обновления CLAUDE.md.
SIGNAL_FILES=$(printf '%s\n' "$CHANGED_FILES" | grep -E \
    -e '^src/dsl/engine/processors/' \
    -e '^src/dsl/builder\.py$' \
    -e '^src/dsl/engine/(exchange|pipeline|context|execution_engine)\.py$' \
    -e '^src/core/(config/|svcs_registry|tenancy/)' \
    -e '^src/infrastructure/(resilience/|eventing/|policy/|ai/|database/models/)' \
    -e '^src/entrypoints/[^/]+/' \
    || true)
SIGNAL_COUNT=$(printf '%s\n' "$SIGNAL_FILES" | grep -c . || true)

cat <<EOF
## CLAUDE.md · проверка актуальности

Последний коммит с правкой CLAUDE.md: \`$LAST_CLAUDE_SHORT\` ($LAST_CLAUDE_DATE).
После этого в \`src/\` изменено файлов: **$FILE_COUNT** (в том числе архитектурно-
значимых: **$SIGNAL_COUNT**).

Затронутые области:
\`\`\`
$CHANGED_DIRS
\`\`\`

**Правило:** перед началом новой работы — прочитай CLAUDE.md целиком. Если в
ходе текущей сессии появятся значимые структурные изменения (новый модуль,
замена библиотеки, новый процессор, новый entrypoint, новая ORM-модель) —
перезапиши соответствующую секцию CLAUDE.md и добавь строку в «Историю
изменений» внизу файла.

Секции-кандидаты по областям изменений:
- \`src/dsl/engine/processors/\` → §8 каталог процессоров
- \`src/dsl/builder.py\`, \`src/dsl/engine/\` → §7 DSL-концепции
- \`src/core/\` → §9 DI или §10 Config или §17 Multi-tenancy
- \`src/infrastructure/resilience/\` → §14
- \`src/infrastructure/eventing/\` → §15
- \`src/infrastructure/ai/\` → §19
- \`src/infrastructure/database/models/\` → §11.1
- \`src/entrypoints/\` → §21
EOF
