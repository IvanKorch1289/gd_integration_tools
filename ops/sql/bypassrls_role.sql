-- Роль БД для межtenant-снапшота (ADR-0455, чек-лист инфраструктуры §10).
--
-- Назначение: снапшот-джоб (`infrastructure/resilience/snapshot_job.py`)
-- читает таблицы нескольких tenant'ов подряд. В PostgreSQL это требует
-- BYPASSRLS (или владельца таблиц): политика RLS
-- `tenant_id = current_setting('app.tenant_id', true)` без выставленного
-- tenant'а возвращает 0 строк без ошибки — «тихая» потеря fallback'а.
--
-- Канон процедуры — `docs/ops/snapshot-bypassrls-role.md` (ADR-0413/0409);
-- этот файл — исполняемая версия той же процедуры (идемпотентная).
--
-- Безопасность:
--   * служебная роль без LOGIN — вход только через отдельный логин;
--   * BYPASSRLS — на уровне роли, не у суперпользователя;
--   * права только на чтение (SELECT) конкретных таблиц, не ALL;
--   * пароль не хранится в репозитории (задаётся переменной окружения).
--
-- Применение (пароль и имя БД — из секрет-хранилища/окружения):
--   psql -v snap_password="$SNAP_DB_PASSWORD" -v snapshots_db=appdb \
--        -f ops/sql/bypassrls_role.sql
--
-- Без `snap_password` пароль логина не меняется (CREATE ROLE ... LOGIN без
-- пароля — вход по сертификату/peer, как и задумано для service-подключения).

\set ON_ERROR_STOP on

-- Значения по умолчанию: psql требует, чтобы переменная была определена,
-- даже если её передача не планировалась.
\if :{?snap_password}
\else
  \set snap_password ''
\endif
\if :{?snapshots_db}
\else
  \set snapshots_db postgres
\endif

-- 1) Роли. CREATE ROLE — только если роли ещё нет; атрибуты приводим к
--    канону при каждом применении (идемпотентно).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'snapshot_service') THEN
        CREATE ROLE snapshot_service NOLOGIN BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'snapshot_service_login') THEN
        CREATE ROLE snapshot_service_login LOGIN;
    END IF;
END
$$;

ALTER ROLE snapshot_service NOLOGIN BYPASSRLS;
ALTER ROLE snapshot_service_login LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

-- 2) Логин наследует права служебной роли (BYPASSRLS наследуется участниками).
GRANT snapshot_service TO snapshot_service_login;

-- 3) Пароль логина — только из внешнего секрета.
SELECT length(:'snap_password') > 0 AS has_snap_password \gset
\if :has_snap_password
  ALTER ROLE snapshot_service_login PASSWORD :'snap_password';
\else
  \echo 'NOTICE: snap_password не передан — пароль snapshot_service_login не изменён'
\endif

-- 4) Минимальные гранты: CONNECT (логину) + USAGE на схеме (служебной роли).
GRANT CONNECT ON DATABASE :"snapshots_db" TO snapshot_service_login;
GRANT USAGE ON SCHEMA public TO snapshot_service;

-- 5) SELECT на таблицы снимка (список — `snapshot.tables` профиля:
--    orderkinds, users, orders, certs, cert_history). Таблицы, которых нет
--    в конкретной установке, пропускаются с NOTICE — скрипт остаётся
--    применимым на неполных схемах.
DO $$
DECLARE
    tbl text;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['orderkinds', 'users', 'orders', 'certs', 'cert_history']
    LOOP
        IF to_regclass('public.' || tbl) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT ON TABLE public.%I TO snapshot_service', tbl);
        ELSE
            RAISE NOTICE 'таблица public.% отсутствует — грант пропущен', tbl;
        END IF;
    END LOOP;
END
$$;

-- ВАЖНО: роль НЕ выдаётся приложению. Приложение работает под своей ролью
-- без BYPASSRLS; переключение выполняет только снапшот-джоб
-- (`snapshot.service_dsn` / env `SNAPSHOT_SERVICE_DSN`).
