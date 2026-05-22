# ADR-0069 — SkillRegistry V11.2 — TOML-манифест для AI-tools

* Статус: **Draft** (Sprint 26 candidate, [wave:s26/w5-skill-registry])
* Связано с: `gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md` Зона 5 (skills declarative), PLAN.md V22.4 §S26, ADR-NEW-22.
* Память: [[feedback_v11_manifest_design]], [[feedback_wave_4_plugin_system]].

## Контекст

Текущее состояние tools/skills:

1. `src/backend/services/ai/tools/registry.py` — хорошая база: `AgentTool` dataclass + `@agent_tool` декоратор + auto JSON-schema generation через `typing.get_type_hints`.
2. Регистрация — **только в Python**: каждый skill требует `@agent_tool` и import цепочки → перезапуск процесса.
3. Capability-gate per-tool — отсутствует.
4. Version pinning per-tool — отсутствует (нельзя сказать «использовать `credit.score.calculate` v1.2.0 для tenant X»).
5. Auto-export в MCP/LangGraph/OpenAI — частично, через manual wrappers.

**Нарушение R-V15-6** (80% YAML / 20% Python): tools — критическая часть AI-стека, но описаны в Python. Расширение под новый skill = редактировать Python и перезапускать.

## Решение (Draft)

**SkillRegistry V11.2** — расширение `plugin.toml` секцией `[[skill]]` + TOML-loader в `core/ai/skill_registry.py` (sov с существующим `services/ai/tools/registry.py`).

### plugin.toml расширение

```toml
[[skill]]
id            = "credit.score.calculate"
version       = "1.2.0"
handler       = "extensions.credit.functions.score:calculate"
description   = "Расчёт скоринга по входным данным договора"
input_schema  = "schemas/credit_score_input.json"
output_schema = "schemas/credit_score_output.json"
capabilities  = ["db.read.orders", "ai.invoke.credit_check"]
policy_ref    = "credit_check_strict"
protocols     = ["mcp", "langgraph", "openai_tools"]
timeout_s     = 30
tenant_aware  = true
feature_flag  = "CREDIT_SCORE_V2_ENABLED"

[[skill]]
id            = "credit.fraud.check"
version       = "0.8.0"
handler       = "extensions.credit.functions.fraud:detect"
description   = "Проверка договора на мошеннические паттерны"
capabilities  = ["db.read.fraud_blacklist", "ai.invoke.fraud_check"]
policy_ref    = "fraud_check_strict"
protocols     = ["mcp", "openai_tools"]
timeout_s     = 10
```

### SkillRegistry API

```python
class SkillSpec(BaseModel):
    id: str                            # "credit.score.calculate"
    version: str                       # semver "1.2.0"
    handler: str                       # "module:function" call_function_modules whitelist
    description: str
    input_schema: str | None           # path to JSON-Schema
    output_schema: str | None
    capabilities: list[str]
    policy_ref: str | None             # ссылка на AIPolicySpec.name
    protocols: list[Literal["mcp", "langgraph", "openai_tools", "all"]]
    timeout_s: float = 30
    tenant_aware: bool = False
    feature_flag: str | None = None

class SkillRegistry:
    """Реестр AI skills с TOML и Python источниками.
    
    Sov:
    - from_toml_manifest(plugin_toml_path) — новый loader (V11.2).
    - from_python_decorator(@agent_tool) — старый путь, остаётся.
    - auto_register_to(mcp_server, langgraph_tools, openai_tools) — auto-protocol.
    """
    def from_toml_manifest(self, plugin_toml: Path) -> list[SkillSpec]: ...
    def from_python_decorator(self, func: Callable) -> SkillSpec: ...
    async def invoke(self, skill_id: str, **kwargs) -> Any: ...
    async def hot_reload(self) -> None: ...  # watchfiles.awatch
    
    def export_to_mcp(self) -> list[MCPTool]: ...
    def export_to_langgraph(self) -> list[LangGraphTool]: ...
    def export_to_openai_tools(self) -> list[dict]: ...  # OpenAI function calling spec
```

### Auto-export pipeline

При регистрации SkillSpec:

```
SkillSpec(protocols=["mcp", "langgraph", "openai_tools"])
    ↓
auto_register_to():
  - if "mcp" in protocols → register in MCPNamespace (по domain из id)
  - if "langgraph" in protocols → register in LangGraphToolRegistry
  - if "openai_tools" in protocols → register in OpenAIToolsRegistry
```

### Hot-reload

Использовать существующий `watchfiles.awatch` (Wave B) на `extensions/*/plugin.toml`:

- При изменении `[[skill]]` секции → diff old/new specs → unregister/register changes.
- Target reload time ≤ 2s в dev_light.

### CI-gate

`make skill-schema` — JSON-Schema validation `plugin.toml [[skill]]` секции.

### Capability

- Existing `plugin_runtime/capability_gate.py` already handles per-plugin capabilities.
- SkillRegistry intercepts `invoke()` → проверяет `skill.capabilities` через `CapabilityGate.check`.

## Альтернативы (отвергнуто на этом этапе)

* **YAML вместо TOML** — `plugin.toml` уже TOML (V11.1); согласованность важнее.
* **Полное удаление `@agent_tool` Python-декоратора** — нарушает backward-compat; декларация Python должна остаться для core skills (ai/, system/).
* **Composio как primary backend** — отлично подходит для готовых SaaS skills, но не покрывает custom domain skills; opt-in S28+.
* **Custom DSL для skills** — overkill; TOML+JSON-Schema достаточно.

## Открытые вопросы (решаются в wave S26 W5)

* **call_function whitelist** — `handler="extensions.credit.functions.score:calculate"` валидируется против `plugin.toml::call_function_modules`?
* **Version pinning per-tenant** — `extensions/credit_premium/plugin.toml` имеет `[[skill]] id="credit.score.calculate" version="2.0.0-beta"`, global = `1.2.0`. Кто резолвит?
* **Skill composition** — может ли skill вызывать другой skill? Через AIGateway?
* **Streaming output skills** — `output_schema` для streaming (SSE)?

## Зависимости

* `core/plugin_runtime/capability_gate.py` — capability check.
* `core/plugin_runtime/sandbox.py` — sandboxed handler invocation.
* `core/ai/policy/spec.py::AIPolicySpec` — policy_ref resolution.
* `core/ai/gateway.py::AIGateway` — skill_invoke через AIGateway.
* `entrypoints/mcp/gateway.py` — MCP auto-export.
* `services/ai/tools/registry.py` — existing Python-decorator registry (compat).
* `watchfiles` — hot-reload.

## DoD-критерии scaffold → Accepted

* [ ] `core/ai/skill_registry.py::SkillRegistry` с `from_toml_manifest()`.
* [ ] `SkillSpec` Pydantic v2 model.
* [ ] `plugin.toml [[skill]]` JSON-Schema (расширение existing schema V11.1 → V11.2).
* [ ] `make skill-schema` CI-gate.
* [ ] Hot-reload через watchfiles ≤ 2s.
* [ ] Auto-export to MCP/LangGraph/OpenAI tools (3 формы из одного SkillSpec).
* [ ] `tests/unit/core/ai/test_skill_registry_toml.py`.
* [ ] PoC `extensions/example_ai_plugin/plugin.toml` с 2 `[[skill]]` секциями.
* [ ] Backward-compat: existing `@agent_tool` декоратор работает.
* [ ] Sphinx page по Skill Registry V11.2 architecture.

## Связи с другими ADR

* **ADR-NEW-19 AIGateway** — потребитель SkillRegistry в `skill_invoke` DSL processor.
* **ADR-NEW-20 AIPolicySpec** — `policy_ref` ссылка из SkillSpec.
* **ADR-NEW-23 MCP Gateway namespaces** — auto-export в MCPNamespace.
* **ADR-0056 Routes V11** — pattern reuse для TOML-manifest.
* **ADR-NEW-S17/K3 MiddlewareRegistry** — pattern reuse для plugin/entry-point hooks.
