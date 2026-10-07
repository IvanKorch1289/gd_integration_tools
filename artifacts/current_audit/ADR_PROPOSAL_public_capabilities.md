# ADR-предложение: публичные capability ядра (unblocks DSL routes)

> **Статус:** Решение A и B приняты владельцем 2026-10-06 (рекомендованные
> варианты, применены по таймауту опроса). Реализовано: `net.inbound` +
> `net.outbound` помечены `public=True`; добавлены определения `audit.write`
> и `jupyter.hub` (49 → 51 capability).
>
> **Важно:** capability-гейт — **не** корневая причина `dsl_routes = 0`.
> См. раздел 3.2: реальная цепочка барьеров длиннее, и capability-гит стоит
> в ней не первым.
>
> **Дата:** 2026-10-06
> **Контекст:** аудит `artifacts/current_audit/AUDIT_2026-10-06_runtime_wiring.md`

---

## 3.2 Реальная цепочка барьеров `dsl_routes = 0` (найдена после решения)

Первая редакция этого ADR считала, что пустой `public_capabilities()` —
корневая причина. **Это не так.** Замер на живом сервере с включённым
`RouteLoader` показал полную цепочку — каждый следующий барьер становился
виден только после снятия предыдущего:

| # | Барьер | Где | Статус |
|---|---|---|---|
| 1 | `V11_ROUTE_LOADER_ENABLED=false` **по умолчанию** — `RouteLoader` не запускается вообще | `core/config/plugin_loader.py:92` | требует решения владельца: включать ли V11-роуты по умолчанию |
| 2 | capability-гит: 4 роута объявляют `db.write` / `audit.write` / `ai.invoke` / `jupyter.hub` без плагина | `gate/__init__.py:117` | **решён** (Решение A + B) |
| 3 | feature-флаг роута не задан в реестре: `routes_v11_1a_discovery` не определён нигде в коде, резолвится как ENV → `False` | `routes/loader.py:78` | делает `echo_demo` / `health_proxy_demo` disabled |
| 4 | `pipeline_register_error: Missing required field: route_id` — pipeline-YAML обязаны содержать `route_id`, но документированный формат (`from:` / `steps:`) его не содержит | `dsl/yaml_loader/build.py:24` | **не решён** |
| 5 | `composition_demo` отключён флагом `route_composition_include` | `dsl/yaml_loader/loaders.py:60` | требует решения |
| 6 | ключ `from:` из документированного YAML-формата **не читается нигде** — `_build_pipeline` читает только `route_id`, `source`, `description`, `processors`/`steps` | `dsl/yaml_loader/build.py:20` | **не решён** — транспорт не привязывается |

### Барьер 6 — самый существенный

«DSL Dual-Mode Principle» в `CLAUDE.md` документирует YAML так:

```yaml
from: { http: { method: POST, path: /api/v1/credit/check } }
steps: [...]
```

Проверено на реальном коде:

* `_build_pipeline` **не читает `from:`** — блок транспорта игнорируется;
* он требует `route_id`, которого в документированном формате нет (барьер 4);
* Python-форма из того же раздела CLAUDE.md
  (`RouteBuilder("x").from_("http:POST /path")`) **падает**:
  `TypeError: RouteBuilder.from_() missing 1 required positional argument:
  'source'` — `from_` является `@classmethod`-конструктором
  (`dsl/builders/base/__init__.py:258`), а не chainable-методом источника.
  Корректная форма: `RouteBuilder.from_("x", source="http:POST /path")`.

То есть ни YAML-, ни Python-форма dual-mode принципа не реализованы так,
как документировано. Даже после снятия барьеров 1–3 маршруты не получат
transport-привязки. Это отдельная работа в ядре DSL, а не настройка.

### Сделанный шаг против чёрного ящика

`GET /api/v1/admin/routes` отдавал `{"total": 0, "routes": []}` независимо от
причины, и найти её можно было только по логам. Теперь ответ содержит секцию
`loader` с состоянием, счётчиками и **причиной каждого отказа**:

```json
{"loader": {"state": "started", "discovered": 7, "active": 0, "failed": 6,
 "rejected": [{"name": "echo_demo",
               "reason": "pipeline_register_error: Missing required field: route_id"},
              {"name": "hello_route",
               "reason": "capability_superset: ..."}]}}
```

Ключи `total` и `routes` не изменены. Проверка
`http_check.py::dsl_route_diagnostics` защищает от возврата к чёрному ящику.

---

## 1. Почему это вообще нужно

`RouteLoader` отклоняет маршрут, если объявленные им capability не покрыты
объединением capability плагинов и **публичного набора ядра**:

```
route.capabilities ⊆ union(requires_plugins.capabilities) ∪ public-core
```

`build_default_vocabulary()` регистрировал **49** capability, и у **ровно 0**
из них `public=True`. Публичного набора не существует, поэтому при отсутствии
`requires_plugins` **любая** декларация непакрываема. Результат: 0 из 7
маршрутов загружается, причём проверка срабатывает **до** `feature_flag`, так
что включение флагов само по себе не помогает.

Официально сгенерированный каталог `docs/reference/capabilities.md` подтверждает
текущее состояние: колонка `public` = `➖` у всех 49. То есть это не регрессия —
механизм `public=True` заложен в модель (`vocabulary/models.py:24-34`), но
никогда не заполнен.

## 2. Что реально объявляют 7 маршрутов

| Capability | Есть в vocabulary? | Где используется |
|---|---|---|
| `net.inbound` | ✅ | `echo_demo`, `composition_demo`, `health_proxy_demo` |
| `net.outbound` | ✅ | 6 из 7 маршрутов |
| `db.write` | ✅ | `hello_route`, `test_route_w1` |
| `ai.invoke` | ✅ | `hello_route`, `osint_agent` *(было `ai.llm` — исправлено)* |
| `audit.write` | ❌ **нет** | `hello_route`, `test_route_w1`, `jupyter_hub_run` |
| `jupyter.hub` | ❌ **нет** | `jupyter_hub_run` |

**Это не декоративные декларации.** У `hello_route` в `main.dsl.yaml` есть
реальные шаги `llm_call:`, `audit:`, `http_call:` — то есть capability реально
нужны для исполнения, а не просто перечислены.

## 3. Ключевой факт для решения

Замер через `tools/public_capabilities_probe.py` (повторяет логику
`check_capabilities_subset` на реальных манифестах, ничего не внедряя):

| Вариант | `public` | Роутов проходит | Остаются заблокированы |
|---|---:|---:|---|
| 0 — текущее состояние | 0 | **0 / 7** | все семь |
| 1 — `net.inbound` + `net.outbound` | 2 | **3 / 7** | `hello_route`, `jupyter_hub_run`, `osint_agent`, `test_route_w1` |
| 2 — + `db.write` | 3 | **3 / 7** | то же — `db.write` **не добавляет ничего** |
| 3 — + `db.read` + `ai.invoke` | 5 | **4 / 7** | `hello_route`, `jupyter_hub_run`, `test_route_w1` |

Два вывода, важных для решения:

1. **Главный рычаг — `net.*`.** Он поднимает 0 → 3. `db.write` в одиночку
   не даёт эффекта: `hello_route` и `test_route_w1` объявляют его вместе с
   `audit.write`, которого нет в vocabulary, и падают на нём.
2. **Оставшиеся 3 роута не чинятся флагом.** `audit.write` и `jupyter.hub`
   **отсутствуют в vocabulary** — их нельзя сделать публичными, их надо
   сначала определить. Это отдельное решение (Решение B).

Фактические capability, объявленные роутами:

| Роут | Capability | В vocabulary |
|---|---|---|
| `composition_demo` | `net.inbound`, `net.outbound` | да / да |
| `echo_demo` | `net.inbound` | да |
| `health_proxy_demo` | `net.inbound`, `net.outbound` | да / да |
| `osint_agent` | `net.outbound`, `ai.invoke` | да / да |
| `hello_route` | `net.outbound`, `db.write`, **`audit.write`**, `ai.invoke` | **`audit.write` — НЕТ** |
| `test_route_w1` | `net.outbound`, `db.write`, **`audit.write`** | **`audit.write` — НЕТ** |
| `jupyter_hub_run` | `net.outbound`, **`jupyter.hub`**, **`audit.write`** | **оба НЕТ** |

## 3.1 Уточнение, меняющее оценку риска

Первая редакция этого ADR утверждала, что публичность `db.write` — «высокий
риск: снимает требование явной декларации доступа к данным». **Это было
слишком сильное утверждение.** Проверка кода показала:

* `public` читается **только** в `gate.check_capabilities_subset`
  (`gate/__init__.py:146,150`) — это проверка манифеста при загрузке роута;
* рантайм-`CapabilityGate.check()` (`gate/check_mixin.py:62`) **`public` не
  смотрит вовсе** — он идёт через policy, затем декларацию плагина, затем
  matcher scope;
* доступ к данным идёт через `external_database_facade._check`
  (`db.read`/`db.write`), egress — через `OutboundHttpClient._capability_check`
  (`net.outbound`). Оба вызывают именно этот `check()`.

Отсюда: `public=True` **не выдаёт доступ**. Он снимает требование назвать
плагина в `route.toml`, но без соответствующей декларации в плагине
рантайм всё равно вернёт `CapabilityDeniedError`.

Дополнительно: **все 49 capability имеют `scope_required=True`**, поэтому
публичность не просто снимает проверку плагина — она обходит и сравнение
scope (`if ref.name in public_names: continue`). Для `net.*` и `db.*` это
компенсируется вторым слоем (см. выше), а вот capability **без рантайм-guard'а**
публиковать нельзя — декларация станет единственной защитой.

**Итог:** риск варианта 1 ниже, чем считалось изначально. Оценка «средний» для
`net.outbound` сохраняется, но по конкретной причине: не из-за снятия
scope-контроля, а из-за снятия требования объявить egress-таргет в плагине.
Рантайм WAF + scope-match остаются.

## 4. Разделение на два независимых решения

### Решение A — что пометить публичным (безопасно обсуждать)

Публичность означает «роут может использовать эту capability без декларации
в плагине». Это расширение поверхности, поэтому:

| Capability | Что даёт публичность | Риск |
|---|---|---|
| `net.inbound` | роут может принимать webhook/SSE без плагина | низкий — входящий трафик всё равно проходит auth/WAF/idempotency middleware |
| `net.outbound` | роут может ходить наружу без плагина | **средний** — обходит необходимость объявить egress-таргет; WAF всё равно enforce'ится, но scope-контроль размывается |
| `db.write` | роут может писать в БД без плагина | **высокий** — снимает требование явной декларации доступа к данным |

**Рекомендация:** начать с варианта 1 (`net.inbound` + `net.outbound`) —
это разблокирует `echo_demo`, `composition_demo`, `health_proxy_demo`, то есть
3 из 7 маршрутов без ослабления доступа к данным. `db.write` оставить
требующим декларации в плагине: это осознанный контроль «кто пишет в БД».

### Решение B — нужны ли `audit.write` и `jupyter.hub` (требует ADR)

Три варианта:

1. **Добавить в vocabulary** как новые `CapabilityDef` — требует ADR, определения
   matcher и `scope_required`. Обратите внимание: в vocabulary уже есть
   `pii.audit` (только для PII-событий), но **общего** capability для записи
   audit-событий нет, хотя шаг `audit:` в DSL существует и используется.
2. **Убрать из манифестов** роутов, которым аудит не нужен по факту.
3. **Оставить как есть** — тогда `hello_route`, `test_route_w1` и
   `jupyter_hub_run` останутся незагруженными даже при решении A.

## 5. Что НЕ требует решения

- `ai.llm` → `ai.invoke` — **уже исправлено** в `routes/hello_route/route.toml`
  и `routes/osint_agent/route.toml`. `ai.invoke` — каноническое имя из
  ADR-NEW-19; `ai.llm` в vocabulary не существует.
- Проверка маршрутов теперь логируется: `RouteLoader._log_outcome()` печатает
  разбивку и причину отказа каждого маршрута, вместо молчаливых
  «0 маршрут(ов) активно».

## 6. Как проверить после решения

```bash
# сколько маршрутов реально загрузится
V11_ROUTE_LOADER_ENABLED=true V11_PLUGIN_LOADER_ENABLED=true \
  .venv/bin/python -m uvicorn src.backend.main:app --port 8180 &
curl -s localhost:8180/health
grep -oE "RouteLoader: [^']{0,120}" /tmp/uvicorn.log | sort -u
```

Ожидание после решения A (вариант 1): `активно 3`, из 7; `jupyter_hub_run`,
`hello_route`, `test_route_w1` — с явной причиной отказа.

## 7. Моя позиция

Я **не стал** менять `public=True` молча. Это единственное изменение в этой
волне, которое осознанно расширяет security-поверхность: до него capability
без объявления получить было нельзя в принципе, после — можно. Такое решение
должно быть записано, а не выведено агентом из молчания.

Всё остальное, что не требовало вашего решения, уже сделано: 16 дефектов
рантайм-связывания, гейт слоёв, документационные ловушки, supply-chain.