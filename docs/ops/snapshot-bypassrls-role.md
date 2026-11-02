# Межtenant-снапшот: служебная роль `BYPASSRLS` и режимы выгрузки

> Процедура для владельца БД. ADR-0413 (`docs/adr/0413-multi-tenant-snapshot-modes.md`),
> контракт скоупа — ADR-0409, роль как эксплуатационное решение — ADR-0393.

## Назначение

Snapshot job (`src/backend/infrastructure/resilience/snapshot_job.py`)
периодически реплицирует read-only critical таблицы из PostgreSQL в
SQLite-файл `var/db/snapshot.sqlite`, который используется
`ResilienceCoordinator` как fallback компонента `db_main`.

Таблицы `users` / `orders` / `orderkinds` (и остальные из
`snapshot.tables`) защищены PostgreSQL-RLS:
политика `tenant_id = current_setting('app.tenant_id', true)`.
Без выставленного `app.tenant_id` выборка возвращает **0 строк без
ошибки** — «тихая» потеря fallback'а.

Реестра tenant'ов в БД нет, а `SELECT DISTINCT tenant_id` под RLS видит
только текущего tenant'а. Поэтому межtenant-снапшот возможен двумя
способами, и оба должны быть включены **явно**.

## ⚠️ Риск: роль `BYPASSRLS` обходит изоляцию tenant'ов

Роль с `BYPASSRLS` **нарушает механизм изоляции tenant'ов**: она читает
строки всех tenant'ов без фильтра по `app.tenant_id`. Утечка такого
доступа — чтение данных чужого tenant'а из привилегированного
подключения.

Поэтому:

* роль — **только** для read-only служебного снимка, **никогда** для
  подключения приложения, миграций, job'ов приложения или ручных
  запросов аналитиков;
* у роли **нет** прав на запись: `GRANT SELECT` + `NOLOGIN` (вход
  запрещён — подключается только конкретный пользователь, которому
  роль выдана);
* DSN хранится как секрет (`SNAPSHOT_SERVICE_DSN`), в дампах конфигурации
  пароль маскируется;
* перед каждой выборкой job проверяет, что у роли **действительно** есть
  `BYPASSRLS` (`_assert_bypassrls`), иначе — fail-closed с ошибкой, а не
  тихий пустой снимок.

**Предпочитайте `per-tenant`:** этот режим не обходит RLS вообще — для
каждого tenant'а из явного списка выставляется собственный
`app.tenant_id`. К `BYPASSRLS` прибегайте только когда список tenant'ов
неизвестен или меняется динамически.

## Когда что применять

| Ситуация | Режим | Что нужно от владельца |
|---|---|---|
| Fallback нужен только одному tenant'у (по умолчанию) | `single-tenant` | ничего (текущее поведение, ADR-0409) |
| Fallback нужен конечному списку tenant'ов | `per-tenant` | список tenant'ов в конфигурации (`snapshot.tenants`) |
| Fallback нужен всем tenant'ам, список неизвестен/меняется | `service-role` | роль `BYPASSRLS` + отдельный DSN + пароль в секрет-хранилище |

Оба межtenant-режима **fail-closed**: без явной настройки (пустой список
tenant'ов / отсутствие DSN) снимок не пишется, предыдущий валидный снимок
сохраняется, ошибка уходит в лог и в `snapshot_sync_errors_total`.

## Режим 1 (рекомендуемый): `per-tenant` — без `BYPASSRLS`

Ничего выдавать в БД не нужно. Достаточно явного списка:

```yaml
# config_profiles/<profile>.yml
snapshot:
  mode: per-tenant
  tenants:
    - tenant-a
    - tenant-b
```

или через окружение:

```bash
SNAPSHOT_MODE=per-tenant
SNAPSHOT_TENANTS='["tenant-a","tenant-b"]'
```

Job для каждого tenant'а выставляет `set_config('app.tenant_id', …, true)`
(transaction-local) и читает только его строки; в SQLite-снимок попадают
все перечисленные tenant'ы (в строках сохраняется колонка `tenant_id`).

## Режим 2: `service-role` — роль с `BYPASSRLS`

### 1. Создание роли и логина

Выполняет **владелец БД** (нужны права `CREATEROLE` / `CREATEDB` не
требуются). Роль — `NOLOGIN`; вход — отдельный пользователь.

```sql
-- 1.1. Служебная роль: только чтение, обход RLS, вход запрещён.
CREATE ROLE snapshot_service NOLOGIN BYPASSRLS;

-- 1.2. Логин для подключения (пароль — из секрет-хранилища, не в репозитории).
CREATE ROLE snapshot_service_login LOGIN PASSWORD '<password-from-vault>';

-- 1.3. Логин наследует права служебной роли (BYPASSRLS наследуется участниками).
GRANT snapshot_service TO snapshot_service_login;
```

### 2. Минимальные гранты (только SELECT на таблицы снимка)

```sql
GRANT USAGE ON SCHEMA public TO snapshot_service;

GRANT SELECT ON TABLE
    orderkinds,
    users,
    orders,
    certs,
    cert_history
TO snapshot_service;

-- ВАЖНО: никаких INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES и никакого
-- GRANT на схему public целиком (public уже имеет CREATE — отзыв «CREATE
-- on SCHEMA public» у роли выполняется отдельно, см. п. 5).
```

Список таблиц должен совпадать с `snapshot.tables` в
`config_profiles/base.yml` — иначе часть данных не попадёт в снимок
(см. §Проверка).

Если в установке есть и другие tenant-таблицы под RLS — их можно
добавить в `GRANT SELECT`, но **только** те, что реально нужны fallback'у.

### 3. DSN

Формат — **sync**-драйвер (snapshot job работает в sync-режиме):

```text
postgresql+psycopg://snapshot_service_login:<password>@<pg-host>:5432/<db-name>
```

Переменная окружения (секрет — в Vault/`.env` приложения, не в YAML):

```bash
SNAPSHOT_MODE=service-role
SNAPSHOT_SERVICE_DSN=postgresql+psycopg://snapshot_service_login:<password>@<pg-host>:5432/<db-name>
```

В YAML-профиле секреты не хранятся (`tools/config_audit.py --scope missing`),
поэтому `service_dsn` задаётся только через env/Vault/Consul.

### 4. Проверка перед включением режима

```sql
-- 4.1. Роль действительно обходит RLS?
SELECT r.rolname, r.rolbypassrls
FROM pg_roles r
WHERE r.rolname IN ('snapshot_service', 'snapshot_service_login');

-- 4.2. У пользователя подключения есть BYPASSRLS (напрямую или через роль)?
SELECT current_user,
       COALESCE(bool_or(r.rolbypassrls), false) AS has_bypassrls
FROM pg_roles r
WHERE r.rolname = current_user
   OR pg_has_role(current_user, r.oid, 'MEMBER')
GROUP BY current_user;

-- 4.3. Гранты — только SELECT?
SELECT table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'snapshot_service'
ORDER BY table_name, privilege_type;

-- 4.4. Политики RLS на месте (ожидаемо, что роль их обходит):
SELECT tablename, policyname, cmd FROM pg_policies
WHERE schemaname = 'public' ORDER BY tablename;
```

Проверка из job'а (до выборки) — `SELECT COALESCE(bool_or(rolbypassrls),
false) ...` — вернёт `false`, если роль настроена неверно: job упадёт с
`SnapshotModeError` и **не** запишет пустой снимок.

### 5. Отзыв лишних прав (рекомендуется)

```sql
-- Убрать неявное право CREATE у роли на схему public (PostgreSQL < 15).
REVOKE CREATE ON SCHEMA public FROM snapshot_service;
```

## Откат

```sql
-- 5.1. Отозвать членство в служебной роли.
REVOKE snapshot_service FROM snapshot_service_login;

-- 5.2. Удалить логин (доступ к БД через него прекращается).
DROP ROLE snapshot_service_login;

-- 5.3. Удалить служебную роль.
DROP ROLE snapshot_service;
```

В приложении: `SNAPSHOT_MODE=single-tenant` (или `per-tenant`) и
удаление `SNAPSHOT_SERVICE_DSN` из секрет-хранилища.

## Критерии приёмки (для владельца)

1. Роль создана: `NOLOGIN`, `BYPASSRLS`, `GRANT SELECT` ровно на таблицы
   из `snapshot.tables`; прав на запись нет.
2. `SNAPSHOT_SERVICE_DSN` задан в секрет-хранилище; в YAML и репозитории
   его нет.
3. `snapshot.mode=service-role`; job `snapshot_*` в логах показывает
   ненулевое число строк по каждой таблице снимка (`snapshot_rows_total`).
4. При намеренном отзыве `BYPASSRLS` job падает с `SnapshotModeError`
   (fail-closed), а снимок **не** перезаписывается пустым.
5. RLS-политики остальных (не служебных) пользователей не изменены —
   `pg_policies` совпадает с состоянием до выдачи роли.

## См. также

- ADR-0413 — режимы межtenant-снапшота (контракт и реализация).
- ADR-0409 — контракт «снапшот в пределах одного tenant_id; без скоупа —
  fail-closed».
- ADR-0393 — `BYPASSRLS`-роль для служебных соединений (эксплуатационное
  решение владельца БД).
- ADR-0400 — tenant-скоуп снапшота через `set_config('app.tenant_id', …)`.
- `src/backend/core/config/services/snapshot.py` — модель настроек
  (`mode`, `tenants`, `service_dsn`).
