# graphify-aliases.sh — shell-функции для graphify CLI.
# Использование:
#   source .shared/context/graphify-aliases.sh
#
# После этого доступны:
#   gq "<question>"    — graphify query (BFS traversal, рекомендуемый)
#   gp "A" "B"         — graphify path (shortest path)
#   gx "X"             — graphify explain (plain-language)
#   gu [path]          — graphify update (re-extract, default = .)
#   ge [path]          — graphify extract (headless, AST + LLM)
#   gt                 — graphify tree (D3 HTML)
#   gh-status          — graphify hook status
#   gh-install         — graphify hook install (post-commit + post-checkout)
#   gh-uninstall       — graphify hook uninstall
#
# Зависимости:
#   - graphify должен быть в PATH (https://github.com/...graphify или pip install)
#   - graphify-out/ должен существовать (запустите `gu .` для первичной генерации)

# Защита от двойного source
if [ -n "$_GRAPHIFY_ALIASES_LOADED" ]; then
    return 0
fi
_GRAPHIFY_ALIASES_LOADED=1

# Дефолтный путь к graph (если нужно)
: "${GRAPHIFY_GRAPH:=graphify-out/graph.json}"
export GRAPHIFY_GRAPH

# Проверка что graphify в PATH
if ! command -v graphify >/dev/null 2>&1; then
    # shellcheck disable=SC2154
    echo "[graphify-aliases] WARNING: 'graphify' не найден в PATH. Алиасы не будут работать." >&2
    echo "  Установка: см. graphify README (https://github.com/...) или 'pip install graphify'." >&2
fi

# gq — query (BFS по графу)
gq() {
    if [ -z "$1" ]; then
        echo "Usage: gq \"<question>\"" >&2
        return 1
    fi
    graphify query "$@"
}

# gp — path (shortest path между двумя узлами)
gp() {
    if [ -z "$1" ] || [ -z "$2" ]; then
        echo "Usage: gp \"<node-a>\" \"<node-b>\"" >&2
        return 1
    fi
    graphify path "$@"
}

# gx — explain (plain-language)
gx() {
    if [ -z "$1" ]; then
        echo "Usage: gx \"<node>\"" >&2
        return 1
    fi
    graphify explain "$@"
}

# gu — update (re-extract; default = current dir)
gu() {
    local target="${1:-.}"
    graphify update "$target"
}

# ge — extract (headless AST + LLM)
ge() {
    local target="${1:-.}"
    graphify extract "$target"
}

# gt — tree (D3 HTML)
gt() {
    graphify tree
}

# gh-* — hook management
gh-status() {
    graphify hook status
}

gh-install() {
    graphify hook install
}

gh-uninstall() {
    graphify hook uninstall
}

# gs — short for "graphify shell" — выводит статус
gs() {
    echo "=== graphify status ==="
    echo "  binary: $(command -v graphify || echo 'NOT FOUND')"
    echo "  graph: $GRAPHIFY_GRAPH"
    [ -f "$GRAPHIFY_GRAPH" ] && echo "  graph.json: $(stat -c %s "$GRAPHIFY_GRAPH" 2>/dev/null) bytes" || echo "  graph.json: MISSING (run 'gu .' to generate)"
    [ -d "graphify-out" ] && ls graphify-out/ | head -10
}
