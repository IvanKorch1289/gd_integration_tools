"""S77 W2 — JSON-Schema export для AIPolicySpec (P0-C closure, ADR-0067).

FINAL_REPORT_V2 P0-C: AIPolicySpec нуждается в JSON-Schema export
для external tools (admin UI form generation, IDE autocomplete,
config validation, MCP gateway documentation).

**Design**:
* :func:`export_aipolicy_json_schema` — возвращает JSON Schema
  representation of :class:`AIPolicySpec` (Pydantic v2 built-in).
* :func:`validate_aipolicy_dict` — validates arbitrary dict against
  generated schema (для external YAML/JSON config validation без
  Pydantic dep).
* :func:`export_default_policy_yaml` — generates example YAML для
  admin docs / starter templates.

**Use case** (FINAL_REPORT_V2 P0-C):
```python
from src.backend.core.ai.policy.jsonschema_export import (
    export_aipolicy_json_schema,
)

schema = export_aipolicy_json_schema()
# Use in: OpenAPI spec, MCP tool documentation, admin UI forms
```

**Output format** (Pydantic v2 ``model_json_schema()``):
```json
{
  "type": "object",
  "properties": {
    "name": {"type": "string"},
    "workflow_pattern": {"type": "string"},
    "tools": {
      "type": "object",
      "properties": {
        "whitelist": {"type": "array", "items": {"type": "string"}},
        "blacklist": {"type": "array", "items": {"type": "string"}},
        "on_violation": {"enum": ["fail", "warn", "block"]}
      }
    }
  },
  "required": ["name", "workflow_pattern", "model_router"]
}
```
"""

from __future__ import annotations
from src.backend.core.logging import get_logger


from typing import Any

from src.backend.core.ai.policy.spec import AIPolicySpec

logger = get_logger(__name__)


__all__ = (
    "export_aipolicy_json_schema",
    "export_default_policy_yaml",
    "validate_aipolicy_dict",
)


def export_aipolicy_json_schema() -> dict[str, Any]:
    """Export :class:`AIPolicySpec` as JSON Schema (draft 2020-12).

    Wraps Pydantic v2 ``model.model_json_schema()``. Use case:
    admin UI form generation, MCP tool docs, IDE autocomplete,
    external config validation tools.

    Returns:
        JSON-Schema dict (Pydantic default format — compatible с
        jsonschema library, ajv, etc.).
    """
    return AIPolicySpec.model_json_schema()


def validate_aipolicy_dict(data: dict[str, Any]) -> AIPolicySpec:
    """Validate arbitrary dict against :class:`AIPolicySpec` schema.

    Convenience function — equivalent to
    ``AIPolicySpec.model_validate(data)`` but explicit name для
    external config validation use cases.

    Args:
        data: dict representing AIPolicySpec (typically from YAML
            or JSON file).

    Returns:
        Validated :class:`AIPolicySpec` instance.

    Raises:
        pydantic.ValidationError: если dict не соответствует schema.
    """
    return AIPolicySpec.model_validate(data)


def export_default_policy_yaml() -> str:
    """Generate example YAML для admin docs / starter templates.

    Returns:
        YAML string с minimal example — tenant admin копирует
        и модифицирует.

    Example output:
        ```yaml
        name: my_workflow_policy
        version: 1
        workflow_pattern: my_workflow_*
        tenant_pattern: "*"
        model_router:
          primary: openai/gpt-4o-mini
          fallback:
            - openrouter/anthropic/claude-3.5-sonnet
          timeout_s: 30.0
          retry_attempts: 2
        input_sanitizers: []
        input_guards: []
        output_guards: []
        output_sanitizers: []
        budget:
          max_tokens_prompt: 8000
          max_tokens_completion: 2000
          max_cost_usd: 0.5
          ttl_s: 3600
        tools:
          whitelist: []
          blacklist: []
          on_violation: fail
        required: true
        ```
    """
    return """name: my_workflow_policy
version: 1
workflow_pattern: my_workflow_*
tenant_pattern: "*"
model_router:
  primary: openai/gpt-4o-mini
  fallback:
    - openrouter/anthropic/claude-3.5-sonnet
  timeout_s: 30.0
  retry_attempts: 2
input_sanitizers: []
input_guards: []
output_guards: []
output_sanitizers: []
budget:
  max_tokens_prompt: 8000
  max_tokens_completion: 2000
  max_cost_usd: 0.5
  ttl_s: 3600
audit:
  extra_attrs: {}
  schema_version: 1
tools:
  whitelist: []
  blacklist: []
  on_violation: fail
required: true
"""
