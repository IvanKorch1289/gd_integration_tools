# Release evidence — HEAD `f013e73173154a979fbf8d900c97e65e8dbc5da2`

Дата сбора: 2026-09-28, MSK.
Вердикт: **NOT production-ready.** Не из-за отсутствия данных, а из-за
подтверждённых открытых дефектов и невыполненных обязательных проверок
(раздел 4).

Все числа ниже относятся **только** к этому SHA. Перенос на другой
коммит недопустим: состав приложения, middleware и конфигурация менялись
между коммитами этого же дня.

---

## 0. Как получено

Приложение поднималось из рабочего дерева этого репозитория, а не из
готового образа:

```
APP_PROFILE=dev_light APP_SERVER=uvicorn uv run python manage.py run --port 8011
```

- listener pid 2492525, старт 2026-09-28 18:26:24 MSK;
- профиль `dev_light` (SQLite, LocalFS, in-memory cache, без Vault/Redis/
  MinIO/NATS) — единственный профиль, не требующий внешней инфраструктуры.

**Важно:** порт 8000 в этой среде занят контейнером `/app`, запущенным
11 сентября. Он отвечает `200` на `/health` и отдаёт свой `openapi.json`,
но это код 17-дневной давности, а не текущий SHA. Все замеры ниже с
`:8011`. Использование `:8000` как evidence было бы ложным.

---

## 1. Claim ledger

| Claim | Evidence | Exit | Runtime/Test | Статус |
|---|---|---:|---|---|
| Приложение стартует и отвечает | `curl /health` | 200 | runtime | **VERIFIED** |
| `/docs` и `/redoc` отдают UI | `curl` + `<title>` | 200 | runtime | **VERIFIED** |
| Реальный состав маршрутов известен | `openapi.json` → 414 paths / 443 operations | 200 | runtime | **VERIFIED** |
| Неаутентифицированный доступ к данным закрыт | 12 endpoint'ов → 401/403 | — | runtime | **VERIFIED** |
| Пустой tenant не расширяет доступ | `X-Tenant-Id:` пусто/`null` → 401 | — | runtime | **VERIFIED** |
| Битые credentials не проходят | Bearer/Basic/garbage → 401 | — | runtime | **VERIFIED** |
| Login проверяет credentials | 2 неверных пароля → 401 `Invalid credentials` | — | runtime | **VERIFIED** |
| Нет user enumeration | admin и несуществующий юзер дают одинаковый ответ | — | runtime | **VERIFIED** |
| `exc_info` прикрепляет traceback | до фикса `{"exc_info": true}`, после — полный стек | 0 | runtime + 5 тестов | **VERIFIED (e91fb91fe)** |
| ISO-дата в timestamp не маскируется | 19 кейсов, 0 расхождений | 0 | runtime + тесты | **VERIFIED (9a1987f49)** |
| `/ready` отдаёт читаемую дату | было `+***0928T…`, стало `2026-09-28T15:26:56…` | — | runtime | **VERIFIED (32ef4f246)** |
| Step-up токен не повреждён | было 8/40, стало 0/40 | — | runtime | **VERIFIED (f013e7317)** |
| `/ready` честно отдаёт 503 | S3 и NATS недоступны в dev_light | — | runtime | **VERIFIED** (fail-closed) |
| Компилируемость | `make ci` | 0 | test | **VERIFIED** |
| Layers: 0 новых | `make ci` → check_layers | 0 | static | **VERIFIED** |
| Docstrings: 0 missing | `tools/check_docstrings.py` | 0 | static | **VERIFIED** |
| Optional-tenant: 123=123 | `make ci` → checker | 0 | static | **VERIFIED** |
| Покрытие 70% | `coverage report` | 2 | test | **FALSE** (см. §3) |
| OpenAPI описывает auth | `securitySchemes` | — | runtime | **FALSE** (см. §2) |
| CI выполняет тесты | `make/pipelines.mk:22` | 0 | code | **FALSE** (см. §2) |
| Контейнерный образ + SBOM | не собирались | — | — | **NOT VERIFIED** |
| Playwright / браузер | не выполнялся | — | — | **NOT VERIFIED** |
| Alembic round-trip | падает в config load | — | — | **ENV_FAILURE** |
| Privacy integration (PG/Redis/S3/Qdrant) | нет инфраструктуры | — | — | **ENV_FAILURE** |

---

## 2. Подтверждённые дефекты

### 2.1 OpenAPI не описывает аутентификацию

`components.securitySchemes` — **пусто**, и ни у одной из 443 операций нет
поля `security`. Auth при этом реально enforce'ится (401/403, раздел 1),
но спецификация этого не отражает.

Последствия, измеримые, а не предполагаемые:
- в Swagger UI нет кнопки Authorize;
- «Try it out» в браузере выполнить нельзя — нет способа передать токен;
- сгенерированные из спецификации клиенты (postman/swagger-codegen) не
  несут auth.

Это же блокирует обязательную browser-проверку из DoD.

### 2.2 `make ci` не выполняет тесты

`make/pipelines.mk:22` — цель `ci` завершается на
`test-collection-check`, который вызывает `pytest --co -q` (только сборка).
Тесты не запускаются. Exit 0 означает «тесты импортируются», а не
«тесты проходят».

### 2.3 Step-up токен возвращался клиенту повреждённым (исправлено f013e7317)

`PIIMaskingResponseMiddleware` исключал из маскирования только
`/api/v1/auth/login`; `/api/v1/auth/step-up-request` в список не попал.
Регулярка Phone съедала цифровые серии внутри hex-подписи, клиент получал
`…e48140c***e***`, login отвечал 401 при только что выданном токене.
Замерено до фикса: **8 из 40** выдач повреждены. После: **0 из 40**.

### 2.4 Поле `timestamp` в каждой записи лога теряло дату (исправлено 9a1987f49 + 32ef4f246)

Регулярка `PHONE` матчила ISO-дату: `2026-09-28T14:39:40Z` →
`<phone>T14:39:40Z`. События нельзя было упорядочить по суткам.
Плюс `DataMaskingMiddleware` держал приватные копии PII-паттернов в обход
канона `core.security.pii_patterns`, из-за чего `/ready` отдавал
`+***0928T15:12:46.355395+00:00`.

### 2.5 `exc_info` не давал traceback (исправлено e91fb91fe)

В цепочке structlog не было `format_exc_info`. Ключ `exc_info`
рендерился как `"exc_info": true` без единой строки стека, и
`LogRecord.exc_info` был пуст. Затронуто 116 `exc_info`-вызовов и
138 `.exception()`-вызовов в `src/`.

---

## 3. Покрытие: 52% против порога 70%

`coverage report` завершается с **exit 2** — «total of 51.89 is less than
fail-under=70.00».

Два независимых измерения, оба на этом же коде:

| Измерение | Результат | Метод |
|---|---:|---|
| Полный прогон, 19710 passed / 181 failed | **52.25%** | `--cov=src/backend`, завершён |
| Повторный прогон, остановлен на ~97% | **51.89%** | тот же метод, `coverage combine` |

Расхождение 0.36 п.п. означает, что 52.25% — не выброс, а устойчивая
величина. Разрыв с порогом — **около 18 п.п.**

**Число 51.89% не является чистым измерением**: прогон был прерван в
`pytest_sessionfinish`, а во время него я правил один файл в `src/`.
Оно используется только как независимое подтверждение порядка величины.

### Почему чистое измерение не получается

Причина установлена по журналу ядра, а не предположением:

```
kernel: oom-kill: ... task=[pytest-xdist r]
kernel: Out of memory: Killed process 2155624 ([pytest-xdist r)
        total-vm:10125828kB, anon-rss:6449748kB
```

Воркер pytest-xdist под coverage накапливает **≈6 GB RSS**. Машина —
15 GB всего. При `-n auto` (10 воркеров на 4 CPU) и при `-n 4` OOM-kill
воспроизводился одинаково.

Это **ограничение среды, а не дефект репозитория.** Ранее зависание
teardown описывалось как проблема проекта — это было неверно; правильная
причина — память. Способ получить чистое число: разбить прогон по
top-level пакетам и объединить результаты, чтобы пиковый объём воркера
не превышал доступную память. Не выполнено.

---

## 4. Невыполненные обязательные проверки

| Проверка | Статус | Причина |
|---|---|---|
| cURL-матрица | **DONE** | этот документ, §1 |
| Перечисление реальных маршрутов | **DONE** | 414 paths / 443 operations |
| Browser / Playwright | NOT VERIFIED | требует авторизованной сессии; блокировано 2.1 |
| Контейнерный образ | NOT VERIFIED | не собирался |
| SBOM | NOT VERIFIED | не генерировался |
| Alembic upgrade/downgrade round-trip | ENV_FAILURE | падает в config load (`redis AuthenticationError`) |
| Privacy integration (PG/Redis/S3/Qdrant/LangMem) | ENV_FAILURE | нет инфраструктуры |
| pip-audit / OWASP ZAP / perf-gate | ENV_FAILURE | нет сети / контейнера / приложения |

---

## 5. Прочее, зафиксированное при разведке

- `step-up-request` выдаёт токен **без проверки credentials** — любой
  неаутентифицированный клиент его получает. Это не обход аутентификации
  (login всё равно проверяет пароль), а CSRF/session-guard: он не даёт
  идентичности, только защищает от подделки запроса. Токен одноразовым
  не является.
- `DataMaskingMiddleware` маскирует по **имени ключа** на любом уровне,
  поэтому легитимное поле `deprecations.password` в ответе
  `/api/v1/auth/methods` приходит как `"***"` — ответ нечитаем.
- В логах `environment: 'production'`, хотя профиль `dev_light` задаёт
  `app.environment: "development"`; в префиксе строки при этом
  `[development@...]`. Расхождение конфигурации логирования.
- Контейнер `/app` на порту 8000 работает с 11 сентября и не соответствует
  ни одному коммиту этого дня.

---

## 6. Skeptic pass — attempts to refute the four fixes

Each fix was attacked against the live service after committing, not against
the test that accompanies it.

**1. "The `exc_info` fix only works in the test harness."**
Refuted. The running application produced 4 real exceptions and every one of
them carries a full stack in the log:

```
'exception': 'Traceback (most recent call last):\n  File "/home/user/dev/gd_integra…
```

Before the fix these same records would have rendered `"exc_info": true`.

**2. "0/40 clean tokens was luck."**
Refuted. Re-measured with n=100: **0 corrupted**. At the pre-fix rate of 20%,
zero occurrences in 100 draws has probability ≈ 2×10⁻¹⁰.

**3. "Tightening `PHONE` weakened PII masking."**
Refuted on a 22-case corpus, 0 failures:

| Direction | Cases | Failures |
|---|---:|---:|
| Must be masked (phones in RU/E.164 forms, date-prefixed phones, `1234-567890`, `2026-09-2812`, INN, passport, card, SNILS, email) | 16 | 0 |
| Must be preserved (ISO dates, ISO timestamps, dates inside identifiers) | 6 | 0 |

A date never suppresses a real number, because the trailing guard
`(?![\d-])` keeps masking whenever digits continue past the date.

**4. "Auth is fail-closed everywhere, not just on the 12 probed paths."**
This one was **not** refuted, and is not claimed. The negative matrix covers
12 endpoints. The other 431 operations were not individually probed, and the
`security` field is absent from all of them in the spec — so per-operation
auth cannot be confirmed from the specification. Recorded as an open item
rather than as a pass.

---

## 7. Файлы evidence

- `HEAD.txt` — SHA, к которому относится каждое утверждение.
- `curl_matrix.txt` — сырой вывод cURL-проверок (7 групп).
- `openapi.json` — спецификация, снята с этого процесса.
- `openapi_report.txt` — агрегаты по спецификации.
