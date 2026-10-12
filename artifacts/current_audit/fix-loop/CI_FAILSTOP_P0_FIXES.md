# FIX-LOOP — три подтверждённых P0 в CI-семантике

Дата: 2026-10-12
Аудит: `cf0802244` / baseline `ae70b1c34`
Регрессия: `tests/unit/tools/test_ci_fail_stop_semantics.py` (8 тестов)

Все три находки — **VERIFIED**: воспроизведены на живом коде, каждая имеет
regression-тест, который падает до фикса и проходит после.

---

## TYPE-P0-001 — падение mypy превращалось в «успешный» `make ci`

**Точный путь / символы**

* `make/quality.mk:65-76` — цель `type-check-strict` (вызывается из `make ci`)
* `make/quality.mk:82-92` — цель `type-check-strict-profile`

**Было**

```make
mypy --cache-dir=/dev/null -p src || ( \
    RET=$$?; \
    if [ $$RET -eq 2 ]; then \
        $(WARN) "Mypy crashed with INTERNAL ERROR. Bypassing..."; \
        exit 0; \
    else \
        exit $$RET; \
    fi )
```

**Факт vs ожидание**

| exit mypy | Факт (было) | Ожидание |
|---|---|---|
| 1 (ошибки типов) | 1 — корректно | 1 |
| **2 (internal error / crash)** | **0 — «Strict type check passed!»** | не 0 |
| 124 (timeout) | 124 | не 0 |

**Severity:** P0. **Runtime impact:** при падении mypy `make ci` зелёный,
при том что ни одной проверки типов не выполнено — gate не fail-stop.

**Способ воспроизведения**

```bash
git checkout HEAD -- make/quality.mk
uv run pytest tests/unit/tools/test_ci_fail_stop_semantics.py -q
# 3 падают: type-check-strict, type-check-strict-profile, behavioral
```

**Fix:** `exit 0` → `exit 2` + поясняющие сообщения. Обходной путь для
разработки остался — `make type-check` (явно помечен «non-blocking» в своём
docstring, `|| printf`, и **никем не вызывается** из CI).

**Regression test:** `test_type_check_gate_does_not_swallow_mypy_internal_error`
(параметризован на обе цели) + поведенческий
`test_ci_type_stage_is_fail_stop_for_every_nonzero_mypy_code`, который
исполняет рецепт ровно как make (отдельный шелл на логическую строку,
склейка `\`-продолжений, стоп на первой непустой) для mypy rc ∈ {1, 2, 124}.

**Команда проверки:** `uv run pytest tests/unit/tools/test_ci_fail_stop_semantics.py -q` → 8 passed.

---

## DEPENDENCIES-P0-002 — `make ci` не проверял CVE вообще

**Точный путь**

* `make/security.mk:115-127` — `audit-deps` (`pip-audit ... || true`)
* `make/pipelines.mk:22-40` — цепочка `ci` (не содержала CVE-шага)
* `tools/pip_audit_gate.py` — компенсирующий гейт, вызывался **только** из
  `.github/workflows/security.yml:160`

**Факт:** комментарий в `make/security.mk:46` утверждал
«CVE-handling отделено: `exit != 0` подавляется `|| true`, гейт —
`tools/pip_audit_gate.py`». По факту гейт был подключён только к GitHub
Actions, а **не** к `make ci` — то есть локальный / make-путь к зависимостям
CVE не проверял вообще. Компенсирующий механизм был «сиротой».

**Severity:** P0 (supply chain, V15 Security Constraint R4).

**Fix:**
1. `tools/pip_audit_gate.py` — добавлен необязательный `--report PATH`.
   Значение по умолчанию (`pip-audit.json` в cwd) сохранено, поэтому
   `.github/workflows/security.yml` работает без правок. Это устранило
   несовместимость: `audit-deps` писал в `dist/`, а гейт читал только `./`.
2. Новая цель `make cve-gate` (`make/security.mk`) = `audit-deps` + гейт.
3. `make ci` (`make/pipelines.mk`) теперь вызывает `$(MAKE) cve-gate`.

**Regression test:** `test_ci_runs_the_cve_gate` (рекурсивный обход цепочки
`$(MAKE)`-зависимостей от `ci`, с исключением комментариев — иначе упоминание
`tools/pip_audit_gate.py` в комментарии `make/security.mk:46` считалось бы
вызовом) + `test_pip_audit_failures_are_not_silently_discarded_in_ci_path`.

---

## DEPENDENCIES-P0-008 — «зелёный» CVE-гейт на устаревшем отчёте

Обнаружено при end-to-end прогоне `make cve-gate` после фикса P0-002.

**Точный путь:** `make/security.mk:126` (`audit-deps`).

**Факт (наблюдение, 2026-10-12)**

```
ERROR:pip_audit._cli:Failed to install packages: ...
ERROR: No matching distribution found for deepteam==1.0.9
[32mpip-audit clean (dist/pip-audit.json)[0m          ← ложь
PASS: 0 unignored vulnerabilities
CVE gate passed (0 unignored vulnerabilities)        ← ложь
cve-gate exit: 0
```

`dist/pip-audit.json` имел mtime **2026-09-29** (13 дней), 361 зависимость,
0 уязвимостей. Каталог `dist/` в `.gitignore:61`, поэтому отчёт жил месяцами.

**Механика:** pip-audit сегодня упал (не разрешается `deepteam==1.0.9` под
Python 3.14) → `|| true` подавил код → новый отчёт не создан → гейт прочитал
**прошлый** отчёт и выдал PASS. Т.е. два подавления складывались в fail-open:
suppressed producer + stale artifact.

**Severity:** P0. **Runtime impact:** `make ci` объявляет «CVE gate passed»
по данным недельной давности, в то время как воспроизводимость зависимостей
уже сломана.

**Fix (`audit-deps`)**
1. `rm -f dist/pip-audit.json` **до** сканирования — старый отчёт физически
   не может быть прочитан как свежий;
2. убран `|| true` — ошибка pip-audit (сбой инструмента) пробрасывается;
3. `test -s dist/pip-audit.json || exit 2` — «успех» печатается только если
   отчёт реально создан и непуст.

**Поведенческое доказательство после фикса**

```bash
rm -f dist/pip-audit.json
make cve-gate
# → make: *** [make/security.mk:133: cve-gate] Ошибка 2   (exit 2)
```

**Regression test:** `test_audit_deps_does_not_suppress_pip_audit_failure`,
`test_audit_deps_removes_stale_report_before_scanning`,
`test_audit_deps_asserts_report_was_produced`.

---

## Смежная находка (не входила в скоуп фикса)

**`deepteam==1.0.9` не устанавливается на Python 3.14** (требует
`>=3.9,<3.14`). Это блокирует воспроизводимость `pip-audit` для всей
зависимости-графы и должно быть решено отдельным atomic-коммитом
(обновление версии / исключение из `uv.lock` с ADR). Пока не решено —
`make cve-gate` будет честно падать, а это правильное поведение.

---

## Устаревшая находка, отклонённая после проверки

**`tests/tools/test_pip_audit_gate_allowlist.py::test_load_allowlist_returns_nonempty_set`
падает — стейл-тест, не регрессия.**

Тест утверждает `len(allowlist) >= 20`. Фактически
`.security/pip-audit-allowlist.txt` содержит 24 строки, из которых все —
комментарии, и завершается `Active count: 0 entries.` Allowlist был
намеренно очищен (S58 / ADR-0290: 22 stale CVE удалены, PYSEC-2026-3552
снята после обновления `uv.lock`, diskcache CVE удалены после устранения
зависимости). `_load_allowlist()` корректно возвращает 0.

Это **не** P0: тест живёт в `tests/tools/`, тогда как `make ci` гоняет
`pytest tests/unit`. Расхождение задокументировано как стейл; отдельным
atomic-коммитом тест следует привести к текущей политике allowlist
(ожидать 0 активных записей + проверять отсутствие «забытых» allowlist-строк
с неразобранным ID).

---

## Итоговая проверка

```bash
# до фикса
git checkout HEAD -- make/quality.mk make/pipelines.mk make/security.mk
uv run pytest tests/unit/tools/test_ci_fail_stop_semantics.py -q
# 8 failed

# после фикса
uv run pytest tests/unit/tools/test_ci_fail_stop_semantics.py -q
# 8 passed

make lint-strict          # exit 0
make cve-gate             # exit 2 — ЧЕСТНЫЙ провал (deepteam != py3.14)
```