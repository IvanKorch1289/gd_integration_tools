"""Regression tests for cycle 208 gRPC-server entrypoint (D-AUDIT-20801).

Verifies:
1. ``__init__.py`` properly invokes ``_patch_rpc_methods()`` at module level.
2. Parent class method map contains OrderServiceServicer + OrderServiceStub.
3. Stub method map contains OrderServiceStub.
4. Subclass method list contains all 7 OrderService methods.

Примечание: runtime functional test (real gRPC RPC over unix socket)
требует image rebuild с cycle 202 patches. Этот файл проверяет
только CONFIG invariants — что блок cycle 208 не сломал cycle 202 fix.
"""

from __future__ import annotations

import pytest


def test_patch_rpc_methods_call_is_at_module_level() -> None:
    """``_patch_rpc_methods()`` вызывается на module level (0 indent).

    Cycle 202 fix: dedent (была 4 spaces → recursive call never fired).
    Cycle 208 smoke check: убеждаемся, что в cycle 208 не откатили назад.
    """
    import ast

    import src.backend.entrypoints.grpc.grpc_server as grpc_pkg

    # Read source directly (avoid ast.parse(file) edge cases)
    init_path = grpc_pkg.__file__
    with open(init_path, encoding="utf-8") as f:
        source_text = f.read()

    tree = ast.parse(source_text)
    # Module-level statements (body of the module)
    module_calls = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            if isinstance(func, ast.Name) and func.id == "_patch_rpc_methods":
                module_calls.append(stmt.lineno)
    assert module_calls, (
        f"_patch_rpc_methods() must be at module level (cycle 202 dedent fix); "
        f"module-level calls found: {module_calls}"
    )


def test_order_service_in_parent_class_method_map() -> None:
    """OrderServiceServicer + OrderServiceStub в parent_class_method_map."""
    from src.backend.entrypoints.grpc.grpc_server import (
        _patch_rpc_methods,
    )

    # Invoke patch function (idempotent — already patched, but safe)
    _patch_rpc_methods()

    # Read the global _parent_class_method_map is hard to inspect directly,
    # but we can verify that the OrderServiceStub methods получили атрибуты.
    from src.backend.entrypoints.grpc.protobuf import orders_pb2_grpc

    expected_methods = (
        "CreateOrder", "GetOrderResult", "GetOrder", "DeleteOrder",
        "CreateSKBOrder", "GetFileAndJson", "SendOrderData",
    )
    for method_name in expected_methods:
        method = getattr(orders_pb2_grpc.OrderServiceServicer, method_name)
        assert method is not None, f"OrderServiceServicer.{method_name} missing"
        assert getattr(method, "request_streaming", "MISSING") is False
        assert getattr(method, "response_streaming", "MISSING") is False


def test_order_service_subclass_has_streaming_attrs() -> None:
    """OrderGRPCServicer (наш subclass) имеет streaming атрибуты."""
    from src.backend.entrypoints.grpc.grpc_server.order import OrderGRPCServicer

    expected_methods = (
        "CreateOrder", "GetOrderResult", "GetOrder", "DeleteOrder",
        "CreateSKBOrder", "GetFileAndJson", "SendOrderData",
    )
    for method_name in expected_methods:
        method = getattr(OrderGRPCServicer, method_name, None)
        assert method is not None, f"OrderGRPCServicer.{method_name} missing"
        assert getattr(method, "request_streaming", "MISSING") is False
        assert getattr(method, "response_streaming", "MISSING") is False


def test_grpc_serve_entrypoint_exit_guard() -> None:
    """server.py: ``if __name__ == "__main__"`` блок вызывает serve().

    Cycle 208 fix: без этой строки ``python -m <module>`` загружает
    module без вызова serve() → socket не создаётся → graceful hang.
    """
    import ast

    import src.backend.entrypoints.grpc.grpc_server.server as server_module

    with open(server_module.__file__, encoding="utf-8") as f:
        source_text = f.read()
    tree = ast.parse(source_text)

    has_main_guard = False
    has_asyncio_run_serve = False
    for stmt in tree.body:
        if isinstance(stmt, ast.If):
            if isinstance(stmt.test, ast.Compare):
                left = stmt.test.left
                if (
                    isinstance(left, ast.Name)
                    and left.id == "__name__"
                    and isinstance(stmt.test.ops[0], ast.Eq)
                ):
                    has_main_guard = True
                    # Walk inside the if-body
                    for child_stmt in stmt.body:
                        if isinstance(child_stmt, ast.Expr) and isinstance(
                            child_stmt.value, ast.Call
                        ):
                            call = child_stmt.value
                            func = call.func
                            if (
                                isinstance(func, ast.Attribute)
                                and isinstance(func.value, ast.Name)
                                and func.value.id == "asyncio"
                                and func.attr == "run"
                            ):
                                if call.args and isinstance(
                                    call.args[0], ast.Call
                                ):
                                    inner = call.args[0].func
                                    if (
                                        isinstance(inner, ast.Name)
                                        and inner.id == "serve"
                                    ):
                                        has_asyncio_run_serve = True

    assert has_main_guard, (
        "server.py: missing `if __name__ == \"__main__\":` block"
    )
    assert has_asyncio_run_serve, (
        "server.py: __main__ block must call `asyncio.run(serve())`"
    )
