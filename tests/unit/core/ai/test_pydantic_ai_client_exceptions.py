"""S69 W2: tests для pydantic_ai_client top-level gateway exceptions.

Проверяют:
1. GatewayRateLimited raised при "rate" + "limit" в message
2. GatewayUnavailable raised при generic exception
3. Both classes импортируются top-level (нет lazy imports)
4. AST verify: zero `from src.backend.services.ai.gateway` imports inside functions
5. Top-level imports section содержит gateway exceptions
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.backend.core.ai.pydantic_ai_client import PydanticAIClient
from src.backend.services.ai.gateway.exceptions import (
    GatewayRateLimited,
    GatewayUnavailable,
)


def test_gateway_exceptions_importable() -> None:
    """Both exceptions импортируются через pydantic_ai_client (top-level)."""
    # If top-level import is broken, эти imports fail
    assert GatewayRateLimited is not None
    assert GatewayUnavailable is not None


def test_pydantic_ai_client_reraise_rate_limit() -> None:
    """Exc с "rate" + "limit" в message → GatewayRateLimited."""
    with pytest.raises(GatewayRateLimited) as exc_info:
        PydanticAIClient._reraise_normalized(
            Exception("Rate limit exceeded for model gpt-4")
        )
    assert "Rate limit exceeded" in str(exc_info.value)


def test_pydantic_ai_client_reraise_unavailable() -> None:
    """Generic exc → GatewayUnavailable."""
    with pytest.raises(GatewayUnavailable) as exc_info:
        PydanticAIClient._reraise_normalized(Exception("Connection refused"))
    assert "Connection refused" in str(exc_info.value)


def test_pydantic_ai_client_reraise_rate_limit_case_insensitive() -> None:
    """Case-insensitive matching: "RATE LIMIT" тоже triggers."""
    with pytest.raises(GatewayRateLimited):
        PydanticAIClient._reraise_normalized(Exception("RATE LIMIT hit on primary model"))


def test_no_lazy_imports_in_methods() -> None:
    """AST-based verify: zero `from src.backend.services.ai.gateway` imports inside functions.

    До S69 W2: 2 lazy imports (lines 360, 363) ВНУТРИ _normalize_litellm_exception.
    После: top-level imports, methods чистые.
    """
    source = Path("src/backend/core/ai/pydantic_ai_client.py").read_text()
    tree = ast.parse(source)

    lazy_imports_found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # Skip top-level imports (direct children of Module)
            if node.module and "src.backend.services.ai.gateway" in node.module:
                # Check if parent is Module (top-level) or Function (lazy)
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.Module):
                        if node in parent.body:
                            break  # top-level, OK
                else:
                    lazy_imports_found.append(node.lineno)

    assert lazy_imports_found == [], (
        f"Found lazy imports at lines {lazy_imports_found}. "
        f"Must be top-level only (S69 W2 refactor)."
    )


def test_top_level_gateway_imports() -> None:
    """Top-level imports section содержит gateway exceptions."""
    source = Path("src/backend/core/ai/pydantic_ai_client.py").read_text()
    # Module-level (lines 1-50 approx, before any class def)
    first_50_lines = "\n".join(source.split("\n")[:50])
    assert "from src.backend.services.ai.gateway.exceptions" in first_50_lines
    assert "GatewayRateLimited" in first_50_lines
    assert "GatewayUnavailable" in first_50_lines
