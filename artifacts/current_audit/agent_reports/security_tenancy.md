# Агент 6 — Security / Tenancy

**Worktree**: `/home/user/dev/gd_audit` @ `a1c72378f8221c91fb883274875f6f27509162bf`
**Python**: `/home/user/dev/gd_integration_tools/.venv/bin/python` (3.14.0)
**Дата**: 2026-09-30
**Область**: `core/auth/**`, `core/security/**`, `core/tenancy/**`, `infrastructure/security/**`, `infrastructure/secrets/**`, `core/net/**`, `tools/checks/{privacy,tenant,security}*`
**Исходный код не изменялся** (правило соблюдено). Все проверки — read-only + изолированные
временные скрипты в `/tmp`.

Итог: **4 P0, 6 P1, 4 P2**. Два P0 — воспроизведённые эксплуатируемые обходы tenant-изоляции.

---

## 1. Карта защиты

| Слой | Файл:строка | Механизм | Fail-closed? |
|---|---|---|---|
| ORM row-level | `src/backend/core/tenancy/sqlalchemy_filter.py:52` | `do_orm_execute` auto-filter по `tenant_id` | **НЕТ** — `:76-78` |
| ORM write | `src/backend/core/tenancy/sqlalchemy_filter.py:88` | `before_flush` проставляет `tenant_id` | **НЕТ** — `:92-94` |
| Tenant context | `src/backend/core/tenancy/__init__.py:48` | `ContextVar[TenantContext \| None]`, default `None` | n/a |
| `get_tenant_id()` | `src/backend/core/tenancy/__init__.py:73-80` | возврат `""` при отсутствии ctx | n/a |
| Auth dependency | `src/backend/core/auth/auth_selector.py:323-329` | `RuntimeError` если default не сконфигурирован | **ДА** |
| Auth 401 | `src/backend/core/auth/auth_selector.py:349-352` | `HTTPException(401)` если все верификаторы вернули `None` | **ДА** |
| SSO guard | `src/backend/core/auth/require_sso_auth.py:82,88,166,172,178` | `RequireSsoAuthError` | **ДА** |
| JWT blacklist | `src/backend/core/auth/jwt_blacklist.py:83-91,101-105,131-135` | Redis-ошибки пробрасываются (`raise`) | **ДА** |
| SAML verify | `src/backend/core/auth/facade_verify_mixin.py:78-82` | без `dev_mode` → `is_authenticated=False` | **ДА** (но см. §9 P1-1) |
| LDAP verify | `src/backend/core/auth/facade_verify_mixin.py:179-181` | `except Exception` → `is_authenticated=False` | **ДА** |
| Env-secrets | `src/backend/infrastructure/secrets/env_backend.py:48-51` | `KeyError` если нет в env | **ДА** |
| WAF facade | `src/backend/core/net/outbound_http.py` | `OutboundHttpClient`, 124 callsite в `src/backend` | Частично (см. §4) |

Ключевой вывод карты: **core-слой (auth, JWT, SSO, env-secrets) сделан fail-closed
осознанно** — комментарии и narrow-exceptions это подтверждают. Провалы сосредоточены
в двух других местах: (а) tenant-фильтр ORM, (б) честность гейтов.

---

## 2. Fail-open места

### P0-1 — Пустой tenant = фильтр не применяется вообще (доступ к данным всех tenant'ов)

`src/backend/core/tenancy/sqlalchemy_filter.py:76-78`:

```python
tenant_id = get_tenant_id()
if not tenant_id:
    return          # <-- НЕ фильтрует, НЕ падает: возвращает ВСЕ строки
```

`get_tenant_id()` возвращает `""` при отсутствии контекста
(`src/backend/core/tenancy/__init__.py:79-80`), а `ContextVar` имеет `default=None`
(`:48`). То есть любой запрос вне `tenant_scope` (async-фоновая задача, celery/Beat,
health-check, WS-reconnect, забытый `set_tenant`) читает **все** tenant-данные.
Ошибка не 403/404 — это прямой доступ к данным.

Воспроизведено:

```
$ /home/user/dev/gd_integration_tools/.venv/bin/python /tmp/t_tenant.py
--- A) no tenant set (empty get_tenant_id()) ---
empty-tenant: rows=2 tenants=['tenantA', 'tenantB']
--- B) tenantA set ---
tenantA: rows=1 tenants=['tenantA']
--- C) empty-string tenant explicitly ---
empty-string: rows=2 tenants=['tenantA', 'tenantB']
EXIT=0
```

Сценарий A (контекст не установлен) и C (`tenant_id=""`) отдают 2 строки обоих
tenant'ов. Fail-closed требовал бы `raise`/`TenantDenied` (или `WHERE 1=0`).

### P0-2 — JOIN мультиплицирует tenant-данные: фильтр применяется только к первой сущности

`src/backend/core/tenancy/sqlalchemy_filter.py:81-86`:

```python
for frm in getattr(stmt, "froms", []):
    entity = getattr(frm, "entity_namespace", None)
    if entity and _is_tenant_aware(entity):
        stmt = stmt.where(entity.tenant_id == tenant_id)
        orm_execute_state.statement = stmt
        break          # <-- только ПЕРВАЯ tenant-aware сущность
```

`break` ограничивает фильтрацию одним entity на запрос. В JOIN двух tenant-aware
таблиц вторая остаётся нефильтрованной. Воспроизведено (tenantA видит tenantB):

```
$ /home/user/dev/gd_integration_tools/.venv/bin/python /tmp/t_join.py
JOIN query as tenantA -> [('tenantA', 'item-A'), ('tenantB', 'item-B')]
EXIT=0
```

Утечка происходит даже при **корректно установленном** tenant — то есть это не
fail-open, а систематический bypass в самом hot-path запросов.

### P0-3 — `check_object_authorization.py` печатает ❌ и выходит 0 (false-green)

`tools/checks/check_object_authorization.py:220`:

```python
if args.strict and issues:
    return 1
return 0                 # <-- без --strict: ❌ на экране, exit 0
```

Вызов в Make **без** `--strict` в двух местах: `make/quality.mk:293` (цель
`check-object-auth`) и `make/quality.mk:319` (`audit-2026-09-22`).

Фактический прогон:

```
$ python tools/checks/check_object_authorization.py
  ℹ️  Routes with ownership check: 17/159 (10.7%)
  ℹ️  Service .get(id) without tenant filter: 127
Issues:
  ❌ Object ownership check coverage is low (10.7%) — <50% of routes have explicit ownership verification.
  ❌ Many service lookups (127) without tenant filter — potential cross-tenant data access.
$ echo $?  → 0
```

С `--strict` тот же вход даёт `STRICT_EXIT=1`. Гейт в CI при этом дополнительно
заглушен `|| true` (`.github/workflows/lint.yml:186`). Итог: 10.7% покрытия
ownership-check'ами и 127 кросс-tenant `.get(id)` **не могут** заблокировать merge.

### P0-4 — Security-гейты в CI не блокирующие (`|| true`)

`.github/workflows/lint.yml:180-198` — все пять security/P0-аудит гейтов:

```
:182  run: uv run python tools/checks/check_tenant_isolation.py --strict || true
:186  run: uv run python tools/checks/check_object_authorization.py || true
:190  run: uv run python tools/checks/check_canonical_errors.py || true
:194  run: uv run python tools/checks/check_cancellation_contract.py || true
:198  run: uv run python tools/checks/check_privacy_lifecycle.py || true
```

`|| true` делает exit-code нерелевантным. Суммарно в workflows — **14** вхождений
`|| true` (`grep -rn "|| true" .github/workflows/*.yml | wc -l` → 14).

### P1-1 — SAML dev-путь возвращает `is_authenticated=True` без проверки подписи

`src/backend/core/auth/facade_verify_mixin.py:89-127`: при включённом
`saml_sp_initiated_enabled` assertion парсится через defusedxml (XXE-защита есть,
`:95-98`), но **подпись не проверяется** — извлекается только `NameID`/`Issuer`/
`Audience` (`:100-108`), и `expected_issuer`/`expected_audience` проверяются лишь
если явно переданы (`:110-117`, оба опциональны). Результат —
`is_authenticated=True` (`:122-127`) из **любого** base64-XML с тегом NameID.

Усугубляющий фактор — флаг по умолчанию включён, хотя его же description
говорит «default-OFF» (`src/backend/core/config/features/infrastructure.py:376-385`):

```python
saml_sp_initiated_enabled: bool = Field(
    default=True,                                    # :377
    description="... Активирует /saml/login ... "
                "default-OFF до AD-coordination."    # :383 — противоречие
)
```

Владелец флага не назначен (`tools/checks/feature_flag_registry.toml:122`,
`owner = "TBD@bank.local"`). Комбинация «fail-closed по умолчанию нет» +
«владелец TBD» + «нет проверки подписи» = P1 (не P0, т.к. entrypoint вне моей
области и фактический ACL я не проверял).

### P1-2 — `before_flush` не проставляет tenant при пустом контексте

`src/backend/core/tenancy/sqlalchemy_filter.py:92-94`: при `tenant_id == ""` —
такой же early-return. Новая запись полагается на колоночный default
`default="default"` (`:40`), т.е. неявно падает в tenant `"default"`. Записи,
созданные вне контекста, **молча** становятся общими.

### P1-3 — `pii-audit-smoke` деградирует провал до warning

`make/quality.mk:180-181`:

```make
@$(UV_RUN) python tools/checks/pii_audit.py --mode smoke --threshold 0.85 \
    || $(WARN) "[pii-audit-smoke] precision/recall below threshold ..."
```

Реальный провал детектора PII (`precision=0.131 recall=0.489`, `EXIT=1`) не
останавливает target. Полный `pii-audit` (`quality.mk:183-188`) не подавлен, но и
не входит в обязательный `make security` composite.

### P2-x (сводно) — осознанный fail-soft в broker/rotation
`infrastructure/secrets/broker.py:190-193` (ошибка подписчика → warning, рассылка
продолжается), `rotation.py:66,82,109`, `long_running_rotation.py:167`,
`cert_store/*` — ошибка одного backend'а не валит остальные. Для ротации это
оправданно, но для `broker.get` (`:130-132`) capability-check опционален
(`if self._check is not None`) — при `None` запрос секрета идёт без проверки.

---

## 3. Tenant isolation — оценка числами

| Метрика | Значение | Источник |
|---|---|---|
| Файлов просканировано | 2551 | прогон `check_tenant_isolation.py --strict` |
| Кандидатов без tenant-фильтра | **552** | там же |
| Allowlisted | **552 (100%)** | там же |
| Unclassified | 0 | там же |
| Прямых `TenantContext.get()` | 0 | там же |
| ORM-моделей без `tenant_id` | 6 | там же |
| Exit code (--strict) | **0** | `EXIT=0` |

**Интерпретация (fail-closed приоритет):** allowlist покрывает 100% находок, и
`_is_finding_allowlisted` (`tools/checks/check_tenant_isolation.py:101-107`)
поддерживает **directory-wildcard** — запись `path/` глушит всё вложенное дерево.
В baseline 136 записей на 552 находки, т.е. расширение идёт именно через wildcard'ы.
Плюс `.github/workflows/lint.yml:182` душит гейт через `|| true`.

Вывод: сам гейт честно работает (проверял на синтетике — см. §7), но **нулевой
свободный от baseline вектор**. С учётом доказанных P0-1/P0-2 вывод о tenant
isolation: **FAIL**. Покрытие 552/552 allowlisted не является доказательством
изоляции — контрольные тесты (P0-1/P0-2) показывают обратное.

---

## 4. SSRF / WAF — обходы

**Факт**: гейт WAF честный. Проверено на синтетике — падает с exit 1:

```
$ python tools/check_waf_coverage.py --strict --root src/backend   # во временном каталоге с нарушением
  src/backend/bad.py:3: httpx.AsyncClient()
EXIT=1        (RAW_EXIT=1)
```

Но **покрытие гейта уже фактического WAF-контракта**:

- Allowlist **пуст** (0 непустых строк в `tools/check_waf_coverage_allowlist.txt`),
  при этом на реальном коде гейт даёт `0 violations`, `EXIT=0` — потому что все
  реальные callsite'ы сидят в exempt-префиксах `_INTERNAL_EXEMPT_PREFIXES`
  (`tools/check_waf_coverage.py:42-45`): `src/backend/core/net/`,
  `src/backend/infrastructure/clients/transport/`.
- **Дыры в детекторе** (`_is_httpx_violation`, `:103-124`):
  1. `httpx.get/post/put/delete/request/stream` — **не детектируются вообще**.
     Docstring заявляет сканирование «module-level `httpx.get/post/...`»
     (`:5-6`), но `_BANNED_CLASSES = {"AsyncClient", "Client"}` (`:39`) их не
     покрывает. Подтверждено синтетикой: в файле с `httpx.get("http://evil")` и
     `AsyncClient()` выведена **только** строка `AsyncClient()`; `httpx.get` не
     попала в вывод, `EXIT=1` возник из-за второй строки.
  2. `import httpx as h` → `h.AsyncClient(...)` не детектируется (docstring `:90-92`
     это признаёт, но bypass остаётся). В текущем коде 0 таких импортов.
  3. Сканируется **только** `src/backend` (`ROOT_DEFAULT`, `:34`) — `extensions/`
     не проверяется (0 `AsyncClient(` там, так что фактического обхода нет).
- **Вне охвата гейта, реально есть 3 прямых сетевых вызова**:
  - `src/backend/services/lineage/lineage_http_emitter.py:194` — `urllib.request.urlopen(  # nosec B310` (подавлено bandit-комментарием!)
  - `src/backend/dsl/builders/content_mixin.py:77` — `urllib.request.urlopen(  # nosec B310`
  - `src/backend/infrastructure/sources/soap.py:96` — `AsyncClient(self._wsdl, transport=AsyncTransport())` (это `zeep.AsyncClient`, не httpx → вне `_BANNED_CLASSES`; WSDL URL из конфига → классический SSRF-вектор)

  Оба `urllib.request.urlopen` помечены `# nosec B310`, т.е. bandit их не видит,
  и WAF-гейт их не видит. Плюс 124 легитимных `OutboundHttpClient` callsite.
  Итого **3 callsite вне WAF-фасада** (все в `src/backend`, не в extensions).

Оценка: **PARTIAL**. Основной путь (httpx-конструкторы) закрыт, но 3 реальных
обхода и неполный детектор = SSRF-поверхность есть.

---

## 5. Auth coverage

| Метрика | Значение | Метод |
|---|---|---|
| `APIRouter(...)` определений | 79 | `grep -rn "APIRouter(" src/backend/` |
| REST-эндпоинтов (`@router.get/post/...`) | 130 | `grep -rnE "@(router\|app\|api_router\|v1_router)\.(get\|post\|...)"` |
| Эндпоинтов с явным auth-dependency | **10** | `grep -rnE "Depends\((require_auth\|get_current\|verify_token\|auth)"` |
| Routes с ownership-check | **17/159 (10.7%)** | прогон `check_object_authorization.py` |
| Service `.get(id)` без tenant-фильтра | **127** | там же |

Оценка: **PARTIAL / UNKNOWN**. Соотношение 10/130 ≈ 7.7% по статическому grep
занижено — многие эндпоинты защищаются middleware/dependencies на уровне router,
а не per-endpoint, что статический grep не видит; поэтому **10/130 нельзя читать
как «120 открытых эндпоинтов»**. Честно измеримые числа — только 17/159 ownership
(10.7%) и 127 кросс-tenant `.get(id)`. Итог по auth coverage: **NOT_VERIFIED**,
но с твёрдо отрицательным индикатором ownership-слоя (10.7% < порога 50%,
который сам гейт считает нарушением — но не блокирует, см. P0-3).

---

## 6. Privacy / erasure

| Компонент | Статус | Доказательство |
|---|---|---|
| `DeleteDataSubject` orchestrator | ✅ есть | `src/backend/core/privacy/delete_data_subject/_orchestrator.py:35` |
| Tombstone publication | ✅ | прогон гейта |
| Legal hold | ✅ | прогон гейта |
| Reconciliation | ✅ | прогон гейта |
| Storage erasure: postgresql | ❌ **UNVERIFIED** | прогон гейта |
| Storage erasure: redis | ❌ UNVERIFIED | прогон гейта |
| Storage erasure: s3 | ❌ UNVERIFIED | прогон гейта |
| Storage erasure: qdrant | ❌ UNVERIFIED | прогон гейта |
| Storage erasure: ai_memory | ❌ UNVERIFIED | прогон гейта |
| **Exit code** | **1** | `EXIT=1` |

```
$ python tools/checks/check_privacy_lifecycle.py --strict
  Storage coverage: 0/5 backends have erasure
    - postgresql: ❌ UNVERIFIED: ORM models not importable — ... (fail-closed)
Issues:
  ❌ Storage backends without erasure coverage: postgresql, redis, s3, qdrant, ai_memory
STRICT_EXIT=1
```

**0/5** backend'ов erasure подтверждены. Причина — ORM-модели не импортируются в
моём окружении; сам гейт при этом **fail-closed** (помечает UNVERIFIED и падает) —
это корректное поведение. Статус: **PARTIAL / ENV_FAILURE по окружению**, но
констатируемая конфигурация — 0/5. Это **не** доказанное нарушение erasure
(нужен полный env), и **не** PASS.

Классификация USER_DATA: реализована в `tools/classify_object_authorization.py`
(`USER_DATA_RECEIVER_PATTERNS:38`, `USER_DATA_NAMES:335`, path-based
`PATH_USER_DATA_PATTERNS:426`). Проблема: path-based детект (`:247-263`)
автоматически помечает любой `self.get(id)` в repository/store как
`receiver_type="user-data"` **с пометкой "tenant validation assumed upstream"** —
это допущение, а не проверка. Гейт при этом проходит: `9 user-data, 0 unknown,
117 total`, `EXIT=0`.

**Negative cross-tenant тесты**: 43 функции матчатся
(`def test_.*(cross_tenant|tenant_isolation|other_tenant|foreign_tenant)`), 20+
файлов в `tests/` по tenancy. Целевые прогоны в моей области — **PASS**:

```
$ python -m pytest -q -p no:randomly --timeout=120 \
    tests/unit/services/workflows/test_hitl_tenant_enforcement.py \
    tests/unit/services/ai/feedback/test_tenant_enforcement.py \
    tests/unit/services/notebooks/test_tenant_enforcement.py
16 passed in 2.81s
EXIT=0
```

Однако покрытие сосредоточено на **service-слое** (`tests/unit/services/...`), а не
на ORM-фильтре — именно тот слой, где обнаружены P0-1/P0-2, тестами на
`sqlalchemy_filter.apply_tenant_filter` не покрыт. PII-детектор: precision 0.131 /
recall 0.489 при пороге 0.85 (smoke) и 0.9 (full) — **детектор непригоден**,
результаты нельзя использовать для оценки покрытия PII.

---

## 7. Честность гейтов (фактические exit code)

Все запуски: `cd /home/user/dev/gd_audit && python <gate>`.

| Гейт | Команда | Exit | Вердикт |
|---|---|---|---|
| WAF coverage | `tools/check_waf_coverage.py --strict` | **0** | PASS (на чистом коде) |
| WAF coverage (синтетика-нарушение) | `... --strict --root src/backend` во временном каталоге | **1** | **PASS — честный** |
| Tenant isolation | `tools/checks/check_tenant_isolation.py --strict` | **0** | PASS, но 552/552 allowlisted |
| No-new-optional-tenant | `tools/checks/check_no_new_optional_tenant.py --strict` | 0 | PASS (123 = baseline 123, drift 0) |
| **Object authorization** | `tools/checks/check_object_authorization.py` | **0** | **FAIL — false-green (P0-3)** |
| Object authorization (strict) | `... --strict` | 1 | gate умеет падать; вызывается без флага |
| **Privacy lifecycle** | `tools/checks/check_privacy_lifecycle.py` | **1** | **FAIL — честный, 0/5 erasure** |
| Privacy lifecycle (strict) | `... --strict` | 1 | FAIL (в моём env) |
| **PII audit (smoke)** | `tools/checks/pii_audit.py --mode smoke --threshold 0.85` | 1 | FAIL — подавлен в `quality.mk:181` (P1-3) |
| PII audit (full) | `tools/checks/pii_audit.py --mode full --threshold 0.90` | 1 | FAIL, precision=0.135 |
| Object-authorization classifier | `tools/classify_object_authorization.py --strict` | 0 | PASS, но 9 user-data на допущении |
| Secrets broker | `python -c "import SecretBroker"` (`security.mk:28`) | 0 | PARTIAL — проверяет только **импортируемость**, не Vault-доступность |

**Итог по false-green**: 2 гейта печатают ❌ / «0 violations» и возвращают 0 в
том состоянии, в котором реально есть проблемы — `check_object_authorization`
(P0-3, 10.7% ownership) и `pii-audit-smoke` (P1-3). Плюс все 5 security-гейтов в
CI заглушены `|| true` (P0-4). WAF- и privacy-гейты **честные** — падают при
нарушении, проверено на синтетике и на реальном коде соответственно.

---

## 8. HYPOTHESIS 10 — статус: **ПОДТВЕРЖДЕНА (P0)**

> «Quality summary может быть зелёным при env/pollution failures»

Артефакт `.audit/quality-results.json` (прочитан, 7217 байт):

```
overall: PASS   counts: {'PASS': 11}   gates: 11
PASS exit=0 compileall / check_layers / check_docstrings
PASS exit=0 classify_object_authorization
PASS exit=0 check_tenant_isolation
PASS exit=0 check_privacy_lifecycle      <-- !!
PASS exit=0 check_dsl_processors_imports / verify_test_profiles / mypy_budget / ruff / ruff_format
```

**Противоречие №1 (главное)**: `check_privacy_lifecycle` записан как `PASS exit=0`,
но прямой прогон той же команды даёт `EXIT=1` с 0/5 erasure. Команда в артефакте:
`python tools/checks/check_privacy_lifecycle.py --strict`
(`quality_results_aggregator.py` записывает `command` в JSON).

**Противоречие №2 (stale-артефакт)**: артефакт записан на **другом** коммите и
в защите от этого нет ничего:

```
recorded head: c5faa2687   recorded ts: 2026-09-29T16:00:26+00:00
current  HEAD: a1c72378f822
→ STALE
```

Агрегатор **записывает** `head` (`quality_results_aggregator.py:397`, поле
`"head": _get_head()`), но **не проверяет** его при чтении — grep по
`staleness|freshness|age|stale|mismatch` в `quality_results_aggregator.py`
не даёт ни одной проверки. Потребитель — `docs/roadmap/PRODUCTION_READINESS_CURRENT.md:558`
— читает этот файл как источник статуса.

**Код формирования статуса** (`tools/checks/quality_results_aggregator.py:389-393`):

```python
overall_status = (
    "PASS"
    if all(g["status"] in {"PASS", "NOT_APPLICABLE"} for g in gates)
    else "FAIL"
)
```

Сама эта логика **корректна** (ENV_FAILURE/TOOL_FAILURE → FAIL), и
`_classify_status` (`:143-156`) корректно маппит exit 2 → ENV_FAILURE, <0/>=128 →
TOOL_FAILURE. **Ложно-зелёный статус приходит не от агрегатора, а от входных
гейтов**: они возвращают 0 при реальных нарушениях (P0-3, P0-4), поэтому
агрегатор видит 11/11 PASS. Это подтверждает гипотезу в её существенной части —
**environmental/pollution failure маскируется**, потому что заглушенный гейт
не может сообщить о провале, а stale-артефакт дополнительно маскирует дрейф.

Дополнительно: `overall_status` не различает PASS/FAIL при `NOT_APPLICABLE` для
всех гейтов (`:391`) — если бы все гейты были NOT_APPLICABLE, статус стал бы PASS.
Не проверял — **NOT_VERIFIED**.

---

## 9. Findings (итог)

### P0
- **P0-1** `core/tenancy/sqlalchemy_filter.py:76-78` — пустой tenant → фильтр не применяется, возврат данных всех tenant'ов (воспроизведено, EXIT=0 на скрипте, 2/2 строки утекли). Также `:92-94` для записей (→ P1-2).
- **P0-2** `core/tenancy/sqlalchemy_filter.py:81-86` — `break` фильтрует только первую tenant-aware сущность; JOIN утекает чужой tenant даже при корректном tenant (воспроизведено).
- **P0-3** `tools/checks/check_object_authorization.py:220` + `make/quality.mk:293,319` — ❌ при exit 0; 10.7% ownership, 127 кросс-tenant `.get(id)` не блокируются.
- **P0-4** `.github/workflows/lint.yml:182-198` — все 5 security/P0-аудит гейтов под `|| true`; ни один не может завалить merge.

### P1
- **P1-1** `core/auth/facade_verify_mixin.py:89-127` + `config/features/infrastructure.py:376-385` — SAML dev-путь даёт `is_authenticated=True` без проверки подписи; флаг `default=True` при описании «default-OFF», owner `TBD@bank.local` (`feature_flag_registry.toml:122`).
- **P1-2** `core/tenancy/sqlalchemy_filter.py:92-94` — `before_flush` не проставляет `tenant_id` при пустом контексте → неявный tenant `"default"` (`:40`).
- **P1-3** `make/quality.mk:180-181` — `pii-audit-smoke` деградирует провал в warning при precision 0.131.
- **P1-4** HYPOTHESIS 10 (см. §8) — `.audit/quality-results.json` = `overall_status: PASS` / 11 gates PASS, включая `check_privacy_lifecycle` (фактически exit 1) на устаревшем SHA `c5faa2687` без staleness-проверки.
- **P1-5** `tools/check_waf_coverage.py:39,103-124` — детектор не покрывает `httpx.get/post/...` (заявлено в docstring `:5-6`) и `import httpx as h`; allowlist пуст (0 записей), реальный код проходит за счёт exempt-префиксов `:42-45`.
- **P1-6** 3 callsite вне WAF-фасада: `services/lineage/lineage_http_emitter.py:194`, `dsl/builders/content_mixin.py:77` (`urllib.request.urlopen  # nosec B310`), `infrastructure/sources/soap.py:96` (`zeep.AsyncClient(self._wsdl, ...)`).

### P2
- **P2-1** `infrastructure/secrets/broker.py:130-132` — capability-check опционален (`if self._check is not None`); при `None` чтение секрета без проверки.
- **P2-2** `infrastructure/secrets/broker.py:190-193` + `rotation.py:66,82,109`, `long_running_rotation.py:167` — ошибки подписчиков/ротации глушатся в warning (для ротации приемлемо, для `get` — см. P2-1).
- **P2-3** `make/security.mk:26-29` (`secrets-check-broker`) — таргет проверяет только импортируемость `SecretBroker`, не доступность Vault; при недоступном Vault остаётся зелёным.
- **P2-4** `tools/classify_object_authorization.py:247-263` — path-based USER_DATA предполагает «tenant validation upstream» вместо проверки; 9 callsites классифицированы на допущении, `EXIT=0`.

---

## Приложение: ограничения верификации

- **ENV_FAILURE (моё окружение)**: ORM-модели не импортируются → privacy-гейт не смог проверить erasure глубже AST-уровня. Помечено UNVERIFIED, **не** PASS. Для полной проверки erasure нужен env с импортируемыми моделями.
- **NOT_VERIFIED**: реальный ACL/маунтинг эндпоинтов (роутеры могут защищаться на уровне router/dependencies — статический grep `Depends(...)` даёт 10 и не отражает полный реальный auth coverage); поведение под нагрузкой/в распределённом контексте; SLO-бенчмарки тенанта.
- **PARTIAL**: WAF-оценка (3 обхода найдены, но `aiohttp`/`requests` в `src/backend` детектором не покрываются вовсе — 8 вхождений, 5 из них в docstring/комментариях, реальных сетевых вызов 3).
- Полный suite **не запускался** (4 ядра / 15 ГБ RAM). Прогнано: 3 целевых теста по tenancy (16 passed), 7 гейтов, 2 синтетических теста P0, 1 JOIN-тест.
- Все скрипты проверки P0/P0-2 лежат в `/tmp` (`/tmp/t_tenant.py`, `/tmp/t_join.py`), исходный код репозитория не модифицирован.
