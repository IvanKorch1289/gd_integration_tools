---
name: code-review
description: Чеклист code review изменений в gd_integration_tools (security → архитектура → качество → стиль)
type: prompt
whenToUse: Делаю ревью изменённых файлов в gd_integration_tools
---

# Code review в gd_integration_tools

Запускай этот skill при ревью любых изменений (свой код, чужой MR, перед
коммитом крупной фичи).

## Принципы

- **НЕ выдумывай улучшения.** Если проблем нет — так и скажи.
- Итог — **список конкретных задач** с указанием файла, строки и действия.
  Не абстрактные "можно улучшить", а "в `src/services/foo.py:42` заменить
  sync `requests` на async `httpx`".
- Если не уверен — задай вопрос или напиши "требует проверки человеком".
- Severity: 🔴 блокер (нельзя мержить), 🟡 важно (можно с дискуссией),
  🟢 нит (стиль/улучшение).
- **Ревью ≠ переписывание.** Не предлагай "а давайте сделаем по-другому"
  если текущее работает.

## Перед стартом

1. `git diff main...HEAD --stat` — масштаб изменений.
2. `git log main..HEAD --oneline` — какие коммиты вошли.
3. Прочитай `CLAUDE.md` если ещё не в контексте.
4. Связанные ADR: `.claude/DECISIONS.md`, `KNOWN_ISSUES.md`.

## Чеклист (в этом порядке)

### 1. 🔒 Security (блокер)

- Секреты в коде? `.env`, токены, пароли, ключи, PII.
  Команда: `make secrets-check` (detect-secrets).
- SQL/NoSQL injection? Параметризованные запросы, нет f-string в SQL.
- Path traversal? `Path`/`os.path.join` безопасно, без `..`?
- Pickle/yaml.load на user input? → заменить.
- `subprocess` с `shell=True` и user input?
- SSRF? URL из user input → HTTP request?
- `eval`/`exec` на user input?

### 2. 🏗️ Архитектура и слои (блокер)

- Импорты между слоями (см. python-dev skill):
  - `extensions/*` напрямую импортирует `infrastructure/*` или `services/*`?
  - `core/` импортирует что-то из `src/`?
  - `entrypoints/` импортирует что-то не из разрешённых слоёв?
- Бизнес-логика вне `extensions/<name>/`?
- Cross-layer доступ идёт через capability-checked фасады или напрямую?
- Новый dependency? Обоснован ли, есть ли в `pyproject.toml`?
- Нарушает ли V15/V22 архитектурные решения (см. `PLAN.md`)?

### 3. ⚡ Async / I/O (блокер)

- Blocking I/O в async-контексте? (`requests`, `time.sleep`, sync `open()`,
  sync DB driver).
- `asyncio.run()` внутри async?
- `await` без таймаута на внешних вызовах?
- `asyncio.gather` без `return_exceptions=True`?
- `for x in async_iter:` без `async for`?

### 4. 🐛 Корректность (важно)

- Граничные случаи: `None`, пустые коллекции, нулевые значения.
- Обработка исключений: голый `except`, `except Exception` без логов,
  `except` без re-raise когда нужно.
- Off-by-one в slicing/range.
- `is` vs `==` для чисел/строк (используй `is` только для `None`/`True`/`False`).
- `mutable default argument` (def foo(x=[]) — bug).
- Ресурсы: файлы/соединения без `async with`/`with`.

### 5. 🧪 Тесты (важно)

- Нет тестов на новую логику?
- Тесты проверяют только happy path?
- Нет тестов на ошибки / граничные случаи?
- Async-код тестируется через `pytest.mark.asyncio`?
- Integration тесты требуют docker — он в CI?
- Coverage не падает? `make test` + `pytest --cov`.

### 6. 📝 Type hints и схемы (важно)

- Все сигнатуры с type hints (включая `-> None`)?
- Pydantic модели для DTO/API?
- `Any` без обоснования?
- `type: ignore` без комментария с причиной?

### 7. 🎨 Стиль и читаемость (нит)

- Имена: snake_case (функции/переменные), PascalCase (классы), UPPER_SNAKE
  (константы)?
- Magic numbers → settings/env?
- `print(...)` для отладки → `logger`/`structlog`?
- Docstring для public API?
- Длина строки/функции/модуля разумна?
- Дублирование кода? (3+ повторов — вынести)

### 8. 📊 Производительность (важно, если код горячий путь)

- N+1 запросов? (lazy loading → joinedload/selectinload)
- Лишние `await` в цикле, которые можно `gather`?
- Большие объекты в памяти без `iter()`/`stream`?
- Hot path без `lru_cache` где уместно?
- `list(...)` там, где хватит генератора?

### 9. 📜 Логи и observability (важно)

- Структурное логирование (`structlog`), не f-string?
- `correlation_id` в логах?
- PII в логах? (запрещено)
- Метрики/трейсы для критичных операций?

### 10. 🔄 Миграции и обратная совместимость (блокер если БД)

- Изменение схемы БД без миграции? (Alembic)
- Breaking change в API? (versioning, deprecation warning)
- Изменение env vars / config без fallback?

## Формат отчёта

```markdown
# Code review: <branch> / <PR title>

## Сводка
- Файлов: N, +X / -Y
- Severity: 🔴 X, 🟡 Y, 🟢 Z
- Вердикт: MERGE / FIX / DISCUSS

## 🔴 Блокеры (N)
1. `path/to/file.py:LINE` — что не так, что сделать.

## 🟡 Важно (N)
1. `path/to/file.py:LINE` — ...

## 🟢 Нит (N)
1. `path/to/file.py:LINE` — ...

## ❓ Вопросы (N)
1. Почему выбран подход X, а не Y? Ссылка на ADR.

## ✅ Что сделано хорошо
- ... (коротко, 1-3 пункта, не расхваливание)
```

## Что НЕ делать

- Не предлагать "общее улучшение" без конкретного файла/строки.
- Не обсуждать стиль, если уже есть `make format` и он зелёный.
- Не предлагать рефакторинг, не относящийся к изменённому коду
  (вынести в отдельный issue).
- Не спорить о naming если имя осмысленное.
- Не дублировать комментарии — код говорит сам за себя.
