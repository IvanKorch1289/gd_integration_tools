#!/usr/bin/env bash
# Чанковый эталонный прогон `-m unit` — проверка предложенного фикса F-AU.
#
# Проблема: и xdist (`-n 2`), и последовательный прогон гибнут по OOM на
# 97–99% (ядро: `Killed process … anon-rss:5209116kB` / `6899284kB`).
# Гипотеза фикса: ограничение не в параллелизме, а в **размере процесса**,
# поэтому прогон нужно разбить по каталогам — каждый чанк в отдельном процессе.
#
# Скрипт НЕ является make-таргетом: это проверка гипотезы, а не новый
# канонический способ запуска. Канон — `make unit-tests`.
#
# Запуск (из корня репозитория):
#   MONGO_ENABLED=false bash artifacts/current_audit/unit_chunked.sh
#
# Пишёт `/tmp/unit_chunks.tsv` (по строке на чанк) и печатает сводку.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"
OUT=/tmp/unit_chunks.tsv
LOGDIR=/tmp/unit_chunks
mkdir -p "$LOGDIR"
: > "$OUT"

cd "$ROOT" || exit 1

# Порядок — от самых больших каталогов к самым маленьким: так у hardest
# чанка максимально свежая память. Корневые `tests/unit/test_*.py` идут
# последним отдельным чанком: без них покрытие неполное (7 файлов).
ROOT_FILES=$(ls "$ROOT"/tests/unit/test_*.py 2>/dev/null | wc -l)
CHUNKS=$(for d in tests/unit/*/; do
  [ -d "$d" ] || continue
  case "$d" in */__pycache__/) continue ;; esac
  echo "$d"
done | while read -r d; do echo "$(find "$d" -name 'test_*.py' | wc -l) $d"; done | sort -rn | cut -d' ' -f2-)
if [ "$ROOT_FILES" -gt 0 ]; then
  CHUNKS="$CHUNKS $ROOT/tests/unit"
fi
echo "# корневых файлов в последнем чанке: $ROOT_FILES" >&2

total_pass=0; total_fail=0; total_skip=0; chunks_ok=0; chunks_fail=0

for chunk in $CHUNKS; do
  name=$(echo "$chunk" | sed 's#tests/unit/##; s#/$##')
  log="$LOGDIR/${name}.log"
  "$PY" -m pytest "$chunk" -m unit -q --no-header -p no:randomly > "$log" 2>&1
  code=$?
  summary=$(grep -E "^[0-9]+ (passed|failed)|passed.*in [0-9]+|no tests ran" "$log" | tail -1)
  [ -z "$summary" ] && summary=$(tail -1 "$log" | tr -d '\r' | cut -c1-100)
  printf '%s\t%s\t%s\n' "$name" "$code" "$summary" >> "$OUT"

  if [ "$code" -eq 0 ]; then
    chunks_ok=$((chunks_ok+1))
    printf '  %-16s EXIT=0   %s\n' "$name" "${summary:0:70}"
  elif [ "$code" -eq 137 ] || [ "$code" -eq 9 ]; then
    chunks_fail=$((chunks_fail+1))
    printf '  %-16s EXIT=%-3s KILLED (OOM) %s\n' "$name" "$code" "${summary:0:40}"
  else
    chunks_fail=$((chunks_fail+1))
    printf '  %-16s EXIT=%-3s %s\n' "$name" "$code" "${summary:0:70}"
  fi
done

echo
echo "### Сводка чанкового прогона"
awk -F'\t' '{c[$2]++} END {for (k in c) printf "  EXIT=%s: %d чанков\n", k, c[k]}' "$OUT" | sort
echo "  зелёных чанков: $chunks_ok, не-зелёных: $chunks_fail"
echo "  таблица: $OUT"
echo
echo "### Сводка тестов по всем чанкам"
cat "$LOGDIR"/*.log 2>/dev/null | grep -E "^[0-9]+ passed|passed, .* in [0-9]" | tail -20
