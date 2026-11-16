-- Роль БД для межtenant-снапшота (ADR-0455, чек-лист инфраструктуры §10).
--
-- Назначение: снапшот-джоб читает таблицы нескольких tenant'ов подряд.
-- В PostgreSQL это требует BYPASSRLS (или владельца таблиц). Роль создаётся
-- вручную DBA, выдаётся ТОЛЬКО сервису снапшота и НЕ используется
-- приложением.
--
-- Безопасность:
--   * роль без LOGIN — вход только через SET ROLE (service-подключение);
--   * BYPASSRLS — только на уровне роли, не у суперпользователя;
--   * права выдаются на чтение (SELECT) конкретных таблиц, не ALL;
--   * пароль не хранится в репозитории (задаётся переменной окружения).
--
-- Применение (заменить <snapshots_db> и задать пароль через psql-переменную):
--   psql -v snap_password="$SNAP_DB_PASSWORD" -f ops/sql/bypassrls_role.sql

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gd_snapshot_reader') THEN
        CREATE ROLE gd_snapshot_reader NOLOGIN BYPASSRLS;
    END IF;
END
$$;

-- Аутентификация: только через внешний секрет (service-подключение + SET ROLE).
ALTER ROLE gd_snapshot_reader PASSWORD :'snap_password';

-- Чтение tenant-aware таблиц (список — из канона core/tenancy/tenant_tables.py).
GRANT CONNECT ON DATABASE :"snapshots_db" TO gd_snapshot_reader;
GRANT USAGE ON SCHEMA public TO gd_snapshot_reader;
GRANT SELECT ON TABLE public.orders, public.users, public.files, public.orderkinds
    TO gd_snapshot_reader;

-- ВАЖНО: роль НЕ выдаётся приложению. Приложение работает под своей ролью
-- без BYPASSRLS; переключение выполняет только снапшот-джоб.
