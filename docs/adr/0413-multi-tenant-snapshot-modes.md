# ADR-0413 — Режимы межtenant-снапшота (single-tenant / per-tenant / service-role)

* Статус: Accepted (2026-11-02, волна 23, кластер C3 — роль `BYPASSRLS` для межtenant-снапшота)
* Cycle: 23 (волна 23)
* Связан с:
  - ADR-0409 (контракт «снапшот в пределах одного `tenant_id`; без скоупа — fail-closed»),
  - ADR-0400 (tenant-скоуп снапшота через `set_config('app.tenant_id', …)`),
  - ADR-0393 (`BYPASSRLS`-роль для служебных соединений — эксплуатационное решение владельца БД),
  - ADR-0378 (секреты в настройках — `SecretStr`, маскирование в дампах)
* Затрагивает:
  - `src/backend/core/config/services/snapshot.py`,
  - `src/backend/infrastructure/resilience/snapshot_job.py`,
  - `docs/ops/snapshot-bypassrls-role.md`,
  - `docs/roadmap/OWNER_TASKS.md` (§11),
  - `tests/unit/infrastructure/resilience/test_snapshot_job.py`,
  - `tests/unit/infrastructure/resilience/test_snapshot_job_modes.py` (новый),
  - `.env.example` (`SNAPSHOT_SERVICE_DSN`)

---

## Контекст

ADR-0409 закрыл «тихий 0 строк» в снимке: снапшот покрывает ровно один
`tenant_id`, скоуп обязателен, его отсутствие — `SnapshotTenantScopeError`
(fail-closed), файл снимка при отказе не затирается.

Там же зафиксировано ограничение: **межtenant-снапшота в ядре нет**, потому
что перечислить tenant'ы нечем — реестра tenant'ов в БД нет, а
`SELECT DISTINCT tenant_id` под RLS видит только текущего tenant'а. Единственный
известный путь — служебная роль с `BYPASSRLS` (ADR-0393), которая является
эксплуатационным решением владельца БД.

Owner-задача (OWNER_TASKS §11) формулировала это как «нужна роль `BYPASSRLS`
+ DSN, либо per-tenant job'ы по одному на тенанта». Кодовая часть была
невозможна без явного решения: не было ни конфигурационного ключа (какой
режим вообще включён), ни безопасной альтернативы `BYPASSRLS`, ни
fail-closed поведения для «явной настройки не задано».

Дополнительный риск, который нельзя оставлять без проверки: служебный DSN
роли **без** `BYPASSRLS` (или с отозванным `BYPASSRLS`) вернул бы 0 строк
**без ошибки** — ровно тот «тихий ноль», который ADR-0409 уже устранял для
tenant-скоупа.

## Решение

### 1. Конфигурация: явный режим (модель, не «сырые» YAML-ключи)

В существующую модель `SnapshotSettings` (`core/config/services/snapshot.py`,
yaml-группа `snapshot`, env-префикс `SNAPSHOT_`) добавлены:

* `mode: Literal["single-tenant", "per-tenant", "service-role"]` — режим
  выгрузки, по умолчанию `single-tenant` (текущее поведение);
* `tenants: list[str]` — явный список tenant'ов для режима `per-tenant`;
* `service_dsn: SecretStr | None` — DSN служебной роли с `BYPASSRLS` для
  режима `service-role` (секрет → `SecretStr`, пароль маскируется в дампах,
  ADR-0378; переменная `SNAPSHOT_SERVICE_DSN` — в `.env.example`).

Неизвестное значение `mode` отвергается валидатором pydantic при загрузке
конфигурации, а не «молча деградирует» в другой режим.

### 2. Три режима

| Режим | Скоуп | Явная настройка | Fail-closed при отсутствии настройки |
|---|---|---|---|
| `single-tenant` | `set_config('app.tenant_id', …)` для одного tenant'а | — | `SnapshotTenantScopeError` (ADR-0409, без изменений) |
| `per-tenant` | свой `set_config('app.tenant_id', …)` для каждого tenant'а из `snapshot.tenants` | список tenant'ов | `SnapshotModeError`, снимок не пишется |
| `service-role` | чтение под `BYPASSRLS` (tenant-скоуп не выставляется) | `service_dsn` | `SnapshotModeError`, снимок не пишется |

`per-tenant` — **безопасная альтернатива** `BYPASSRLS`: RLS остаётся
включённым, изоляция не обходится, читаются только перечисленные tenant'ы.
`service-role` — единственный режим, который обходит RLS; он требует
явного DSN и проверки `BYPASSRLS` у роли.

### 3. «Нет тихих 0 строк» во всех режимах

* `service-role`: перед выборкой выполняется проверка
  `SELECT COALESCE(bool_or(rolbypassrls), false) …` (роль соединения +
  роли, в которые она входит) — нет `BYPASSRLS` → `SnapshotModeError`
  **до** выборки, снимок не пишется;
* `per-tenant` / `service-role`: пустой результат (0 строк по всем
  таблицам) — `SnapshotModeError`, проверка выполняется **до** записи в
  SQLite, поэтому предыдущий валидный снимок сохраняется;
* `per-tenant`: пустая таблица по конкретному tenant'у — WARNING с
  указанием tenant'а (не молчание);
* `single-tenant`: поведение ADR-0409 сохранено (0 строк → WARNING).

### 4. Эксплуатационный артефакт

`docs/ops/snapshot-bypassrls-role.md`: SQL создания роли
(`NOLOGIN` + `BYPASSRLS` + `GRANT USAGE/SELECT` только на таблицы
снимка), шаблон DSN (sync-драйвер `psycopg`), проверки (`pg_roles`,
`information_schema.role_table_grants`, `pg_policies`), откат, критерии
приёмки и явное предупреждение о риске: роль обходит изоляцию tenant'ов
и используется **только** для read-only служебного снимка, никогда — для
подключения приложения.

Роль не создаётся миграцией Alembic: `CREATE ROLE … BYPASSRLS` требует
прав `CREATEROLE` у DBA, а job'ы миграций выполняются от имени
приложения. Поэтому артефакт — процедура в `docs/ops/`, а не код в
`infrastructure/database/migrations/`.

### 5. Инварианты, зафиксированные тестами

* `single-tenant` — прежнее поведение не изменилось (регрессия);
* `per-tenant` — для каждого tenant'а из списка выставляется свой
  `SET app.tenant_id`, строки суммируются;
* `per-tenant` без списка / `service-role` без DSN / неизвестный режим —
  ошибка **до** создания SQLite-движка (файл снимка не тронут);
* `service-role` — проверка `BYPASSRLS` выполняется до выборки; роль без
  `BYPASSRLS` → ошибка, выборка не выполняется;
* пустой результат в межtenant-режимах → ошибка, `DELETE`/`INSERT` не
  вызываются (снимок не затирается пустым);
* значения режимов в конфиг-модели и в job'е совпадают (единый источник
  истины).

## Альтернативы (отклонённые)

1. **Оставить только `single-tenant`, закрыть задачу документацией.**
   Отклонено: owner-задача требовала кодовой части — явного режима и
   безопасной альтернативы `BYPASSRLS`; без них «нужна роль» остаётся
   неисполняемым требованием.
2. **Автоматически перебирать tenant'ов через `SELECT DISTINCT tenant_id`.**
   Отклонено: под RLS видны только строки текущего tenant'а (ADR-0409) —
   перебор всё равно даст 0 строк, то есть тот же «тихий ноль».
3. **Режим `per-tenant` с перебором всех tenant'ов из файла конфигурации
   приложения.** Отклонено: список должен быть явным и проверяемым;
   неявный источник tenant'ов вернул бы к «тихому нулю» при опечатке.
4. **Служебная роль в ядре (создаётся миграцией).** Отклонено: `CREATE ROLE
   … BYPASSRLS` требует прав `CREATEROLE`, которых у приложения нет;
   выдача роли — эксплуатационное решение владельца БД (ADR-0393).
5. **Автоматически повышать привилегии при подключении (SET ROLE).**
   Отклонено: требует, чтобы у app-пользователя был `SET ROLE` на
   привилегированную роль — это ровно тот доступ, которого мы избегаем.
6. **Не проверять `BYPASSRLS` у роли (полагаться на DSN).** Отклонено:
   DSN без `BYPASSRLS` даёт 0 строк без ошибки — «тихий ноль», ради
   устранения которого ADR-0409 и писался.
7. **Молча деградировать при неизвестном `mode` в `single-tenant`.**
   Отклонено: опечатка в конфигурации выглядела бы как «снимок есть, но
   не тот»; режим отвергается валидатором.

## Последствия

* **Позитивные:**
  - межtenant-снапшот стал настраиваемым кодом, а не только
    эксплуатационной запиской; безопасный режим (`per-tenant`) не требует
    расширения прав;
  - «тихие 0 строк» невозможны ни в одном режиме: пустой результат и
    отсутствие `BYPASSRLS` — явные ошибки, файл снимка не затирается;
  - процедура выдачи роли (SQL + DSN + проверки + откат + критерии
    приёмки) оформлена и доступна оператору;
  - контракт ADR-0409 не сломан: default — `single-tenant`, поведение
    single-tenant не изменилось.
* **Ограничения / вне зоны (требует владельца):**
  - **выдача роли `BYPASSRLS` и настройка DSN** — эксплуатационное решение
    владельца БД (ADR-0393); ядро не может выдать себе права
    (`docs/ops/snapshot-bypassrls-role.md`);
  - **потребитель снимка** (`infrastructure/resilience/components/database_chain.py`,
    вне зоны кластера) не проверяет, что снимок принадлежит текущему
    tenant'у: при межtenant-снимке fallback отдаст данные всех tenant'ов
    подряд. Требуется guard на стороне потребителя (owner-задача);
  - **в `per-tenant` снимок попадают все перечисленные tenant'ы** — это
    осознанный компромисс: отдельный файл на tenant потребовал бы
    изменения потребителя снимка;
  - `docs/adr/INDEX.md` не обновлялся (по условию задачи) — индекс
    генерируется скриптом `tools/generate_adr_index.py` (CI: `adr-sync.yml`).

## Проверка

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/resilience/test_snapshot_job.py \
  tests/unit/infrastructure/resilience/test_snapshot_job_modes.py -q

.venv/bin/python tools/config_audit.py --scope orphans
.venv/bin/python tools/config_audit.py --scope missing
.venv/bin/python tools/check_env_example.py --secrets-only
.venv/bin/python tools/check_layers.py --strict
.venv/bin/python tools/checks/mypy_budget.py
```

## Связи

* [ADR-0409](../adr/0409-multi-tenant-snapshot-and-credit-pipeline-agents.md) —
  контракт «снапшот в пределах одного tenant_id; без скоупа — fail-closed».
* [ADR-0400](../adr/0400-snapshot-rls-graphql-hot-reload-and-bls-gate.md) —
  tenant-скоуп снапшота через `set_config('app.tenant_id', …)`.
* [ADR-0393](../adr/0393-db-capability-gate-and-rpa-authorization.md) —
  `BYPASSRLS`-роль для служебных соединений (эксплуатационное решение).
* [ADR-0378](../adr/0378-secret-masking-and-undeclared-env-secrets.md) —
  секреты в настройках (`SecretStr`), маскирование пароля в дампах.
* `docs/ops/snapshot-bypassrls-role.md` — процедура выдачи роли и DSN.
* `docs/roadmap/OWNER_TASKS.md` §11 — статус owner-задачи.
