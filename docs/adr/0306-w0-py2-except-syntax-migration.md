# ADR-0306 — W0 P0-BLOCKER: миграция `except A, B:` → `except (A, B):`

* Статус: **Accepted** (2026-09-23, cycle 152).
* Связано с: MINIMAX W0 P0-BLOCKER; ADR-0084 (библиотеки > кастом); ADR-0304
  (fail-closed AST parse); S260 re-audit (16 файлов с Py2-pattern).
* Заменяет/уточняет: предыдущий комментарий в `.github/workflows/lint.yml`
  утверждавший, что ``except A, B:`` «каноничен по PEP 758» — это было
  неверно (PEP 758 разрешает ``except*`` без скобок, не ``except A, B:``).

## Контекст

В репо накопилось **233 строки** Python-2 синтаксиса ``except A, B:``
(запятая вместо скобок) в 177 файлах (src/backend:147, src/frontend:12,
tests:16, tools:1, extensions/scripts:0). Распределение по зонам
(infrastructure 35, dsl 26, entrypoints 20, services 19, core 12, plugins 3,
frontend 12) совпадает с заявлением S260 re-audit.

**Семантика на Python 3.10+**:

* PEG-парсер (PEP 617, default с Python 3.10) трактует ``except A, B:`` как
  ``except (A, B):`` с ``name=None`` — кортеж без as-переменной.
* AST-анализ показывает ``ast.ExceptHandler(type=Tuple(...), name=None)`` —
  **не** ``except A as B:`` (как утверждал старый комментарий в lint.yml).
* То есть на Py3.10+ Py2-pattern формально валиден, ловит оба типа как
  кортеж, но:
    * Архаичен стилистически.
    * Ломает совместимость с Py3.9 и ранее.
    * Вводит в заблуждение читателя (PEP 758 говорит про ``except*``, не про
      этот синтаксис — старый комментарий в CI был ошибочен).
    * Ломает detection в guard-тесте (искал ``ast.ExceptHandler.name`` —
      молчит на Py3.10+).

**Критические пути, пострадавшие от регрессии**:

* Guard-тест ``tests/unit/test_py2_except_syntax_lint.py:35`` сам содержал
  ту же ошибку (``except UnicodeDecodeError, OSError:``), что маскировало
  регрессию.
* ``tools/checks/check_python3_syntax.py:78`` содержал тот же паттерн.
* 16 test-файлов, 12 streamlit-страниц — все имели Py2-архаизм.

## Решение

### 1. AST-based миграция (W0 P0-BLOCKER fix)

Создан ``tools/migrate_py2_except.py`` (9265 байт) — AST-aware line-splice
инструмент, который:

* Парсит каждый ``.py`` через ``ast.parse`` (fail-closed на syntax errors).
* Находит ``ast.ExceptHandler`` где ``type`` — ``Tuple`` и ``name`` — None.
* Для каждого handler-а проверяет source-строку: если между ``except`` и
  ``:`` есть запятая и скобки несбалансированы (т.е. не ``except (A, B):``)
  и нет ``as`` — это Py2-pattern.
* Применяет ``except (<types>):`` с явными скобками.
* После замены — ``compile()`` всего файла (fail-closed).

**Результат миграции**: 177 файлов, 234 строки, exit 0, 0 потерянного LOC
семантики. Один atomic commit.

### 2. Guard-тест переписан (S260 fix)

``tests/unit/test_py2_except_syntax_lint.py`` теперь использует **source-line
detection** вместо AST-attribute ``name``. Эвристика:

1. Строка начинается с ``except``.
2. Между ``except`` и ``:`` есть запятая.
3. Скобки несбалансированы в этом сегменте.
4. Нет `` as `` (валидный Py3 синтаксис с as-binding).

**Verification**: guard PASS (2/2) после миграции; guard FAIL на regression
(тестовый файл с ``except ValueError, TypeError:`` в чистом src/backend).

### 3. CI gate расширен

``.github/workflows/lint.yml:48`` уже содержал blocking
``uv run python -m compileall -q src extensions scripts tools tests``
(был подключён в S141/S260 audit). W0 добавляет:

* Исправленный комментарий в lint.yml (L51-54): PEP 758 ссылка удалена
  (была неверной); новый комментарий явно говорит, что Py2-pattern
  запрещён policy проекта.
* Guard-тест (``tests/unit/test_py2_except_syntax_lint.py``) — часть
  существующего pytest-runner job, теперь корректно ловит regression.

### 4. README синхронизирован

``README.md:664`` — таблица метрик обновлена: ``compileall src/backend/``
exit 0 подтверждён + короткая справка про миграцию (177 файлов / 234 строки).

## Альтернативы (рассмотренные, отклонённые)

* **PEP 758 compliance**: оставить ``except A, B:`` как канонический стиль.
  Отклонено: PEP 758 говорит про ``except*``, не про этот синтаксис.
  Старый комментарий в lint.yml был основан на неверной интерпретации.
* **Игнорировать warning, оставить как legacy**: отклонено — guard-тест
  молчит на Py3.10+, regression не ловится.
* **Regex-based миграция**: отклонено — ломает строки/docstrings/f-strings.
  AST-based line-splice безопаснее.

## Последствия

**Плюсы**:

* compileall exit 0 на всём репо (4892+ .py файлов).
* Guard-тест корректно ловит regression (fail на Py2-pattern, pass после
  миграции).
* Совместимость с Py3.9 и ранее (если когда-то потребуется).
* Стилистическая явность — ``except (A, B):`` — explicit tuple.

**Минусы / риски**:

* Изменение 177 файлов — большой diff. Но semantic-identical, поведение
  не меняется.
* Любой новый код должен соблюдать policy: ``except (A, B):``, не
  ``except A, B:``. Guard-тест это enforcing.

## Verification (cycle 152)

```bash
# 1. compileall exit 0
python3.14 -m compileall -q src/ extensions/ scripts/ tools/ tests/
# Exit: 0

# 2. check_python3_syntax exit 0
python3.14 tools/checks/check_python3_syntax.py --root src/backend
python3.14 tools/checks/check_python3_syntax.py --root tests
python3.14 tools/checks/check_python3_syntax.py --root tools
# Exit: 0 (3 SyntaxWarning про docstrings с `\``, не блокирующие)

# 3. Guard-тест зелёный
python3.14 -m pytest tests/unit/test_py2_except_syntax_lint.py -q
# 2 passed

# 4. Regression-тест guard-теста — Py2-pattern во временном src/backend
# должен ловиться. Verified в cycle 152 (subprocess test).
```

## Связанные изменения

* ``tools/migrate_py2_except.py`` — AST-based миграционный tool (новый).
* ``tests/unit/test_py2_except_syntax_lint.py`` — guard переписан на
  source-line detection.
* 177 файлов мигрированы (src/backend + src/frontend + tests + tools).
* ``README.md:664`` — синхронизирован с реальностью.
* ``.github/workflows/lint.yml:51-54`` — комментарий исправлен (убрана
  неверная PEP 758 ссылка).
* ``CHANGELOG.md`` — запись цикла 152.
* ``docs/roadmap/PROGRESS_LEDGER.md`` — wave-memo для cycle 152.

Refs: MINIMAX W0 (P0-BLOCKER), S260 re-audit, ADR-0084, ADR-0304.