# ADR-0070 — MCP Gateway — domain namespaces + trusted external registry

* Статус: **Draft** (Sprint 27 candidate, [wave:s27/w4-mcp-gateway])
* Связано с: `gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md` Зона 8 (MCP gateway pattern), PLAN.md V22.4 §S27, ADR-NEW-23.
* Память: [[feedback_wave_8_rag]], [[feedback_wave_k1_security]].

## Контекст

Текущее состояние MCP:

1. `src/backend/entrypoints/mcp/mcp_server.py` — монолитный FastMCP-сервер с **50+ tools** от разных доменов (credit, analytics, system, RAG, workflow).
2. `src/backend/entrypoints/mcp/workflow_tools.py` — durable workflows как MCP tools.
3. `src/backend/infrastructure/clients/external/mcp_local_client.py` — MCP-client для local-only вызовов.
4. FastMCP версия не зафиксирована в `pyproject.toml::[ai-2026]` (`fastmcp>=2.x`).
5. **Нет auth provider** — все MCP-вызовы доверенные (anonymous).
6. **Нет MCP-client registry** для trusted external MCP-серверов.
7. **Нет streaming** support через MCP (SSE/WebSocket).

**Проблема**:
- Монолитный MCP-сервер усложняет ownership: команда credit не может deploy свои MCP tools отдельно от system tools.
- Нет boundary между trusted (internal) и external (3rd-party SaaS) MCP-вызовами → WAF не применяется.
- FastMCP 3.x вышел с `JWTAuthProvider` + streaming + multi-server registry, но не подключён.

## Решение (Draft)

**MCP Gateway pattern**: разбиение монолита на domain-MCP + единый client registry для external MCP.

### 1. Domain MCP namespaces

```python
# entrypoints/mcp/gateway.py
class MCPNamespace:
    """Logical grouping of MCP tools по domain."""
    name: str                      # "credit", "analytics", "system"
    description: str
    tools: list[MCPTool]
    capabilities_required: list[str]   # для auth-проверки

class MCPGateway:
    """Aggregator: один FastMCP-сервер, 3 namespace-логических группировки.
    
    Endpoints:
      - /mcp/credit/* → credit_mcp namespace
      - /mcp/analytics/* → analytics_mcp namespace
      - /mcp/system/* → system_mcp namespace
      - /mcp/* (legacy) → aggregator (backward-compat)
    
    Backward-compat: existing mcp_server.py preserved через aggregator.
    """
    def register_namespace(self, ns: MCPNamespace) -> None: ...
    def auto_register_skills(self, registry: SkillRegistry) -> None: ...
```

3 PoC namespaces в S27 W4:

```
entrypoints/mcp/namespaces/
├── credit_mcp.py        # credit.* skills
├── analytics_mcp.py     # analytics.* skills
└── system_mcp.py        # system.*, tech.*, health.* skills
```

### 2. MCPClientRegistry (trusted external)

```python
# infrastructure/clients/external/mcp_registry.py
class MCPClientSpec(BaseModel):
    name: str                      # "anthropic-mcp-search"
    url: str                       # "https://mcp.anthropic.com/v1/search"
    auth_provider: Literal["jwt", "api_key", "oauth", "none"]
    capability_required: str       # "net.outbound.mcp.anthropic.com:external"
    waf_policy: str = "strict"     # via OutboundHttpClient + WAF
    timeout_s: float = 10.0

class MCPClientRegistry:
    """Реестр trusted external MCP-серверов.
    
    Все запросы — через OutboundHttpClient (ADR-0050 WAF strict single-entry).
    """
    async def call(
        self, mcp_name: str, tool_name: str, **params: Any,
    ) -> Any: ...
    
    def list_registered(self) -> list[MCPClientSpec]: ...
```

`mcp_clients.yaml` config:

```yaml
clients:
  - name: anthropic-mcp-search
    url: https://mcp.anthropic.com/v1/search
    auth_provider: jwt
    capability_required: net.outbound.mcp.anthropic.com:external
    waf_policy: strict
    timeout_s: 10.0
```

### 3. Auth provider (FastMCP 3.x JWTAuthProvider)

```python
from fastmcp.auth import JWTAuthProvider

auth = JWTAuthProvider(
    issuer="https://sso.bank.internal",
    audience="mcp-gateway",
    public_key_url="https://sso.bank.internal/.well-known/jwks.json",
)

mcp_gateway = MCPGateway(auth=auth)
```

SSO integration через S18/B-1 (SAML completion).

### 4. OTel GenAI semantic conventions

Каждый MCP-вызов эмитит OTel span с атрибутами:

```python
span.set_attribute("mcp.namespace", "credit")
span.set_attribute("mcp.tool.name", "credit.score.calculate")
span.set_attribute("mcp.tool.version", "1.2.0")
span.set_attribute("gen_ai.system", "fastmcp")
```

## Альтернативы (отвергнуто на этом этапе)

* **Отдельные FastMCP-серверы per namespace** (3 разных порта) — усложняет deploy/discovery; aggregator с namespaces достаточен.
* **MCP-only без HTTP gateway** — Streamable HTTP / SSE требует HTTP-uplevel; FastMCP 3.x уже умеет.
* **Trusted external через `services/ai/tools/`** — нарушает WAF boundary; должно быть в `infrastructure/clients/external/`.
* **Без auth (anonymous)** — нарушает Auth-стек V7; невозможно audit-trail.

## Открытые вопросы (решаются в wave S27 W4)

* **Streaming MCP** — `fastmcp` 3.x поддерживает SSE/WS. Какие namespace их используют (analytics для realtime metrics)?
* **Per-namespace rate-limit** — отдельный bucket per namespace через S22 `ResilienceCoordinator`?
* **MCP versioning** — `/mcp/v1/credit/*` vs `/mcp/credit/*` (latest)? OpenAPI-like versioning?
* **Tool discovery** — `/mcp/list-tools` aggregator endpoint? Per-namespace?

## Зависимости

* `fastmcp>=3.2.4` (upgrade с 2.x; верификация через Context7 + DuckDuckGo).
* `core/net/outbound_http.py::OutboundHttpClient` — все external MCP через WAF.
* `core/plugin_runtime/capability_gate.py` — capability `net.outbound.<host>:external` + `mcp.gateway.invoke.<namespace>`.
* `core/ai/skill_registry.py::SkillRegistry` — auto-register skills в namespaces.
* `infrastructure/auth/jwt_validator.py` (S18/B-1) — для JWTAuthProvider integration.
* `infrastructure/observability/otel_tracing.py` — OTel GenAI conventions.

## DoD-критерии scaffold → Accepted

* [ ] `entrypoints/mcp/gateway.py::MCPGateway` создан.
* [ ] 3 namespace в `entrypoints/mcp/namespaces/{credit,analytics,system}_mcp.py`.
* [ ] Aggregator backward-compat: `mcp.tools.count() == pre_split_count`.
* [ ] `infrastructure/clients/external/mcp_registry.py::MCPClientRegistry`.
* [ ] `mcp_clients.yaml` config с 1+ PoC trusted external.
* [ ] FastMCP `>=3.2.4` в `pyproject.toml::[ai-2026]`.
* [ ] `JWTAuthProvider` интегрирован через SSO.
* [ ] OTel GenAI atts на 100% MCP-вызовах.
* [ ] `tests/mcp/test_namespaces_aggregator.py`.
* [ ] `tests/mcp/test_external_client_waf.py` (WAF capability проверена).
* [ ] Sphinx page по MCP Gateway architecture.

## Связи с другими ADR

* **ADR-0050 WAF strict single-entry** — все external MCP через `OutboundHttpClient`.
* **ADR-NEW-19 AIGateway** — MCP-вызовы через AIGateway если требуется policy enforcement.
* **ADR-NEW-22 SkillRegistry V11.2** — auto-export skills в MCPNamespace по domain.
* **ADR-0054 SSO Federation** — JWTAuthProvider source.
* **ADR-NEW-3 RequestContext** — `correlation_id` propagation в MCP spans.
