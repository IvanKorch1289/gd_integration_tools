# Cookbook 03: Secure AI Code Execution with E2B Sandbox

**Sprint**: S75
**ADR**: [ADR-0157](../adr/0157-sprint-75-e2b-kernelspec-closure.md)
**Status**: Production-ready

## Use Case

AI agent получил задачу "посчитать статистику по CSV и построить график".
Прямое выполнение в production Python — **небезопасно**: agent может сгенерировать
`os.system("rm -rf /")` или бесконечный цикл. E2B даёт изолированный sandbox.

## Solution

`E2BExecutionBackend` (S75 W1) + `ExecutionBackendFactory` (S74 W2) +
`KernelSpecDiscovery` (S75 W3) = composable multi-backend stack.

## Recipe

### Step 1: Add e2b to dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
ai = [
    "e2b-code-interpreter>=0.0.25",
    "litellm>=1.50.0",  # S80: LLM gateway pool
]
```

### Step 2: Configure backend

```yaml
# config/jupyter.yaml
backends:
  default: nbclient          # local, eager
  agent_code_execution: e2b  # sandbox, lazy
e2b:
  api_key_env: E2B_API_KEY
  timeout_seconds: 30
  kernel: python3
```

### Step 3: Use in code

```python
from gd_integration_tools.infrastructure.clients.jupyter import (
    ExecutionBackendFactory, BackendKind
)
from gd_integration_tools.core.config.services.jupyter import jupyter_settings

backend = ExecutionBackendFactory.create(
    BackendKind.E2B, jupyter_settings.e2b
)
result = await backend.execute_cell("import pandas as pd; df = pd.read_csv('/data/x.csv'); df.describe()")
# result.output: "{       x  \\n count  100.0  \\n mean   42.3  ..."
```

### Step 4: Combine with KernelSpecDiscovery

```python
from gd_integration_tools.infrastructure.clients.jupyter.kernel_discovery import (
    KernelSpecDiscovery
)

# Discover locally-installed kernels
kernels = await KernelSpecDiscovery.list_kernels()
# -> [KernelSpec(name="python3", language="python", ...), KernelSpec(name="ir", language="R", ...)]

# Use discovered kernel in E2B
e2b_kernel = next(k for k in kernels if k.name == "python3")
backend = ExecutionBackendFactory.create(BackendKind.E2B, kernel=e2b_kernel)
```

## Key Points

- **Lazy import** — E2B SDK грузится только когда `BackendKind.E2B` выбран
- **Sandbox per cell** — каждый `execute_cell()` создаёт fresh sandbox,
  гарантируя clean state (no cross-cell state leaks)
- **Timeout enforced** — `timeout_seconds=30` hard-kill в sandbox
- **Resource quota** — e2b sandboxes считаются per-tenant (P1 #5 follow-up)

## Related

- `01-ai-agent-tools-whitelist.md` — agent policy для tools filter
- `04-circuit-breaker-middleware.md` — resilience для repeated E2B failures
