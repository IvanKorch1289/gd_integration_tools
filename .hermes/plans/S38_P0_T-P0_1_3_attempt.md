# T-P0.1.3 — ruff --fix attempt (ОТКАЗАНО)

> **Дата:** 02.06.2026
> **Статус:** ❌ Отказано — слишком большой diff для одного коммита
> **План:** per-file commit strategy (вместо bulk)

## Что попытался сделать

`ruff check src/ --fix` (safe fixes) для механической очистки I001 (sort imports), F401 (unused imports), F841 (unused variables), S110 (try-except-pass), S603 (subprocess annotations), и др.

## Результат

- **394 → 2 ruff errors** (только 2 E402 manual, не fixable)
- **219 файлов изменено** (sort imports + удаления)
- **+2209 / -2276 LOC** (net -67, типично для unused removal)

## Почему отказано

1. **Working tree содержал 200+ чужих uncommitted M-файлов** (parallels процесс активно работает: P4 Consul, P7 Groovy DSL, etc)
2. **Ruff --fix применил fixes ПОВЕРХ чужих изменений** — diff показывает 219 файлов, но это **mix** моих + чужих изменений
3. **`git add src/` добавил 213 файлов, ВКЛЮЧАЯ untracked `consul_config.py`** от параллельного процесса (НЕ мой)
4. **Невозможно разделить** мои mechanical fixes от чужих semantic changes без `git add -p` (интерактивно)

## Что я сделал

1. `ruff check src/ --fix` — 394→2 errors
2. `git add src/` — 213 файлов в stage
3. Увидел `consul_config.py` (untracked) и 200+ чужих M в stage
4. **`git restore --staged src/`** — unstage всё
5. **НЕ коммитил** — риск сломать parallels работу

## Текущее состояние

- Working tree: ~210 файлов с mix мои+чужие изменения
- Staged: ничего
- Comitted: 13 моих предыдущих коммитов в S38
- Ruff: 2 remaining errors (E402 manual)

## Уроки

1. **Bulk `ruff --fix` опасен** при активной parallels работе
2. **Per-file commit strategy** нужна: `ruff check <file> --fix` + `git add <file>` + commit
3. **Working tree noise** — parallels процесс создаёт постоянный поток изменений
4. **Mechanical changes** невозможно отделить от semantic без явного baseline

## Альтернативы (для следующей попытки)

| Подход | Плюсы | Минусы |
|--------|-------|--------|
| **A. Per-file ruff + commit** | Безопасно, атомарно | 219 коммитов (too many) |
| **B. Per-layer ruff (core/, dsl/, etc)** | Умеренно | 8-10 коммитов, может конфликтовать с parallels |
| **C. Drop ruff --fix, использовать только `--select` для safe rules** | Минимальный риск | Только sort imports + unused vars |
| **D. Принять 2 remaining E402, не фиксить** | Ничего не делаем | Не прогресс |
| **E. Дождаться стабилизации parallels (нет движения 1 час)** | Безопасно | Непредсказуемо |

**Рекомендация:** **C** (select safe rules + per-file) — минимальный риск, видимый прогресс.

## Что НЕ делаем

- ❌ Не коммитим 219 файлов одним блоком
- ❌ Не делаем `git restore` (уничтожит чужие изменения)
- ❌ Не делаем `git stash` (mix не разделяется)

## Следующий шаг

**T-P0.1.3a** — selective ruff fix: только `I001` (sort imports) для **одного** слоя (например, `core/auth/`) как proof-of-concept. Если работает — расширяем.

Альтернативно: переключаемся на другую часть P0 (coverage gap analysis после pytest завершится в background).
