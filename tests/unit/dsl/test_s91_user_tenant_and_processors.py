"""S91 W4 — User TenantMixin + processors 'del context' fix regression tests.

V2 P0 #6 continue: User тепер TenantMixin subclass (2/7 моделей).
V2 P0 #7 fix: 10 processors замість 'del context' використовують '_ = context'.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# V2 P0 #6: User TenantMixin
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_user_is_tenant_aware() -> None:
    """User успадковує TenantMixin → _is_tenant_aware повертає True."""
    from extensions.core_entities.users.domain.models import User
    from src.backend.infrastructure.database.tenant_filter import _is_tenant_aware

    assert _is_tenant_aware(User) is True


@pytest.mark.unit
def test_user_mro_includes_tenant_mixin() -> None:
    """User MRO містить TenantMixin перед BaseModel."""
    from extensions.core_entities.users.domain.models import User

    mro_names = [cls.__name__ for cls in User.__mro__]
    assert "TenantMixin" in mro_names
    assert "BaseModel" in mro_names
    # TenantMixin має бути ПІСЛЯ BaseModel в MRO
    assert mro_names.index("TenantMixin") > mro_names.index("BaseModel")


@pytest.mark.unit
def test_user_tenant_id_column_present() -> None:
    """User має tenant_id mapped_column через TenantMixin."""
    from sqlalchemy import inspect

    from extensions.core_entities.users.domain.models import User

    mapper = inspect(User)
    columns = {col.key for col in mapper.columns}
    assert "tenant_id" in columns


# ---------------------------------------------------------------------------
# V2 P0 #7: 10 processors 'del context' → '_ = context'
# ---------------------------------------------------------------------------


PROCESSOR_FILES_WITH_CONTEXT = [
    "src.backend.dsl.engine.processors.agent_dsl.memory_recall",
    "src.backend.dsl.engine.processors.agent_dsl.memory_store",
    "src.backend.dsl.engine.processors.agent_dsl.reflection_loop",
    "src.backend.dsl.engine.processors.agent_dsl.plan_execute",
    "src.backend.dsl.engine.processors.agent_dsl.agent_run",
    "src.backend.dsl.engine.processors.agent_dsl.pii_mask",
    "src.backend.dsl.engine.processors.agent_dsl.pii_unmask",
    "src.backend.dsl.engine.processors.agent_dsl.guardrails_apply",
    "src.backend.dsl.engine.processors.agent_dsl.mcp_tool",
    "src.backend.dsl.engine.processors.ml_predict",
]


@pytest.mark.unit
def test_no_processor_uses_del_context() -> None:
    """Жоден з 10 processors не використовує 'del context' (regression S91 W3)."""
    import importlib
    import inspect

    for module_name in PROCESSOR_FILES_WITH_CONTEXT:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        assert "del context" not in source, (
            f"{module_name} still has 'del context' — should be '_ = context'"
        )


@pytest.mark.unit
def test_processors_use_underscore_context() -> None:
    """Кожен з 10 processors використовує '_ = context' explicit discard."""
    import importlib
    import inspect

    count = 0
    for module_name in PROCESSOR_FILES_WITH_CONTEXT:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        if "_ = context" in source or "_=context" in source:
            count += 1

    assert count == 10, f"Expected 10 processors with '_ = context', found {count}"


@pytest.mark.unit
def test_processors_signature_intact() -> None:
    """Сигнатура _run/process(self, exchange, context) збережена у всіх 10 processors."""
    import ast
    import importlib
    import inspect

    for module_name in PROCESSOR_FILES_WITH_CONTEXT:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        tree = ast.parse(source)
        found_method = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in (
                "_run",
                "process",
            ):
                args = [a.arg for a in node.args.args]
                assert args == ["self", "exchange", "context"], (
                    f"{module_name}.{node.name} signature changed: {args}"
                )
                found_method = True
        assert found_method, f"{module_name} has no _run/process method"
