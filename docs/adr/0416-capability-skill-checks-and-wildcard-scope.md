# ADR-0416 — Capability-проверка скиллов, честный core-baseline и отказ от wildcard-scope

* Статус: Accepted (2026-11-02)
* Автор: wave-24, кластер F1 (мультироевой аудит, волна 24)
* Затрагивает:
  - `src/backend/core/ai/skill_registry.py`,
  - `src/backend/core/security/capabilities/runtime_resolver.py`,
  - `src/backend/core/security/capabilities/core_declarations.py`,
  - `src/backend/core/security/capabilities/gate/__init__.py`,
  - `tests/unit/core/ai/test_skill_registry_capability_gate.py`,
  - `tests/unit/core/security/capabilities/test_core_baseline_scope.py`,
  - `tests/unit/core/security/capabilities/test_runtime_resolver.py`,
  - `tests/unit/services/rpa/test_core_capabilities.py`
* **Связан с**:
  - ADR-0366 — runtime-резолвер capability-гейта (§2 — правило namespace,
    §4 — feature-флаги rollout'а);
  - ADR-044 — `CapabilityGate`, `CapabilityRef`, vocabulary, matchers scope'а;
  - ADR-0078 — синтаксис декларации capability (`[[capabilities]] name + scope`);
  - ADR-0393 / ADR-0397 — fail-closed DB-гейт и подсказки при отказе;
  - ADR-0069 — `SkillRegistry` V11.2 (TOML-манифест skill'ов).

## Контекст

Мультироевой аудит (волна 24) нашёл три дефекта в capability-контуре. Все
три — **fail-open** по природе: контроль либо не выполнялся вовсе, либо
выдавал доступ шире, чем предполагала модель.

### Дефект 1 (high) — capability скиллов не проверялись никогда

`SkillRegistry.invoke()` искал символ `_global_capability_check` в
`src/backend/core/plugin_runtime/sandbox.py`. Такого символа в проекте
**нет** (проба аудита: `has _global_capability_check: False`), а блок
проверки был обёрнут в `try/except ImportError` с `pass` — то есть
исполнялся как no-op. `SkillSpec.capabilities`, объявленные в
`plugin.toml::[[skill]]`, **не проверялись ни разу**: skill с
недекларированной capability выполнялся как ни в чём не бывало. Это прямое
нарушение контракта `core/ai/skill_registry.py` (docstring: «SkillRegistry
intercepts `invoke()` и проверяет каждое имя из `SkillSpec.capabilities`
через `CapabilityGate.check`»).

### Дефект 2 (medium) — флаг core-baseline обходился

ADR-0366 §2 определяет namespace-резолвер так: `route_id` роута → иначе
fallback `"core"`, но **только** при `dsl_capability_core_baseline_enabled
is True` **и** `capability ∈ CORE_CAPABILITIES`. Однако
`runtime_resolver.resolve_plugin()` проверял ветку
`gate.has_declaration(request.plugin, capability)` **до** флага, а в
baseline-декларациях capability «core» были объявлены **всегда**. Итог:
`resolver("core", "rpa.browser.launch")` → `allowed=True` при
`dsl_capability_core_baseline_enabled: false` — то есть в prod/staging
(где флаг выключен сознательно, «least privilege») baseline-доступ к
capability ядра был открыт всегда.

### Дефект 3 (medium) — blanket-scope в baseline

`core_capability_refs()` объявлял **77** capability со scope `"**"` сразу
для namespace'ов `core`, `system` и `ai-agent`. Wildcard-scope означал, что
scope-проверка была отключена: любая декларированная capability принимала
**любой** запрошенный scope. Пробы аудита (все — `namespace = "system"`):

```
system.check("fs.read", "/etc/shadow")                    -> ALLOWED
system.check("net.outbound", "evil.internal.example")      -> ALLOWED
system.check("storage.read", "tenant-a/private/secret.txt")-> ALLOWED
```

Последствие видно в проде: `StorageFacade` создаётся в composition root с
`plugin="system"` (`plugins/composition/service_setup.py:156`) и проверяет
`storage.read` по **ключу объекта** (`services/storage/facade.py:197`) — с
`scope="**"` проверка проходила для любого ключа, включая ключи чужого
тенанта. То же для `fs.read` (AI-слой), `net.outbound` (хост), `rpa.*`
(путь/цель операции).

Проблема не сводится к «широкому scope»: `scope="**"` — это
**декоративная** декларация. Она не ограничивает ничего и не может быть
ограничена, потому что объявляет capability сразу для всех namespace'ов
платформы — включая те, где вызывающий подставляет свой, произвольный
resource.

## Решение

### 1. Capability скиллов проверяются через гейт (fail-closed)

`SkillRegistry.invoke()` теперь вызывает
`_check_skill_capabilities(skill)`:

* гейт берётся из process-wide singleton `get_capability_gate()`
  (тот же, что у `agent_dsl`, `CapabilityFacade` и `plugin_loader`);
* **namespace** — плагин-владелец skill'а (`plugin.toml::name`, читается в
  `from_toml_manifest` и хранится в `SkillRegistry._skill_plugins`);
* **capability/scope** разбираются по vocabulary гейта: строка
  `"db.read.orders"` → capability `db.read` + scope `orders` (если capability
  известна vocabulary, scope не уточняется); неизвестное имя уходит в гейт
  как есть и отклоняется с `CapabilityNotFoundError`;
* **недоступность гейта → DENY** (`PermissionError`, «fail-closed»), а не
  «пропустить проверку»;
* отказ фиксируется audit-событием `capability.check` (`outcome="denied"`,
  в details — skill_id, capability, plugin, причина).

Мёртвый блок с `_global_capability_check` удалён. Заодно в этом файле
логирование переведено на `get_logger` (были прямые `logging.getLogger`
вызовы).

### 2. Core-baseline подчиняется флагу

`resolve_plugin()` больше **не** отдаёт namespace `"core"` по факту
декларации в гейте: ветка `has_declaration(...)` применяется только к
namespace'ам, отличным от `"core"`. Fallback `"core"` достигается только
при `dsl_capability_core_baseline_enabled is True` и
`capability ∈ CORE_CAPABILITIES` — буквально по ADR-0366 §2.

Сам baseline-grant переехал в резолвер: если namespace'ом выбран `"core"`,
решение выдаётся самим резолвером (причина `core_baseline`), потому что
core-baseline означает «ядро использует свою capability», а не «доступ к
ресурсу». Tenant-атрибуция (ADR-0366 §3) при этом сохранена: запрос без
tenant → `tenant_missing` → DENY.

### 3. Blanket-scope в baseline убран

`core_declarations.py` разделён на две части:

* `CORE_CAPABILITIES` (77 имён) — **не изменился**: список отвечает на
  вопрос «какие capability принадлежат ядру» и используется резолвером для
  выбора fallback-namespace;
* `CORE_CAPABILITY_SCOPES` — **явные** scope для capability, которые ядро
  выдаёт самостоятельно;
* `RESOURCE_SCOPED_CAPABILITIES` — capability, **исключённые** из
  baseline: их scope задаёт вызывающий (путь, host, ключ объекта, алиас
  БД, namespace кэша, URI секрета, путь/цель RPA-операции) и статически
  не выражается. Их объявляет **владелец ресурса** — роут
  (`[[route.capabilities]]`) или плагин (`[[capabilities]]`), как требуют
  ADR-0078 / ADR-044.

Wildcard `"**"` в декларациях ядра не осталось **ни в одном** namespace'е
(`core`, `system`, `ai-agent`).

## Что осталось объявленным в baseline (21 capability из 77)

| Capability | Scope | Почему такой scope |
|---|---|---|
| `agent.run` | `*` | идентификатор workflow'а (односегментный) |
| `ai.invoke` | `*` | идентификатор workflow'а |
| `ai.memory.read` | `*` | namespace памяти |
| `ai.memory.write` | `*` | namespace памяти |
| `ai.tool.dispatch` | `*` | идентификатор tool'а |
| `mcp.call` | `*` | идентификатор MCP-инструмента |
| `skill.invoke` | `*` | идентификатор skill'а |
| `pii.tokenize.reversible` | `*` | domain-id PII (banking/hr/medical) |
| `pii.tokenize.reversible.agent_actions` | `*` | domain-id PII |
| `pii.tokenize.reversible.agent_tools` | `*` | domain-id PII |
| `web_search.perplexity.invoke` | `*` | идентификатор провайдера |
| `web_search.tavily.invoke` | `*` | идентификатор провайдера |
| `data.export` | `*` | идентификатор операции/формата |
| `event.publish` | `*` | идентификатор операции |
| `llm.stream` | `*` | идентификатор операции |
| `security.waf.check` | `*` | идентификатор операции |
| `workflow.convert.format` | `*` | идентификатор формата |
| `workflow.subprocess.invoke` | `*` | идентификатор операции |
| `fs.write` | `workspace.*` | scope записи — `workspace.<session_id>` (`core/ai/fs_facade.py:213`) |
| `code.execute` | `workspace.*` | scope sandbox'а — `workspace.<session_id>` (`infrastructure/ai/e2b_sandbox.py:86`) |
| `fs.read` | `<repo_root>/**` | корень репозитория — та же политика, что `allowed_read_roots` у `AIFsFacade` (читать проект — можно, читать систему — нельзя) |

Односегментный glob `"*"` — соглашение проекта для «любой идентификатор
операции» (ср. `routes/osint_agent/route.toml`: `ai.invoke` scope=`"*"`).
Многосегментные идентификаторы (skill_id вида `credit.score.calculate`)
требуют явной декларации владельцем — baseline их не выдаёт.

### Исключены из baseline (56 capability)

* `storage.read`, `storage.write`, `storage.presign` — scope = ключ объекта;
* `net.inbound`, `net.outbound` — scope = endpoint/host;
* `db.read`, `db.write`, `db.execute_procedure` — scope = алиас ресурса
  (`ExactAliasMatcher`, точное совпадение);
* `cache.read`, `cache.write` — scope = namespace кэша;
* `secret.read` — scope = URI/имя секрета;
* `fs.watch` — scope = наблюдаемый каталог;
* `message.claim_check.store`, `workflow.claim_check.store`,
  `workflow.continue_as_new.request` — scope = идентификатор сообщения/workflow;
* `rpa.*` (41 capability) — scope = путь/цель операции (файл, URL,
  селектор, команда, артефакт).

Каждая capability из `CORE_CAPABILITIES` теперь либо объявлена в baseline с
явным scope, либо явно отнесена к resource-scoped (инвариант проверяется
тестом `test_core_capabilities_classification_is_exhaustive`).

## Альтернативы (отклонённые)

* **(а) Оставить blanket-scope у platform-идентичностей.** Отклонено: это
  и есть дефект — scope-проверка не выполняется, а `StorageFacade` под
  plugin `"system"` читает любой ключ.
* **(б) Сузить scope конкретными путями/хостами в самом baseline.** Отклонено:
  baseline объявляет capability сразу для трёх namespace'ов, а scope
  вызывающих (ключ объекта, host, алиас БД) задаёт **вызывающий**.
  Статический glob здесь — фикция: он не ограничивает ресурс, а лишь
  создаёт иллюзию ограничения.
* **(в) Оставить blanket, но закрыть namespace'ы `system`/`ai-agent`.**
  Отклонено: `core` — тоже платформенная идентичность (в неё ходит
  `OutboundHttpClient`), и в ней blanket означал бы то же самое.
* **(г) Убрать baseline целиком (пустая декларация).** Отклонено: тогда
  core-baseline (флаг `dsl_capability_core_baseline_enabled`) теряет смысл,
  а процессоры, не объявляющие capability у роута, получают blanket-deny
  даже при явно открытом baseline. Реализовано мягче: baseline-grant
  переехал в резолвер и открывается **явным** флагом.
* **(д) Добавить отдельный feature-флаг «строгий baseline».** Отклонено:
  конфиг-лишние ключи запрещены (правило `tools/config_audit.py`), а
  поведение «baseline выключен ⇒ доступа нет» уже выражается существующим
  флагом `dsl_capability_core_baseline_enabled`.
* **(е) Проверять capability скилла в DSL-процессоре
  (`SkillInvokeProcessor`), а не в реестре.** Отклонено: `SkillRegistry`
  публичен и вызывается из MCP-шлюза и LangGraph-экспорта; проверка в
  реестре покрывает все пути вызова.

## Последствия

### Позитивные

* `SkillSpec.capabilities` из `plugin.toml` **проверяются** — иначе, чем
  раньше, capability скилла не декларирована в capability-гейте.
* Core-baseline стал **честным**: он открывается ровно тогда, когда
  владелец этого решил флагом (ADR-0366 §2), и не обходится «случайной»
  декларацией в namespace `"core"`.
* Scope-проверка platform-идентичностей работает: `fs.read` за пределами
  репозитория, `net.outbound` на чужой хост, `storage.read` на чужой ключ —
  отказ.
* Единый источник правды: baseline-декларации, `CORE_CAPABILITIES` и
  runtime-резолвер больше не противоречат друг другу.

### Негативные

* **Capability, у которой scope задаёт вызывающий, больше не выдаётся
  «просто так».** Владелец обязан объявить её с конкретным scope в
  `route.toml` / `plugin.toml`. Для `storage.*`, `cache.*`, `db.*`,
  `net.*`, `rpa.*` это означает миграцию деклараций — она и была
  целью (ADR-0393, ADR-0405).
* **Платформенные сервисы, работающие от общей идентичности** (`system`,
  `ai-agent`), теперь проходят scope-проверку по своим же декларациям
  ядра. Там, где scope динамический (ключ объекта, host, алиас БД),
  декларации в baseline нет — см. «Открытые owner-задачи».
* `fs.read` в baseline привязан к корню репозитория: в окружении, где
  корень определён иначе (контейнер, симлинк), путь читается из
  `core.config.config_loader.repo_root()` — тот же источник, что у
  `AIFsFacade.allowed_read_roots`.

### Нейтрально

* `CORE_CAPABILITIES` (77 имён) не изменился — изменился только состав
  baseline-декларации (21 вместо 77).
* Проверка `required_capability` у DSL-процессоров (ADR-0366) не менялась:
  изменён только выбор namespace'а и способ выдачи core-baseline.

## Проверка

```bash
.venv/bin/python -m pytest \
  tests/unit/core/ai/test_skill_registry.py \
  tests/unit/core/ai/test_skill_registry_capability_gate.py \
  tests/unit/core/security/capabilities \
  tests/unit/services/rpa/test_core_capabilities.py \
  -q -p no:randomly
# 234 passed, 1 skipped (skip — pre-existing: hot_reload не реализован)

.venv/bin/python -m ruff check \
  src/backend/core/ai/skill_registry.py \
  src/backend/core/security/capabilities/core_declarations.py \
  src/backend/core/security/capabilities/runtime_resolver.py \
  src/backend/core/security/capabilities/gate/__init__.py
# All checks passed!

.venv/bin/python tools/config_audit.py --scope orphans   # 0
.venv/bin/python tools/check_layers.py --strict          # baseline 41 — новых нет
.venv/bin/python tools/checks/mypy_budget.py             # OK
```

Пробы аудита — до/после:

```
# было (scope="**" в baseline)
system.check("fs.read", "/etc/shadow")                     -> ALLOWED
system.check("net.outbound", "evil.internal.example")       -> ALLOWED
system.check("storage.read", "tenant-a/private/secret.txt") -> ALLOWED
resolver("core", "rpa.browser.launch")                     -> allowed=True (флаг baseline выключен)

# стало
system.check("fs.read", "/etc/shadow")                     -> denied
system.check("net.outbound", "evil.internal.example")       -> denied
system.check("storage.read", "tenant-a/private/secret.txt") -> denied
resolver("core", "rpa.browser.launch")                     -> denied (no_declaration)
```

## Открытые owner-задачи

1. **Миграция деклараций ресурсных capability.** Владельцы `storage.*`,
   `cache.*`, `db.*`, `net.*`, `rpa.*` должны объявить свои capability с
   конкретным scope в `route.toml` / `plugin.toml` — до этого соответствующие
   шаги получают fail-closed отказ. Сейчас в репозитории таких деклараций
   нет ни у одного роута (`routes/*/route.toml` не используют S3/кэш/БД).
2. **Identity-confusion платформенных фасадов.** `StorageFacade`
   (`plugin="system"`), `UnifiedCacheFacade` (`"system"`),
   `ExternalDatabaseFacade` (`"system"`), `OutboundHttpClient` (`"core"`)
   проверяют capability под **общей** идентичностью платформы, а не под
   идентичностью вызывающего. Правильное решение — проверять под
   namespace'ом вызывающего (`register_outbound_http_client(plugin=...)`
   уже существует; host-glob'ы нужных хостов уже объявлены в `plugin.toml`
   плагинов). Это правка в `services/`/`plugins/` — **вне зоны** кластера F1.
3. **`fs.read` и корень репозитория.** Scope привязан к
   `repo_root()`; если окружение выдаёт несколько корней (workspace +
   репозиторий), потребуется переход на список корней.
4. **Audit-событие baseline-выдачи.** Резолвер эмитит
   `capability.check` с `outcome="granted"` и `reason="core_baseline"` —
   стоит проверить, что дашборд аудита не считает это «обходом» (событие
   выглядит как обычный grant).

## Связи с другими ADR

- ADR-0366 — runtime-резолвер и feature-флаги; §2 теперь исполняется
  буквально, §3 (tenant-атрибуция) сохранена.
- ADR-044 — `CapabilityGate`, `CapabilityRef`, matchers scope'а; blanket
  больше не является «способом объявить capability».
- ADR-0078 — `[[capabilities]] name + scope`: декларация владельца —
  единственный способ выдать ресурсную capability.
- ADR-0393 / ADR-0397 — fail-closed и actionable-сообщения при отказе.
- ADR-0069 — `SkillRegistry` V11.2: контракт «capabilities проверяются при
  invoke» теперь исполняется.
