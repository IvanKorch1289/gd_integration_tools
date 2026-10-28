# ADR-0361 — Семантика `required_capability` у DSL-процессоров: фактический deny-all и план починки

* Статус: ACCEPTED (2026-10-27, cycle 172, Wave 13 — решения Q14 + Q15)
* Cycle: 172
* Дата: 2026-10-27
- **Затрагивает**: `src/backend/dsl/engine/processors/base.py`,
  `src/backend/core/security/connector_auth.py`,
  `src/backend/services/authorization/facade.py`,
  `src/backend/core/security/authorization_gateway/__init__.py`
- **Связан с**: ADR-0358 (allowlist файловых путей), ADR-0359 (канонический
  SQL-guard и fail-closed flag для `infra_db_query`),
  ADR-0284 (§1.1 — governance: изменение семантики авторизации = отдельный ADR),
  ADR-0335 (гейт unsafe-defaults)

## Контекст

### Что декларируется

`BaseProcessor.required_capability` (`src/backend/dsl/engine/processors/base.py:46`)
— классовый атрибут «имя capability для auth-gate». Если он задан,
`BaseProcessor.auth_check` (`base.py:74-145`) обязан проверить его **до**
выполнения шага и вернуть `False` при отказе (`base.py:101-102` — при
`None` проверка пропускается; `base.py:135-140` — deny ставит
`exchange.set_error(...)` + `exchange.stop()`).

В `src/backend` **72 класса** объявляют непустой `required_capability`
(70 — процессоры в `src/backend/dsl/engine/processors/`, 2 — search-провайдера
в `src/backend/dsl/engine/providers_search/`); из них **59 реально вызывают
`await self.auth_check(...)`** — именно эти отказывают в рантайме.
Ещё **16 коннекторов** помечены `@require_capability(...)`
(`src/backend/infrastructure/sinks/*.py`, `src/backend/infrastructure/sources/webhook.py`,
`src/backend/infrastructure/messaging/dlq/*.py`) и идут по **тому же** пути
проверки (`connector_auth.py:110-117` → `facade.check_principal`).

### Фактический путь проверки (sync-policy)

```
BaseProcessor.auth_check                     base.py:74-145
  → check_source_capability                  core/security/connector_auth.py:154-233
      → AuthorizationFacade.check_principal  services/authorization/facade.py:281-307
          → AuthorizationFacade.check        services/authorization/facade.py:457-474
              → AuthorizationGateway.check   core/security/authorization_gateway/__init__.py:262-317  (sync)
```

`AuthorizationGateway.check` (`authorization_gateway/__init__.py:262-317`) —
**единственный allow-источник** — exact in-memory policy
`(subject, action, resource)`:

* `authorization_gateway/__init__.py:286-289` — точный lookup в
  `self._in_memory_policies`; иначе — падение дальше;
* `authorization_gateway/__init__.py:297-303` — `_casbin_check(...)`;
* `authorization_gateway/__init__.py:305-314` — `_opa_check(...)`;
* `authorization_gateway/__init__.py:316-317` — **default deny**.

Оба sync-хука — **мёртвые**. `_casbin_check`
(`authorization_gateway/__init__.py:377-385`) вызывает
`CasbinMixin._casbin_check` только если `hasattr(CasbinMixin, "_casbin_check")`,
но `casbin_mixin.py` объявляет только `casbin_step` (`casbin_mixin.py:17`) —
характеристика `False`, хук возвращает `None`. Аналогично `_opa_check`
(`authorization_gateway/__init__.py:387-395`) vs `opa_mixin.py:17` (`opa_step`).
Casbin/OPA существуют только как **async** `casbin_step`/`opa_step`, которые
вызываются из `authorize()` (`authorization_gateway/__init__.py:127`,
цикл по политикам — `authorization_gateway/__init__.py:190`), а не из
sync-`check()`.

`CapabilityGate.check` (`core/security/capabilities/gate/check_mixin.py:62`)
в этом пути **не вызывается**: `_capability_gateway.check(...)` есть только в
async-`authorize()` (`authorization_gateway/__init__.py:171`).

In-memory policy в проде **не заполняется**: `AuthorizationGateway.add_policy`
(`authorization_gateway/__init__.py:319-344`) имеет 0 production-callers —
единственная ссылка на него — обёртка `AuthorizationFacade.add_policy`
(`services/authorization/facade.py:476-486`), которую никто в `src/`,
`extensions/`, `routes/`, `plugins/` не зовёт.

### Отдельный app-level gateway

Composition root поднимает **другой** экземпляр `AuthorizationGateway` —
`src/backend/plugins/composition/di.py:221-224` — с цепочкой OPA/Casbin-политик
(`di.py:151-198`), заполненной только при `policy.engine_enabled=True`
(`di.py:155`). `AuthorizationFacade.gateway` (`services/authorization/facade.py:96-113`)
поднимает **свой** экземпляр без этих политик. Это **разные объекты**:
даже если OPA/Casbin сконфигурированы и подняты, sync-путь `auth_check` их
не видит.

### Runtime-пробник (воспроизведён 2026-10-27)

Логика пробника (вынесена в `/tmp`, production-код не менялся):

```python
proc = FileListProcessor()            # required_capability = "rpa.file.list"
exchange = Exchange()
allowed = await proc.auth_check(exchange, action="read", principal="anonymous")
decision = await get_authorization_facade().check_principal(
    principal="anonymous", required_action="read", required_resource="rpa.file.list",
)
```

Фактический вывод:

```
source_capability_denied: capability=rpa.file.list action=read principal=anonymous
                          tenant=None reason=policy denied: read
auth_check allowed = False
exchange.error = file_list: capability 'rpa.file.list' denied
decision: allowed=False method=principal reason='policy denied: read'
```

**Контрольный эксперимент** (тот же процесс, тот же principal):

```python
facade.add_policy("anonymous", "read", "rpa.file.list", "allow")
# → decision: allowed=True method=principal reason=''
# → auth_check after add_policy allowed = True
```

Вывод: deny вызван **отсутствием policy**, а не логикой capability-гейта.
Как только exact in-memory policy появляется, тот же самый путь даёт allow.

### Следствие

Фактический результат: **`auth_check` → deny для ЛЮБОГО `required_capability`**.
59 процессоров и 16 коннекторов в проде отказывают на ровном месте —
это P0-дефект доступности, а не дефект конфигурации.

## Решение

### (а) Не расширять capability-охват до починки пути

`required_capability` **не добавляется** новым процессам до починки пути
(иначе процессор станет нерабочим целиком). Это зафиксировано в коде
прямым комментарием: `src/backend/dsl/engine/processors/db_query_external.py:108-115`
— «`required_capability` намеренно НЕ задан … в текущем рантайме
`BaseProcessor.auth_check` для ЛЮБОГО `required_capability` возвращает deny».

### (б) В этом цикле — доменные guard'ы вместо capability-барьеров

Capability-барьеры в этом цикле заменены на **независимые доменные guard'ы**:
канонический SQL-guard для DSL-процессоров и fail-closed flag для
`infra_db_query` (ADR-0359) и **allowlist файловых путей** (ADR-0358). Они
не зависят от политик авторизации и потому работают при любом состоянии
policy-цепочки.

### (в) Починка пути — отдельная задача с отдельным ADR

Кандидаты (каждый меняет семантику авторизации → по правилу ADR-0284 §1.1
требует отдельного ADR и назначенного владельца):

1. **Единый gateway** — использовать app-level gateway
   (`plugins/composition/di.py:221-224`, с OPA/Casbin) в processor-пути;
2. **Sync-реализация Casbin/OPA-хуков** — добавить `_casbin_check`/`_opa_check`
   в соответствующие mixin'ы, чтобы sync-`check()` увидел policy-движки;
3. **Маппинг principal → plugin** — чтобы `CapabilityGate.check`
   (`capabilities/gate/check_mixin.py:62`) вызывался в sync-пути.

Выбор варианта — вне scope этого ADR.

### (г) Честная маркировка до починки

Capability-декларации в `@processor(capabilities=...)` остаются
**метаданными** (LSP/линтер/JSON-схема `x-gd-capabilities`), а не
работающим барьером. Чтобы долг не рос, введён гейт
`tools/check_decorative_capabilities.py` с baseline
`tools/check_decorative_capabilities_allowlist.txt`: **45 декоративных
деклараций** зафиксированы как известный долг, новые — падают с exit 1
(проверено запуском гейта: «Декоративные capability-декларации: 0 новых
(всего в долге: 45; allowlist: 45)»). CI-шаг
«Decorative processor capabilities gate» — `.github/workflows/lint.yml:117-120`.

Ограничение базовой декларации: `CORE_CAPABILITIES`
(`src/backend/core/security/capabilities/core_declarations.py:44-144`) —
**73 уникальных capability** ядра; это декларация, а не разрешение доступа.

## Альтернативы (отклонённые)

### (а) Добавить `CapabilityGate.check` в sync-путь как fallback — отклонено

Маппинг principal → plugin в проекте не определён: `check()` принимает
`(subject, action, resource)`, а `CapabilityGate.check` — `(plugin, capability,
requested_scope)` (`capabilities/gate/check_mixin.py:62`). Без явного
маппинга fallback либо ничего не проверяет, либо открывает доступ к
73 объявленным core-capability. Риск «открыть доступ» перевешивает
пользу от «наконец-то работающего гейта».

### (б) Заполнить in-memory policy на старте из baseline-деклараций — отклонено

Тот же риск, что и в (а), только в другой обёртке: baseline-декларации
(`core_declarations.py:44-144`) превратились бы в allow для всех
исполнителей, а объём policy совпал бы с полным набором core-capability.
Плюс policy-строки, выгруженные в стартовый лог, раскрывают модель доступа.

### (в) Оставить как есть, без фиксации — отклонено

Дефект не зафиксирован → следующий разработчик добавит
`required_capability` ещё одному процессору и получит ещё один
неработающий шаг. Фиксация честной маркировки (г) + гейт (ADR-0361-гейт)
останавливает рост долга до починки.

## Последствия

### Позитивные

- Поведение `required_capability` задокументировано и **проверяемо**
  (runtime-пробник + контрольный эксперимент с `add_policy`).
- Новым процессам нельзя случайно «включить» неработающий capability-барьер
  (решение (а) + комментарий в `db_query_external.py:108-115`).
- Долг по декоративным декларациям зафиксирован (45 записей) и не растёт.
- Реальные защиты этого цикла (доменные guard'ы, allowlist путей) не зависят
  от policy-цепочки и потому работают.

### Негативные

- **59 процессоров и 16 коннекторов фактически отказывают в рантайме.**
  Это P0-дефект доступности, который **не закрывается этим циклом** →
  owner-задача (см. Followup).
- Capability-декларации в `@processor(capabilities=...)` по-прежнему
  декоративны: LSP/схемы показывают capability, которой нет в рантайме.
  Компенсировано гейтом и настоящим ADR.

### Нейтрально

- Sync-`check()` и async-`authorize()` продолжают использовать разные
  источники решений. Это расхождение зафиксировано как кандидат на
  отдельный ADR, а не исправлено в этом цикле.

## Проверка после реализации

```bash
# 1. Runtime-пробник: deny для ЛЮБОГО required_capability
uv run python /tmp/adr0361_probe.py
# ожидаемо: auth_check allowed = False; reason='policy denied: read'

# 2. Контрольный эксперимент: после add_policy — allow
#    (ожидаемо: auth_check after add_policy allowed = True)

# 3. Гейт декоративных деклараций не растёт
uv run python tools/check_decorative_capabilities.py --ci
# ожидаемо: 0 новых (всего в долге: 45)

# 4. Слой-контроль
uv run python tools/check_layers.py --strict
```

## Статус реализации

**Cycle 172 (Wave 13).** Реализовано: решения (а), (б), (г) —
комментарий-фиксация в `db_query_external.py:108-115`, доменные guard'ы и
allowlist путей (ADR-0358 / ADR-0359), гейт
`tools/check_decorative_capabilities.py` + baseline (45 записей) + CI-шаг.
Решение (в) — **не реализовано**, это отдельная owner-задача.

## Followup (owner-задачи)

1. **P0 — починить sync-путь авторизации.** Выбрать один из трёх
   кандидатов раздела «Решение (в)», зафиксировать отдельным ADR
   (правило ADR-0284 §1.1) с владельцем; после этого — снять baseline
   `tools/check_decorative_capabilities_allowlist.txt` и вернуть
   `required_capability` новым процессам.
2. **Свести два gateway к одному** (app-level из `plugins/composition/di.py:221-224`
   и facade-овский из `services/authorization/facade.py:96-113`) — иначе
   policy-цепочка prod и рантайм-проверка процессоров продолжат различаться.
3. **Решить судьбу 13 классов**, которые объявляют `required_capability`,
   но не вызывают `auth_check` (декларация без эффекта) — либо вызвать
   `auth_check`, либо убрать декларацию.

## Связи с другими ADR

- ADR-0358 — allowlist файловых путей в конфиг-системе и единый path-барьер
  DSL (Wave 13 Q7): независимый от policy барьер, работает всегда.
- ADR-0359 — канонический SQL-guard для DSL и fail-closed flag для
  `infra_db_query` (Wave 13): доменная защита вместо capability-барьера;
  сам ADR-0359 отсылает capability-барьер для SQL-процессоров сюда.
- ADR-0284 §1.1 — governance-правило «изменение семантики = отдельный ADR
  с владельцем»; основание для отложенной починки пути.
- ADR-0335 — гейт unsafe-defaults конфигурации (смежный класс дефектов:
  декларация без исполнения).
