# Release evidence — HEAD `bbadf108a2bdefacf7673d9bb9b78c7147619b77`

Дата сбора: 2026-09-28, MSK.
Вердикт: **NOT production-ready** — не из-за отсутствия данных, а из-за
подтверждённых открытых дефектов и невыполненных обязательных проверок.

Все числа относятся **только** к этому SHA. Перенос на другой коммит
недопустим.

Предыдущий evidence-каталог этого же дня:
[`f013e7317.../EVIDENCE.md`](../../f013e73173154a979fbf8d900c97e65e8dbc5da2/EVIDENCE.md).
Разница между двумя SHA — один коммит `bbadf108a` (описание аутентификации
в OpenAPI и исключение документации из маскирования ответов).

---

## 0. Как получено

Приложение поднималось из рабочего дерева этого репозитория:

```
APP_PROFILE=dev_light APP_SERVER=uvicorn uv run python manage.py run --port 8011
```

`dev_light` — профиль без внешней инфраструктуры (SQLite, LocalFS,
in-memory cache, без Vault/Redis/MinIO/NATS).

**Порт 8000 в этой среде занят контейнером `/app`, запущенным 11 сентября.**
Он отвечает 200 на `/health` и отдаёт свой `openapi.json`, но это код
17-дневной давности, а не текущий SHA. Все замеры — с `:8011`.

---

## 1. Что изменилось в этом SHA

**Дефект 2.1 из предыдущего evidence закрыт.** Спецификация теперь описывает
аутентификацию:

| Метрика | До | После |
|---|---:|---:|
| Операций с полем `security` | 0 / 443 | **443 / 443** |
| Объявлено `securitySchemes` | 0 | **4** |
| Неразрешённых ссычек `security` | — | **0** |
| Расхождений с рантайм-guard | — | **0** |
| Испорченных значений (`***`) в спеке | **16** | **0** |

Объявленные схемы: `bearerAuth` (JWT), `apiKeyAuth` (`X-API-Key`),
`basicAuth`, `samlSession` (cookie). Они соответствуют verifiers'ам
`core.auth.auth_selector`, которые вызывает `verify_request`.

Признак public выводится из `auth_required.is_path_public` с каноническим
`DEFAULT_PUBLIC_PATH_PREFIXES` — из того же источника, которым пользуется
рантайм-guard. Публичных операций ровно 5: `/health`, `/ready`,
`/api/v1/auth/methods`, `/api/v1/auth/login`, `/api/v1/auth/step-up-request`.

**Почему это было возможно.** Guard живёт в pure-ASGI middleware, который
FastAPI в схему не выводит: присутствие или отсутствие авторизации было
неизвестно генератору спецификации.

### Границы того, что теперь видно в спеке

Поле `security` описывает слой `AuthRequiredMiddleware`, а не всю цепочку:

- `/api/v1/auth/login` и `/api/v1/auth/step-up-request` входят в
  `DEFAULT_PUBLIC_PATH_PREFIXES` — их пропускает auth-guard, и в спеке они
  получают `security: []`. Их настоящая защита — следующий слой,
  `LoginStepUpMiddleware` (`X-Step-Up-Token` + rate-limit 10/5min), который
  OpenAPI выразить не может.
- Требование CSRF-cookie на изменяющих методах в спецификации не отражено.
- `MTLS` (transport-level) и `EXPRESS` / `EXPRESS_JWT` (заголовок
  `X-Express-HUID` от доверенного edge-прокси) схемами не описаны — для них
  не выдумывались схемы. Фактический набор методов виден в
  `core.auth.auth_selector._VERIFIERS`.

### Испорченные описания

До фикса в опубликованной спецификации 16 значений были заменены на `***`
**двумя разными маскерами**:

- `pii_masker._RU_SURNAMES` считает фамилией любое русское слово на
  `-ский` / `-ова` / `-ин`: `Семантический поиск` → `*** поиск`,
  `Логистический маршрут` → `*** маршрут`;
- правило phone съедало пример номера в описании поля;
- `DataMaskingMiddleware` маскирует значение **по имени ключа**, поэтому
  описание поля `token` становилось `***`.

Спецификация собирается из аннотаций исходного кода: runtime-данных и
данных арендаторов в ней нет (все 414 путей статические, определения
DSL-маршрутов в OpenAPI не попадают). Маскирование здесь не давало выигрыша
в приватности, но уничтожало контракт, который читают разработчики и
сгенерированные клиенты. `/openapi.json`, `/docs`, `/redoc` и
`/docs/oauth2-redirect` исключены из маскирования обоими маскерами.

Паттерн `_RU_SURNAMES` намеренно **не сужен**: сужение ослабило бы
privacy-контур. Вместо этого описания новых схем подобраны так, чтобы не
попадать под ложное срабатывание, и закреплены двумя тестами.

---

## 2. Claim ledger

| Claim | Evidence | Exit | Runtime/Test | Статус |
|---|---|---:|---|---|
| Приложение стартует и отвечает | `curl /health` | 200 | runtime | **VERIFIED** |
| `/docs`, `/redoc`, `/openapi.json` доступны | `curl` | 200 | runtime | **VERIFIED** |
| Спецификация описывает аутентификацию | 443/443 операций, 4 схемы, 0 битых ссылок | — | runtime | **VERIFIED (bbadf108a)** |
| Схема совпадает с рантайм-guard | 0 расхождений с `is_path_public` | — | runtime | **VERIFIED (bbadf108a)** |
| Спецификация не порчена маскером | 0 вхождений `***` (было 16) | — | runtime | **VERIFIED (bbadf108a)** |
| Неаутентифицированный доступ закрыт | 12 endpoint'ов → 401/403 | — | runtime | **VERIFIED** |
| Пустой tenant не расширяет доступ | `X-Tenant-Id:` пусто/`null` → 401 | — | runtime | **VERIFIED** |
| Битые credentials не проходят | Bearer/Basic/garbage → 401 | — | runtime | **VERIFIED** |
| Login проверяет credentials | 2 неверных пароля → 401, без user enumeration | — | runtime | **VERIFIED** |
| Step-up токен не повреждён | 0 / 60 | — | runtime | **VERIFIED (f013e7317)** |
| `exc_info` прикрепляет traceback | живые 4 traceback в логе приложения | 0 | runtime | **VERIFIED (e91fb91fe)** |
| ISO-дата в timestamp сохраняется | `/ready` отдаёт `2026-09-28T15:44:07Z` | — | runtime | **VERIFIED (9a1987f49, 32ef4f246)** |
| `/ready` честно отдаёт 503 | S3 и NATS недоступны в dev_light | — | runtime | **VERIFIED** (fail-closed) |
| `make ci` | exit 0 на содержимом этого SHA | 0 | test | **VERIFIED** (не гоняет тесты) |
| Layers / docstrings / optional-tenant | 0 новых / 0 missing / 123=123 | 0 | static | **VERIFIED** |
| Покрытие 70% | exit 2 | 2 | test | **FALSE** (~52%) |
| `make ci` выполняет тесты | `make/pipelines.mk:22` | — | code | **FALSE** |
| Auth на всех 443 операциях | 12 путей проверены | — | runtime | **PARTIAL** |
| Browser / Playwright | не выполнялся | — | — | **NOT VERIFIED** |
| Контейнерный образ + SBOM | не собирались | — | — | **NOT VERIFIED** |
| Alembic round-trip | падает в config load | — | — | **ENV_FAILURE** |
| Privacy integration (PG/Redis/S3/Qdrant) | нет инфраструктуры | — | — | **ENV_FAILURE** |

---

## 3. Покрытие: ~52% против порога 70%

Два независимых измерения: **52.25%** (полный прогон) и **51.89%**
(прогон, остановленный на ~97%). Расхождение 0.36 п.п. — величина устойчивая.

Чистое измерение не получается из-за памяти, и это **ограничение среды, а не
дефект репозитория**:

```
kernel: Out of memory: Killed process 2155624 ([pytest-xdist r)
        total-vm:10125828kB, anon-rss:6449748kB
```

Каждый воркер pytest-xdist под coverage накапливает ~6 GB; машина — 15 GB.
Воспроизводится одинаково при `-n auto` (10 воркеров на 4 CPU) и при `-n 4`.
Способ получить чистое число: разбить прогон по top-level пакетам и
объединить. Не выполнено.

---

## 4. Невыполненные обязательные проверки

| Проверка | Статус | Причина |
|---|---|---|
| cURL-матрица | **DONE** | этот документ, §1 |
| Перечисление реальных маршрутов | **DONE** | 414 paths / 443 operations |
| OpenAPI описывает аутентификацию | **DONE** | 443/443, 4 схемы |
| Browser / Playwright | NOT VERIFIED | требует запуска браузера; ранее блокировалось пустым `securitySchemes` — теперь разблокировано, но не выполнено |
| Контейнерный образ | NOT VERIFIED | не собирался |
| SBOM | NOT VERIFIED | не генерировался |
| Alembic upgrade/downgrade round-trip | ENV_FAILURE | падает в config load (`redis AuthenticationError`) |
| Privacy integration | ENV_FAILURE | нет инфраструктуры |
| pip-audit / OWASP ZAP / perf-gate | ENV_FAILURE | нет сети / контейнера / приложения |

---

## 5. Прочее, зафиксированное при разведке

- `step-up-request` выдаёт токен **без проверки credentials** — любой
  неаутентифицированный клиент его получает. Это не обход аутентификации
  (login всё равно проверяет пароль), а CSRF/session-guard. Токен не
  одноразовый.
- В логах `environment: 'production'`, хотя профиль `dev_light` задаёт
  `app.environment: "development"`; в префиксе строки при этом
  `[development@...]`.
- Контейнер `/app` на порту 8000 работает с 11 сентября и не соответствует
  ни одному коммиту этого дня.

---

## 6. Файлы evidence

- `HEAD.txt` — SHA, к которому относится каждое утверждение.
- `curl_matrix.txt` — сырой вывод cURL-проверок (7 групп).
- `openapi.json` — спецификация, снята с этого процесса.
- `openapi_report.txt` — агрегаты по спецификации.
