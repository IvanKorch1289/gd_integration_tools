# Release-ready hardening: ЭТАП 0–5 (2026-11-23)

Цикл подготовки релизного кандидата (`gd_integration_tools`). Каждый этап —
с самостоятельным SHA, таблицей находок, списком изменённых файлов, тестами
и кодом выхода, оценкой влияния на безопасность и производительность,
перечнем непроверяемого офлайн, планом отката и следующим шагом.

## Статусы находок

| Статус | Значение |
|---|---|
| `CONFIRMED` | Проблема подтверждена воспроизведением |
| `FIXED` | Подтверждена и устранена коммитом (указан SHA) |
| `FALSE_POSITIVE` | Предположение не подтвердилось проверкой |
| `ENV_BLOCKED` | Проверка невозможна в этом окружении (нет сети/токена/инструмента) |
| `NOT_RUN` | Проверка не выполнялась (с указанием причины) |
| `OWNER_DECISION` | Требуется решение владельца (O1–O6) |

`ENV_BLOCKED` и `NOT_RUN` — **не** успех. «Собрано» ≠ «прошло»: счётчик
тестов, заявленный прогон, порог покрытия и утверждение старого отчёта не
заменяют фактический результат проверки на текущем SHA.

---

## ЭТАП 0. Базовая линия

### 1) SHA до / после

| | SHA |
|---|---|
| До | `a9638db26452b27b364b717a9db8db52a3085280` (= `origin/master`, дерево чистое) |
| После | без изменений (этап только читающий) |

### 2) Что красное и почему

Прогоны обязательных workflow на SHA `a9638db26` (GH API,
`/actions/workflows/{id}/runs` + фильтр по `head_sha`):

| Workflow | Итог | Причина | Статус |
|---|---|---|---|
| `lint.yml` | **failure** | ruff-гейт `src`/`tests` зелёный; красный — 25 ошибок ruff в `tools/` (вне CI-гейта) + mutation-гейт | `CONFIRMED` |
| `test.yml` | **failure** | 15 упавших тестов: 2× `test_api_key_admin_roles_config.py` (хардкод абсолютного пути `/home/user/dev/...`, commit `5a113404c`) + 13× DSN-драйверных (в CI нет extra `db_drivers`: `pyodbc`/`aioodbc`/`pymysql`/`oracledb`) | `CONFIRMED` |
| `type.yml` | success | — | — |
| `security.yml` | **failure** | `uv audit`: 14 advisories + SBOM diff-гейт | `CONFIRMED` → O1 |
| `sbom.yml` | success | — | — |
| `stubs-drift.yml` | success | — | — |
| `image.yml` | **failure** | красный шаг Trivy в image pipeline | `CONFIRMED` → ЭТАП 1 |
| `release-gate.yml` | **failure** | корректно: агрегирует красное (4 из 7 красные) | `CONFIRMED` |

Локальная проверка тех же 15 тестов: **46 passed** (exit 0) — падения
воспроизводятся только в CI-окружении (нет драйверов, другой путь).

### Локальные гейты на базовом SHA

| Гейт | Команда | Exit | Результат |
|---|---|---|---|
| Компиляция | `python -m compileall -q src extensions` | 0 | ок |
| Ruff (`src`,`tests`) | `ruff check src tests` | 0 | All checks passed |
| Ruff (`tools/`) | `ruff check tools` | 1 | 25 ошибок (вне CI-гейта) |
| Слои | `python tools/check_layers.py` | 0 | 0 новых нарушений (файлов 2599, debt 0, contract 3) |
| Сбор тестов | `pytest --collect-only -q` | 0 | 26 036 собрано (на текущем HEAD после ЭТАП 1) |

### Branch protection / rulesets (только чтение)

| Объект | Состояние | Статус |
|---|---|---|
| Branch protection на `master` | **отключено** (404 при запросе) | `OWNER_DECISION` (O4) |
| Rulesets репозитория | `[]` — ни одного ruleset | `OWNER_DECISION` (O4) |
| Required checks | не заданы → «зелёные обязательные workflow» держатся только на соглашении, а не механизмом | `OWNER_DECISION` (O4) |

### 3) Изменённые файлы

Нет (этап читающий).

### 4) Тесты и коды выхода

| Команда | Exit |
|---|---|
| `compileall -q src extensions` | 0 |
| `ruff check src tests` | 0 |
| `ruff check tools` | 1 (25 ошибок) |
| `tools/check_layers.py` | 0 |
| `pytest --collect-only -q` | 0 (26 036 собрано) |
| `pytest tests/unit/core/config/test_api_key_admin_roles_config.py …dsn…` | 0 (46 passed) |

### 5) Влияние на безопасность

Прямых изменений нет. Зафиксировано: обязательных проверок на `master` нет
(branch protection выключена) → «красный merge» технически не запрещён
(O4).

### 6) Влияние на производительность

Нет (изменений нет).

### 7) Что не удалось проверить и почему

| Проверка | Статус | Причина |
|---|---|---|
| Состояние branch protection на других ветках | `NOT_RUN` | проверялся только `master` |
| Квоты/политики организации GHCR | `ENV_BLOCKED` | нет доступа к настройкам организации |
| Реальный Subject сертификата cosign | `ENV_BLOCKED` | нет OIDC-токена и cosign в окружении |

### 8) План отката

Не применим (изменений нет).

### 9) Следующий шаг

ЭТАП 1 — переработка цепочки публикации образа.

---

## ЭТАП 1. Цепочка публикации container-образа

### 1) SHA до / после

| | SHA | Содержание |
|---|---|---|
| До | `a9638db26` | исходная схема `build → scan → sign → push` |
| После | `f34e07a6a` | новая схема: ревью-ветка и ветка публикации |
| После | `ebca48c88` | правки по итогам независимого ревью |

### 2) Находки

| ID | Severity | Что было | Статус |
|---|---|---|---|
| F1 | **MAJOR** | identity сверялся по `https://github.com/.*/.*` — принималась подпись **любого** workflow на github.com | `FIXED` (`f34e07a6a`) |
| F2 | MAJOR | теги (`master`/`latest`/`sha-*`) публиковались **до** скана и подписи: красный verify не мог отозвать уже опубликованный тег | `FIXED` (`f34e07a6a`) |
| F3 | MAJOR | `push` пересобирал образ через buildx → просканированные байты ≠ опубликованные (TOCTOU) | `FIXED` (`f34e07a6a`) |
| F4 | MAJOR | `if: github.event_name != 'pull_request'` пропускал `merge_group` в ветку публикации: временный merge-коммит merge queue получал теги в registry | `FIXED` (`f34e07a6a`) |
| F5 | MINOR | порядок «sign → push» был неисполним: cosign подписывает манифест **в registry** → «no such manifest» | `FIXED` (`f34e07a6a`, порядок push → sign → verify) |
| F6 | MINOR | job-level `permissions` заменяют workflow-level: `sign`/`verify`/`promote` не имели `packages: write/read` → cosign не смог бы записать подпись | `FIXED` (`f34e07a6a`) |
| F7 | MINOR | комментарии и заголовок workflow описывали старую схему | `FIXED` (`f34e07a6a`) |
| F8 | **MAJOR** (ревью-2) | имя образа бралось из `${{ github.repository }}`; владелец `IvanKorch1289` — со смешанным регистром, а docker/distribution требует lowercase («repository name must be lowercase») → ветка публикации упала бы на первом шаге | `FIXED` (`ebca48c88`) |
| F9 | MINOR (ревью-2) | `imagetools create` со значением по умолчанию для одиночного манифеста создаёт **новый** index → digest тега ≠ подписанного digest'а | `FIXED` (`ebca48c88`, `--prefer-index=false`) |
| F10 | MINOR (ревью-2) | триггер `v*.*.*` шире identity-регексп'а (`v[0-9]+\.[0-9]+\.[0-9]+`) → релиз `v1.2.3-rc.1` падал бы на verify | `FIXED` (`ebca48c88`) |
| F11 | MINOR-INFO (ревью-2) | `checkout` был убран из scan-джобов → потеряны fingerprint'ы файлов в SARIF | `FIXED` (`ebca48c88`) |
| F12 | MINOR (ревью-2) | тесты не фиксировали инварианты: триггеры `on:`, права каждого job'а, `outputs.digest`, нормализацию имени, источник promote, RE2-совместимость регексп'а (7 ложно-зелёных мутаций) | `FIXED` (`ebca48c88`, 67 тестов) |
| F13 | — | негативная проверка на чужую подпись | `ENV_BLOCKED` (офлайн нет cosign/OIDC; офлайн-проверка регексп'а реализована) |

### 3) Изменённые файлы

| Файл | Изменение |
|---|---|
| `.github/workflows/image.yml` | переписан: 7 job'ов, две взаимоисключающие ветки, push по digest, promote тегов после verify, нормализация имени образа, якорный identity |
| `tests/unit/deploy/test_image_workflow.py` | переписан: 67 контрактных тестов (было 21) |

### 4) Тесты и коды выхода

| Команда | Exit | Результат |
|---|---|---|
| `pytest tests/unit/deploy/test_image_workflow.py -p no:randomly -q` | 0 | 67 passed |
| `pytest tests/unit/deploy/ tests/unit/tools/test_ci_workflow_failure_modes.py tests/unit/tools/test_ci_workflow_integrity.py -p no:randomly -q` | 0 | 192 passed |
| `ruff check tests/unit/deploy/test_image_workflow.py` | 0 | All checks passed |
| `ruff format --check tests/unit/deploy/test_image_workflow.py` | 0 | formatted |
| `actionlint .github/workflows/image.yml` | — | `NOT_RUN`: actionlint в окружении отсутствует (`command -v actionlint` пусто), установка запрещена правилами проекта |
| мутационная проверка контрактных тестов (10 мутаций) | — | 10/10 обнаружены; `crane tag` (допустимая альтернатива) остаётся зелёным |

### 5) Влияние на безопасность

- Якорный identity: принимается только подпись **этого** репозитория, **этого**
  workflow (`.github/workflows/image.yml`) и допустимого ref; прежний regex
  принимал подпись любого репозитория на github.com.
- Ни один пользовательский тег не появляется в registry до успешного `verify`;
  путь «публикация без проверки подписи» отсутствует (единственный job, выдающий
  теги — `promote`, он зависит от `verify`).
- Сканируется, подписывается и публикуется **один и тот же digest**.
- `merge_group`/`pull_request` ничего не публикуют и не подписывают.
- Права job'ов минимальны (`packages: read/write`, `id-token: write` только
  там, где нужен).

### 6) Влияние на производительность

- Ревью-ветка: сборка одна, скан локальный (как раньше) — регрессии нет.
- Ветка публикации: одна сборка (buildx `push-by-digest=true`) вместо двух
  (было: сборка + пересборка в job `push`); образ не пересобирается → минус
  ~1 полный build на релиз.
- `imagetools create` — копия манифеста (carbon copy), без пересборки слоёв.

### 7) Что не удалось проверить и почему

| Проверка | Статус | Причина |
|---|---|---|
| Реальный Subject сертификата cosign (точный регистр владельца) | `ENV_BLOCKED` | нет OIDC-токена и cosign в окружении; регексп терпим к обоим регистрам (`[Ii][Vv]…`) |
| Негативная проверка на чужую подпись (уровень подписи) | `ENV_BLOCKED` | нет cosign и доступа к registry; реализована офлайн-проверка самого регексп'а |
| `actionlint` | `NOT_RUN` | бинарь отсутствует, установка запрещена |
| Живое поведение GitHub Actions (resolve `needs`, реальные claim'ы OIDC) | `ENV_BLOCKED` | коммиты не запушены (push запрещён правилами проекта) |

### 8) План отката

```bash
git revert ebca48c88 f34e07a6a   # или
git checkout a9638db26 -- .github/workflows/image.yml tests/unit/deploy/test_image_workflow.py
```
Откат возвращает прежнюю схему (с её дефектами: не-якорный identity,
публикация тегов до подписи, merge_group в ветке публикации). Побочных
эффектов нет: изменения затрагивают только CI и его контрактные тесты.

### 9) Следующий шаг

ЭТАП 2 — верификация гипотез (SIGSEGV, PII fast-path, Granian, order-dependence).
