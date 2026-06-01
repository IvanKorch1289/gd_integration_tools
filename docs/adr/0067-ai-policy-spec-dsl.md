# ADR-0067 — AIPolicySpec — декларативная политика AI per-workflow

* Статус: **Draft** (Sprint 25 candidate, [wave:s25/w2-policy-resolver])
* Связано с: `gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md` Зона 2 (policy DSL), PLAN.md V22.4 §S25, ADR-NEW-20.
* Память: [[feedback_v11_manifest_design]], [[feedback_track_a_dsl_foundation_refactor]].

## Контекст

Текущее состояние политик AI:

1. `services/ai/guardrails/tenant_config.py` — per-tenant конфиг для Rebuff/Lakera **жёстко зашит в Python-классах**.
2. `services/ai/ai_moderation.py` — единая Python-логика moderation.
3. `pii_masker.py` — настройки regex hard-coded.
4. Per-workflow вариативность отсутствует: нельзя сказать «для `credit_check` нужны topic-control + Llama Guard, а для `doc_summarize` — только output PII mask».

**Нарушение R-V15-6** (80% YAML / 20% Python) — декларативного описания политики не существует. Расширение под новый workflow = редактировать Python и перезапускать сервис.

## Решение (Draft)

**`AIPolicySpec`** — Pydantic v2 модель + YAML-описание в `ai_policies/*.policy.yaml`.

### Pydantic-модель

```python
from typing import Literal
from pydantic import BaseModel, Field

class ModelRouterSpec(BaseModel):
    primary: str                       # "gpt-4o-mini" или "openrouter/anthropic/claude-3.5"
    fallback: list[str] = Field(default_factory=list)
    timeout_s: float = 30.0
    retry_attempts: int = 2

class SanitizerRef(BaseModel):
    name: str                          # "presidio:ru" / "pii_tokenizer:reversible:ru_strict"
    config: dict[str, Any] = Field(default_factory=dict)
    on_error: Literal["fail", "warn", "skip"] = "fail"

class GuardRef(BaseModel):
    name: str                          # "nemo:colang:topics" / "llama_guard:safe_v3" / "rebuff:default"
    config: dict[str, Any] = Field(default_factory=dict)
    on_block: Literal["fail", "warn", "dlq"] = "fail"

class MemorySpec(BaseModel):
    short_term: BackendSpec | None = None
    long_term: BackendSpec | None = None
    checkpointer: BackendSpec | None = None
    tenant_isolation: bool = True
    encryption: bool = True

class BudgetSpec(BaseModel):
    max_tokens_prompt: int = 8000
    max_tokens_completion: int = 2000
    max_cost_usd: float = 0.50
    ttl_s: int = 3600

class AuditSpec(BaseModel):
    extra_attrs: dict[str, str] = Field(default_factory=dict)
    schema_version: int = 1

class AIPolicySpec(BaseModel):
    name: str                          # "credit_check_strict"
    version: int = 1
    workflow_pattern: str              # glob "credit_check*" или exact "credit_check"
    tenant_pattern: str = "*"          # glob по tenant_id
    model_router: ModelRouterSpec
    input_sanitizers: list[SanitizerRef] = Field(default_factory=list)
    input_guards: list[GuardRef] = Field(default_factory=list)
    output_guards: list[GuardRef] = Field(default_factory=list)
    output_sanitizers: list[SanitizerRef] = Field(default_factory=list)
    memory: MemorySpec | None = None
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    audit: AuditSpec = Field(default_factory=AuditSpec)
    required: bool = True              # если True — Gateway падает без resolved policy
```

### YAML-форма

`ai_policies/credit_check_strict.policy.yaml`:

```yaml
name: credit_check_strict
version: 1
workflow_pattern: "credit_check*"
tenant_pattern: "*"

model_router:
  primary: "openrouter/anthropic/claude-3.5-sonnet"
  fallback: ["openrouter/gpt-4o-mini", "huggingface/local-llama"]
  timeout_s: 30.0
  retry_attempts: 2

input_sanitizers:
  - { name: "pii_tokenizer:reversible:ru_strict", on_error: "fail" }

input_guards:
  - { name: "nemo:colang:topics", config: { allowed: ["finance", "credit"] }, on_block: "fail" }
  - { name: "rebuff:default", config: { threshold: 0.7 }, on_block: "fail" }

output_guards:
  - { name: "llama_guard:safe_v3", on_block: "dlq" }

output_sanitizers:
  - { name: "presidio:ru_anonymize", on_error: "warn" }

memory:
  short_term: { backend: "redis", namespace: "credit:short:{tenant_id}:{session_id}", ttl: 3600 }
  long_term:  { backend: "mem0+pgvector", namespace: "credit:long:{tenant_id}", ttl: 2592000 }
  checkpointer: { backend: "langgraph+postgres", namespace: "credit_checkpoints" }
  tenant_isolation: true
  encryption: true

budget:
  max_tokens_prompt: 4000
  max_tokens_completion: 1000
  max_cost_usd: 0.25
  ttl_s: 1800

audit:
  extra_attrs: { compliance: "152-FZ", domain: "banking_credit" }
  schema_version: 1

required: true
```

### PolicyResolver

```python
class PolicyResolver:
    """Resolve AIPolicySpec по workflow_id + tenant_id.
    
    Lookup order:
    1. extensions/<plugin>/ai_policies/<name>.policy.yaml — per-plugin override
    2. ai_policies/<name>.policy.yaml — global
    3. fallback: AIPolicySpec(name="default", required=False, ...)
    """
    async def resolve(self, workflow_id: str, tenant_id: str) -> AIPolicySpec: ...
    def reload(self) -> None: ...  # hot-reload через watchfiles
```

### Per-tenant override

`extensions/credit_premium/ai_policies/credit_check_premium.policy.yaml` имеет приоритет над `ai_policies/credit_check_strict.policy.yaml` если `tenant_pattern` совпадает.

### Capability

`ai.policy.read.<name>` — capability для resolver (по умолчанию: всем доступно для resolve, но плагины не могут читать чужие политики).

## Альтернативы (отвергнуто на этом этапе)

* **Один глобальный YAML** — не покрывает per-tenant override.
* **Inline в `route.toml`** — дублирование политик между routes; усложняет аудит.
* **OPA (Open Policy Agent)** — overkill для AI-политик; AuthorizationGateway уже использует OPA.
* **Casbin** — RBAC-ориентирован, не подходит для содержательного pipeline.

## Открытые вопросы (решаются в wave S25 W2)

* **Schema versioning** — как мигрировать `version: 1` → `version: 2` при breaking change? Через `legacy_policy_migrator`?
* **Cache** — `PolicyResolver` кэширует resolved policies в RAM? TTL? Invalidation по pub/sub из Redis?
* **Validation runtime** — JSON-Schema validation при загрузке (`make ai-policy-schema`) + Pydantic at runtime?
* **Composition** — наследование политик (`extends: "base_strict"`)? Или плоская модель?

## Зависимости

* `services/schema_registry/` — JSON-Schema каталог (Sprint 23 W2).
* `core/ai/gateway.py::AIGateway` — потребитель PolicyResolver.
* `watchfiles` (Wave B) — hot-reload `ai_policies/`.

## DoD-критерии scaffold → Accepted

* [ ] `core/ai/policy/spec.py::AIPolicySpec` Pydantic v2.
* [ ] `core/ai/policy/resolver.py::PolicyResolver`.
* [ ] `core/ai/policy/enforcer.py::AIPolicyEnforcer` middleware-like.
* [ ] `ai_policies/.gitkeep` + `ai_policies/credit_check_strict.policy.yaml` PoC.
* [ ] `make ai-policy-schema` валидирует 100% `*.policy.yaml`.
* [ ] `tests/unit/core/ai/policy/test_resolver_yaml.py`.
* [ ] Per-tenant override `extensions/example_ai_plugin/ai_policies/` PoC.
* [ ] Hot-reload через watchfiles ≤2s.

## Связи с другими ADR

* **ADR-NEW-19 AIGateway** — потребитель PolicyResolver.
* **ADR-NEW-21 PIITokenizer** — referenced via `SanitizerRef.name="pii_tokenizer:reversible:*"`.
* **ADR-NEW-22 SkillRegistry V11.2** — Skill имеет `policy_ref` ссылку на AIPolicySpec.
* **ADR-0056 Routes V11** — `route.toml` может ссылаться на `ai_policy: "credit_check_strict"`.
* **ADR-NEW-1 AuthorizationGateway** — pattern reuse для resolve.
