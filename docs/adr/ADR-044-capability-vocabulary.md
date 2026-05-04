# ADR-044: Capability vocabulary V11 (R1.1)

- **Статус:** proposed
- **Дата:** 2026-05-04
- **Фаза:** R1 Foundation (V11 — domain-agnostic core re-frame)
- **Автор:** v11-architect

## Контекст

V11.1 фиксирует runtime capability-gate как механизм изоляции
плагинов и маршрутов: ядро выдаёт ресурсы (БД, секреты, HTTP, FS,
MQ, кэш, …) только через capability-checked фасады. Плагин/route
декларирует нужные capabilities в `plugin.toml` / `route.toml`
(см. ADR-042 / ADR-043); запрос вне декларации → `CapabilityDeniedError`.

ADR-042 / ADR-043 используют v0-набор как placeholder и явно
форвардят сюда полное определение. Без формального каталога:

- Невозможно валидировать manifest — `CapabilityRef.name` принимает
  любую строку.
- Невозможно реализовать `CapabilityGate` — нет правил резолвинга
  scope-glob.
- Невозможно построить admin-UI / DSL-Linter — нет каталога
  «что вообще можно запросить».

Дополнительно V11.1a требует: **capabilities route ⊆ union(capabilities
плагинов из `requires_plugins`)** — без формального scope-grammar
этот инвариант проверить нельзя.

## Рассмотренные варианты

- **Вариант 1 — свободные строки + ad-hoc проверки на стороне фасадов.**
  Плюсы: zero-структура. Минусы: нельзя валидировать manifest до
  активации; разные фасады реализуют разные правила; нет каталога.

- **Вариант 2 — Python-enum закрытый набор capability-имён.**
  Плюсы: type-safety. Минусы: расширение требует правки ядра при
  каждом новом ресурсе (LLM-провайдер, S3-bucket, ...) → ломает
  V11 «ядро domain-agnostic, плагины расширяемы».

- **Вариант 3 — формальная грамматика `<resource>.<verb>` + scope-glob,
  открытый каталог через `CapabilityVocabulary` registry.**
  Плюсы: формальные инварианты + расширяемость через registry
  (плагин может зарегистрировать свою capability-категорию через
  ядро); единая модель парсинга; CapabilityGate может проверять
  scope без знания природы ресурса. Минусы: нужна минимальная
  runtime-инфраструктура (~150 LOC).

- **Вариант 4 — POSIX-style integer-bitmap capabilities.**
  Плюсы: O(1) проверка. Минусы: непригодно для scope (host-glob,
  path-glob, namespace-prefix не выражаются битами); нечитаемо
  в TOML.

## Решение

Принят **Вариант 3** — формальная грамматика + scope-glob + открытый
каталог через `CapabilityVocabulary` registry.

### Грамматика

```
capability       := name ["." scope]
name             := resource "." verb
resource         := IDENT          ; "db", "secrets", "net", "fs",
                                     "mq", "cache", "workflow", "llm"
verb             := IDENT          ; "read", "write", "publish",
                                     "consume", "invoke", "start", ...
scope            := scope-token { "." scope-token }
scope-token      := SAFE-STR | glob-segment
glob-segment     := "*"            ; одиночный сегмент wildcard
                  | "**"           ; рекурсивный wildcard
SAFE-STR         := [a-z0-9_-]+    ; alias-имена (`credit_db`)
                  | uri-prefix     ; "vault://", "env://", "kms://"
                  | host-glob      ; "*.cbr.ru", "api.*.bank.local"
                  | path-glob      ; "/var/lib/credit/*"
                  | topic-glob     ; "credit.events.*"
IDENT            := [a-z][a-z0-9_]*
```

В TOML это выражается как **отдельные `name` + `scope`**:

```toml
[[capabilities]]
name = "db.read"
scope = "credit_db"
```

(`scope` опционален; отсутствие = «без scope-restriction», что
допустимо только для сугубо «бесресурсных» capability — таких в
v0-каталоге нет).

### V0 каталог capabilities

> Минимальный набор, нужный R1-демо плагинам и Wave D Temporal-backend.
> Расширения (LLM, S3-buckets, cluster-admin, billing) — отдельными
> ADR через CapabilityVocabulary.register().

| name | scope-форма | фасад ядра | пример scope | пример caller |
|---|---|---|---|---|
| `db.read` | DSN-alias | `DatabaseFacade.session(read_only=True)` | `credit_db` | плагин кредитки |
| `db.write` | DSN-alias | `DatabaseFacade.session()` | `credit_db` | он же, write-handler |
| `secrets.read` | URI-glob | `SecretsFacade.get(...)` | `vault://credit/*`, `env://CREDIT_*` | плагин кредитки |
| `net.outbound` | host-glob | `HTTPFacade.request(...)`, `GRPCFacade.invoke(...)` | `*.cbr.ru`, `api.bki.ru` | route credit_pipeline |
| `net.inbound` | port-spec | `WebhookFacade.endpoint(...)` | `8080/credit/*` | плагин webhook-receiver |
| `fs.read` | path-glob | `FSFacade.open(..., mode="r")` | `<plugin>/data/*`, `/tmp/credit/**` | RPA-плагин |
| `fs.write` | path-glob | `FSFacade.open(..., mode="w")` | `<plugin>/output/*` | он же |
| `mq.publish` | topic-glob | `MQFacade.publish(...)` | `credit.events.*` | route credit_pipeline |
| `mq.consume` | topic-glob | `MQFacade.consume(...)` | `credit.commands.*` | плагин кредитки |
| `cache.read` | namespace-prefix | `CacheFacade.get(...)` | `tenant:{id}:plugin:credit:*` | плагин кредитки |
| `cache.write` | namespace-prefix | `CacheFacade.set(...)` | `tenant:{id}:plugin:credit:*` | он же |
| `workflow.start` | workflow_id-glob | `WorkflowFacade.start(...)` | `credit.score.*` | route credit_pipeline (Wave D Temporal) |
| `workflow.signal` | workflow_id-glob | `WorkflowFacade.signal(...)` | `credit.score.*` | плагин human-approval |
| `llm.invoke` | provider-glob | `LLMFacade.invoke(...)` | `openai/*`, `local/llama-*` | AI-агенты (Wave 8) |

**Префикс scope-токенов** (зарезервированы ядром):

- `vault://<path>` — Vault-secret
- `env://<NAME>` — переменная окружения
- `kms://<key>` — KMS-зашифрованный секрет (R3)
- `tenant:{id}:` — tenant-namespaced cache-ключ

### Scope-резолвинг

`CapabilityGate.check(plugin_name, capability_name, requested_scope)`:

1. Найти декларацию `CapabilityRef(name=capability_name, scope=declared_scope)`
   в `manifest.capabilities` плагина/route.
2. Если декларации нет — `CapabilityDeniedError(plugin=…, name=…)`.
3. Если `declared_scope is None` — capability бесскоупная; ok
   (только для capabilities из white-list в `CapabilityVocabulary`).
4. Иначе — сматчить `requested_scope` с `declared_scope` через
   `ScopeMatcher` для соответствующего resource:
   - `db.*` → exact-match alias.
   - `secrets.*`, `net.*`, `fs.*`, `mq.*`, `cache.*`, `workflow.*`,
     `llm.*` → `fnmatch.fnmatchcase(requested, declared)` с
     обработкой `**` (рекурсивный glob).
5. Не-матч → `CapabilityDeniedError`.

ScopeMatcher реализован как **strategy-per-resource**:

```python
@runtime_checkable
class ScopeMatcher(Protocol):
    def match(self, requested: str, declared: str) -> bool: ...
```

Дефолтные:

- `ExactAliasMatcher` (`db.*`)
- `GlobScopeMatcher` (`net.*`, `fs.*`, `mq.*`, `cache.*`,
  `workflow.*`, `llm.*`)
- `URISchemeMatcher` (`secrets.*` — учёт `vault://` /
  `env://` префиксов как самостоятельных пространств)

### CapabilityVocabulary registry

```python
class CapabilityDef:
    name: str                # "db.read"
    matcher: ScopeMatcher    # ExactAliasMatcher() | GlobScopeMatcher()
    scope_required: bool     # True для всех ресурсных
    description: str         # для admin-UI / DSL-Linter

class CapabilityVocabulary:
    def register(self, definition: CapabilityDef) -> None: ...
    def get(self, name: str) -> CapabilityDef: ...
    def all(self) -> tuple[CapabilityDef, ...]: ...
    def validate_ref(self, ref: CapabilityRef) -> None: ...
```

V0-каталог регистрируется в `core/security/capabilities/vocabulary.py`
через `register_default_vocabulary()`. Плагины могут зарегистрировать
**новую категорию** только если их manifest имеет meta-capability
`core.capability_vocabulary.extend` (выдаётся вручную ядром-админом).

### Audit policy

Любой `CapabilityGate.check(...)` пишет audit-event:

```json
{
  "event": "capability.check",
  "plugin": "credit_pipeline",
  "capability": "db.read",
  "requested_scope": "credit_db",
  "declared_scope": "credit_db",
  "outcome": "granted",     // | "denied"
  "tenant_id": "bank_a",
  "timestamp": "2026-05-04T18:30:00Z"
}
```

Outcome `denied` дополнительно:
- инкрементирует Prometheus-метрику
  `capability_denied_total{plugin=..., capability=..., outcome=...}`;
- на `≥ N denied/min` (default 50) — `CapabilityFloodAlert`
  через `NotificationGateway`.

### Inheritance route → plugin

V11.1a инвариант: **capabilities route ⊆ union(capabilities плагинов
из `requires_plugins`) ∪ ядро-public-capabilities**.

Проверка в `RouteLoader.register()`:

```python
def _check_capabilities_subset(
    route_caps: tuple[CapabilityRef, ...],
    plugin_caps_by_name: dict[str, tuple[CapabilityRef, ...]],
    core_public_caps: tuple[CapabilityRef, ...],
) -> None:
    """
    Каждая capability route'а должна быть покрыта объединением:
    - public capabilities ядра (`net.outbound` к public-сетям и т.п.);
    - capabilities всех плагинов из requires_plugins.
    """
    available = set()
    available.update((c.name, c.scope) for c in core_public_caps)
    for plugin_name in plugin_caps_by_name:
        for c in plugin_caps_by_name[plugin_name]:
            available.add((c.name, c.scope))
    for c in route_caps:
        if not _is_covered(c, available):
            raise CapabilitySupersetError(
                route_capability=c, plugin_caps=plugin_caps_by_name
            )
```

`_is_covered` использует `ScopeMatcher` той же strategy, что в
runtime — symmetric reasoning ловит ошибки во время load,
а не во время первого `CapabilityGate.check`.

### TOML representation в manifest

См. ADR-042 / ADR-043 — capabilities декларируются как массив таблиц:

```toml
[[capabilities]]
name = "db.read"
scope = "credit_db"

[[capabilities]]
name = "secrets.read"
scope = "vault://credit/*"
```

JSON-Schema (выгружается через `CapabilityRef.model_json_schema()` в
`docs/reference/schemas/capability.schema.json`) фиксирует:

- `name` — pattern `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`
- `scope` — `string | null`, `minLength: 1`

## Последствия

- **Положительные:**
  - Manifest валидируется до активации (имя capability + грамматика
    scope) → ясные load-time-ошибки вместо runtime-сюрпризов.
  - `ScopeMatcher`-strategy позволяет ядру не знать о специфике
    ресурсов (DSN-alias vs glob vs URI-prefix) — расширение
    через регистрацию новой capability в `CapabilityVocabulary`.
  - Audit + Prometheus + Alert built-in — capability-gate видим
    в SOC/Grafana без отдельной интеграции.
  - V11.1a инвариант `route ⊆ plugins ∪ core` проверяется
    statically в RouteLoader, не на первом hot-path.
  - DSL-Linter (R2) и admin-UI могут перечислить «доступные
    capabilities» через `CapabilityVocabulary.all()` → IDE-подсказки
    в `plugin.toml`.
- **Отрицательные:**
  - +150 LOC runtime-инфраструктуры в `core/security/capabilities/`
    (Vocabulary, Matcher, Gate, ошибки).
  - Глоб-scope даёт CPU-overhead `O(n_capabilities × n_glob_segments)`
    на каждый capability-check; для 10-15 capabilities на плагин
    это пренебрежимо, но в hot-path (тысячи запросов/сек) —
    рекомендуется кэш в `CapabilityGate` (LRU по
    `(plugin, capability_name, requested_scope)`).
  - Subset-проверка route ⊆ plugins требует, чтобы все
    `requires_plugins` были загружены **до** route — это уже
    зафиксировано в V11.1a (RouteLoader после PluginLoader),
    но требует явного теста на ordering.
- **Нейтральные:**
  - Открытый CapabilityVocabulary означает, что список capabilities
    в проекте меняется со временем — `make capability-catalog`
    (после R1-импл) экспортирует актуальный список в
    `docs/reference/capabilities.md` для портала.

## Связанные ADR

- ADR-042 (R1.2 plugin.toml) — **dependent**: использует
  `CapabilityRef` из этого ADR.
- ADR-043 (R1.2a route.toml) — **dependent**: тот же
  `CapabilityRef` + invariant route ⊆ plugins.
- ADR-040 (SecretsBackend через svcs) — **связан**: secrets-фасад
  становится capability-aware (`secrets.read.<glob>` →
  `SecretsBackend.get(scope_check=…)`).
- ADR-036 (ResilienceCoordinator) — **связан**: capability-denied
  не должен триггерить fallback-chain (это не infrastructure-fail,
  а security-deny); CapabilityDeniedError помечается `not_retriable`.
- ADR-028 (Security hardening) — **связан**: capability-audit
  пишется в immutable audit-store вместе с прочими security-event'ами.
