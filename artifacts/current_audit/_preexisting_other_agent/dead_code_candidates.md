# Dead-code / duplicate candidates (протокол: удаление только после доказательства)

## CONFIRMED дубликаты (удаление безопасно, ~1110 LOC)
1. `src/backend/core/services/base_external_api.py` = exact-copy `services/core/base_external_api.py`
   (275 LOC, md5 15930cd9). Канон — services.core (2/2 клиента + прокси). Удалить копию,
   переписать 1 импорт: core/api/__init__.py:170. Условия: нет string-ref, есть shim __init__.
2. `src/backend/dsl/processors/saga_lra_processor/` — legacy-копия пакета:
   state.py+_protocol.py+5 mixin-ов (~811 LOC) никем не импортируются вне пакета;
   __init__ (3 строки) — шим на engine-пакет, его используют тесты. Удалить содержимое,
   оставить шим. (См. также вход 6da43abc8 — уже удалял 452 LOC этого пакета.)

## Мёртвые процессоры (registry, нет route/YAML/string-использований)
- InfraLogWriteProcessor (infra_log.py) — только self+__init__+1 unit-тест.
- FeatureFlagCheckProcessor (feature_flag_check.py) — 0 использований вне модуля.
- collection_mixin.py / request_reply_mixin.py — классы-дубли ВНЕ MRO RouteBuilder,
  живут только в собственных тестах. Удаление после миграции тестов.

## Мёртвый код подтверждённый
- redis_broadcaster.py:310 `_now_utc()` — 0 использований.
- middlewares/admin_audit.py — 0 импортов (заменён audit_log/audit_replay).
- feature_flags.scheduler_backend — флаг без потребителей.
- quotas_service.py — stub-класс (raise в __init__), DI идёт мимо (NoOpBillingFacade).

## FALSE POSITIVES (не удалять)
- Protocol/ABC методы с pass (base repository, logging router) — контракты.
- «Заменяется декоратором» NotImplementedError (11 шт., services/ops/*) — паттерн proxy.
- capability-гейты (claude.py:57 и др.) — fail-fast по дизайну.

## Правило
Каждое удаление: grep import + grep string/YAML + focused tests + полный verify.
