# Cookbook #1: AI Agent с Tools Whitelist + CapabilityGate (Two-Layer Enforcement)

**Sprint**: S76 (ToolsSpec) + S79 (CapabilityGate integration)
**Audience**: AI engineers, security architects
**Time**: 15 minutes

## Goal

Restrict AI agent к invocation только approved tools. Two-layer
enforcement:
1. **CapabilityGate** (per-plugin declaration, S36/S54)
2. **AIPolicySpec.tools** (whitelist/blacklist, S76)

Disallowed tools → fail-closed, agent НИКОГДА не получает их.

## Prerequisites

```bash
# Project deps
uv sync --extra ai  # litellm, pydantic-ai, langgraph
```

## Step 1: Define AIPolicySpec с tools whitelist

Create `ai_policies/credit_check_strict.policy.yaml`:

```yaml
name: credit_check_strict
version: 1
workflow_pattern: credit_check_*
tenant_pattern: premium_*
model_router:
  primary: openai/gpt-4
  fallback:
    - openai/gpt-4o-mini
  timeout_s: 30.0
tools:
  whitelist:
    - db.read
    - ai.invoke
  blacklist:
    - fs.write
    - shell.execute
  on_violation: fail  # or "warn" or "block"
required: true
```

## Step 2: Declare capabilities в CapabilityGate

```python
from src.backend.core.security.capabilities.gate import CapabilityGate
from src.backend.core.security.capabilities.models import CapabilityRef

gate = CapabilityGate()
gate.declare(
    "credit_plugin",
    [
        CapabilityRef(name="db.read", scope="*"),
        CapabilityRef(name="ai.invoke", scope="*"),
    ],
)
```

## Step 3: Use two-layer check (per-invoke)

```python
from src.backend.core.security.capabilities.tool_policy_integration import (
    check_tool_with_policy,
)
from src.backend.core.ai.policy.spec import ToolsSpec
from src.backend.core.ai.policy.resolver import PolicyResolver

resolver = PolicyResolver(roots=[Path("ai_policies")])
policy = asyncio.run(resolver.resolve_specific("credit_check_v2", "premium_user"))

# At agent dispatch:
for tool_call in agent_response.tool_calls:
    check_tool_with_policy(
        gate=gate,
        plugin="credit_plugin",
        tool_name=tool_call.name,
        scope=tenant_id,
        policy=policy.tools,
    )
    # Raises CapabilityDeniedError OR ToolPolicyViolationError
    # If passes, proceed with tool execution
```

## Step 4: OR use pre-init filter (fail-closed)

```python
from src.backend.core.security.capabilities.tool_policy_integration import (
    filter_tools_with_gate,
)

allowed_tools = filter_tools_with_gate(
    gate=gate,
    plugin="credit_plugin",
    tool_names=all_available_tools,
    scope=tenant_id,
    policy=policy.tools,
)
agent = PydanticAI(tools=allowed_tools)
# Agent НИКОГДА не имеет disallowed tools в своём toolset
```

## Verification

```bash
# Test 1: Capability declared + in whitelist → OK
.venv/bin/python -c "
from src.backend.core.security.capabilities.gate import CapabilityGate
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.ai.policy.spec import ToolsSpec
from src.backend.core.security.capabilities.tool_policy_integration import check_tool_with_policy
g = CapabilityGate()
g.declare('plugin', [CapabilityRef(name='db.read', scope='*')])
check_tool_with_policy(gate=g, plugin='plugin', tool_name='db.read', scope='*', policy=ToolsSpec(whitelist=['db.read']))
print('OK: both layers passed')
"

# Test 2: Not declared → CapabilityDeniedError
# Test 3: Declared but not in whitelist → ToolPolicyViolationError
# Test 4: Whitelist match but excluded by blacklist → ToolPolicyViolationError (blacklist wins)
```

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `CapabilityDeniedError` | Tool not declared в gate | Add `CapabilityRef(name=tool, scope=...)` к `gate.declare(plugin, ...)` |
| `ToolPolicyViolationError` | Tool not in AIPolicySpec.tools whitelist | Edit `ai_policies/*.policy.yaml` `tools.whitelist` |
| `ValidationError: capability name` | Invalid name (must match `<resource>.<verb>`) | Use names like `db.read`, `ai.invoke` (2 parts only) |
| `scope_required=True` error | Capability needs explicit scope | Add `scope='*'` к CapabilityRef |

## Related

- **ADR-0067**: AI Policy Spec DSL
- **ADR-0161**: Sprint 79 closure (CapabilityGate + AIPolicySpec integration)
- **Cookbook #2**: Multi-instance outbox claim (related: lease-based atomicity)
