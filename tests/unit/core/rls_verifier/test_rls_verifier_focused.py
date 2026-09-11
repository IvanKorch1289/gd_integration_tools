"""Focused tests for ``core.rls_verifier`` (Wave 4 P0 #36)."""

from __future__ import annotations

import pytest

from src.backend.core.rls_verifier import (
    IsolationTestCase,
    IsolationTestResult,
    RLSVerifier,
    TenantContext,
    TenantIsolationChecker,
    get_rls_verifier,
)
from src.backend.core.rls_verifier.verifier import reset_rls_verifier


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_rls_verifier()


class TestTenantContext:
    def test_init(self) -> None:
        c = TenantContext(tenant_id="t1")
        assert c.user_id == ""
        assert c.role == ""
        assert c.is_admin is False
        assert c.allowed_tenants == []

    def test_full(self) -> None:
        c = TenantContext(
            tenant_id="t1",
            user_id="alice",
            role="admin",
            is_admin=True,
            allowed_tenants=["t1", "t2"],
        )
        assert c.role == "admin"


class TestRLSVerifierInit:
    def test_init(self) -> None:
        v = RLSVerifier()
        assert v is not None


class TestRLSVerifyQueryAdmin:
    def test_admin_bypass(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1", is_admin=True)
        # SELECT * без tenant filter — admin bypass.
        assert v.verify_query("SELECT * FROM users", ctx) is True


class TestRLSVerifyQueryForbidden:
    def test_select_star_no_where_denied(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1")
        assert v.verify_query("SELECT * FROM users", ctx) is False

    def test_delete_no_where_denied(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1")
        assert v.verify_query("DELETE FROM users", ctx) is False


class TestRLSVerifyQueryMissingTenant:
    def test_query_with_where_but_no_tenant_denied(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1")
        assert v.verify_query("SELECT id FROM users WHERE status = 'active'", ctx) is False


class TestRLSVerifyQueryWithTenant:
    def test_query_with_tenant_filter_allowed(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1")
        assert v.verify_query(
            "SELECT id FROM users WHERE tenant_id = :tenant AND status = 'active'",
            ctx,
        ) is True

    def test_query_with_where_tenant_allowed(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1")
        assert v.verify_query(
            "SELECT * FROM orders WHERE tenant = 't1'",
            ctx,
        ) is True

    def test_query_dollar_tenant_param(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1")
        assert v.verify_query(
            "SELECT * FROM x WHERE tenant_id = $1",
            ctx,
        ) is True


class TestRLSVerifyAccess:
    def test_admin_bypass(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1", is_admin=True)
        assert v.verify_access(resource_tenant_id="t999", context=ctx) is True

    def test_same_tenant_allowed(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1")
        assert v.verify_access(resource_tenant_id="t1", context=ctx) is True

    def test_cross_tenant_denied(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1")
        assert v.verify_access(resource_tenant_id="t2", context=ctx) is False

    def test_allowed_tenants_override(self) -> None:
        v = RLSVerifier()
        ctx = TenantContext(tenant_id="t1", allowed_tenants=["t1", "t2"])
        assert v.verify_access(resource_tenant_id="t2", context=ctx) is True
        assert v.verify_access(resource_tenant_id="t3", context=ctx) is False


class TestIsolationTestCase:
    def test_init(self) -> None:
        a = TenantContext(tenant_id="t1")
        b = TenantContext(tenant_id="t2")

        def loader(ctx):
            return []

        test = IsolationTestCase(
            name="t1_vs_t2",
            tenant_a=a,
            tenant_b=b,
            resource_loader=loader,
            expected_isolation=True,
        )
        assert test.expected_isolation is True


class TestIsolationTestResult:
    def test_defaults(self) -> None:
        r = IsolationTestResult(test_name="t1", passed=True)
        assert r.leaked_resources == []
        assert r.notes == ""


class TestTenantIsolationCheckerInit:
    def test_init(self) -> None:
        c = TenantIsolationChecker()
        assert c.results == []


class TestCheckerRunTest:
    def test_isolated_tenants_pass(self) -> None:
        c = TenantIsolationChecker()
        # Mock: each tenant sees own dict.
        resources_by_tenant = {"t1": {"a": 1}, "t2": {"b": 2}}

        def loader(ctx):
            return resources_by_tenant.get(ctx.tenant_id, {})

        test = IsolationTestCase(
            name="t1_vs_t2",
            tenant_a=TenantContext(tenant_id="t1"),
            tenant_b=TenantContext(tenant_id="t2"),
            resource_loader=loader,
        )
        result = c.run_test(test)
        assert result.passed is True
        assert result.leaked_resources == []

    def test_cross_tenant_leak_fails(self) -> None:
        c = TenantIsolationChecker()
        # Bug: tenant B sees tenant A's data.
        resources_by_tenant = {
            "t1": {"a": 1, "b": 2},
            "t2": {"a": 1, "c": 3},  # leak: "a" appears in both.
        }

        def loader(ctx):
            return resources_by_tenant.get(ctx.tenant_id, {})

        test = IsolationTestCase(
            name="t1_vs_t2",
            tenant_a=TenantContext(tenant_id="t1"),
            tenant_b=TenantContext(tenant_id="t2"),
            resource_loader=loader,
        )
        result = c.run_test(test)
        assert result.passed is False
        assert "a" in result.leaked_resources


class TestCheckerMatrix:
    def test_matrix_3_tenants(self) -> None:
        c = TenantIsolationChecker()
        resources = {"t1": {"a"}, "t2": {"b"}, "t3": {"c"}}

        def loader(ctx):
            return resources.get(ctx.tenant_id, set())

        tenants = [TenantContext(tenant_id=t) for t in ["t1", "t2", "t3"]]
        results = c.run_matrix(tenants, loader)
        # 3 tenants → 6 pairs (3*2).
        assert len(results) == 6
        assert all(r.passed for r in results)

    def test_matrix_with_leak(self) -> None:
        c = TenantIsolationChecker()
        resources = {
            "t1": {"shared", "a"},  # shared appears in multiple.
            "t2": {"shared", "b"},
            "t3": {"c"},
        }

        def loader(ctx):
            return resources.get(ctx.tenant_id, set())

        tenants = [TenantContext(tenant_id=t) for t in ["t1", "t2", "t3"]]
        results = c.run_matrix(tenants, loader)
        # Some pairs fail.
        assert not all(r.passed for r in results)


class TestCheckerResults:
    def test_results_accumulate(self) -> None:
        c = TenantIsolationChecker()
        c.run_test(IsolationTestCase(
            name="t1",
            tenant_a=TenantContext(tenant_id="t1"),
            tenant_b=TenantContext(tenant_id="t2"),
            resource_loader=lambda ctx: {},
        ))
        assert len(c.results) == 1

    def test_clear(self) -> None:
        c = TenantIsolationChecker()
        c.run_test(IsolationTestCase(
            name="t1",
            tenant_a=TenantContext(tenant_id="t1"),
            tenant_b=TenantContext(tenant_id="t2"),
            resource_loader=lambda ctx: {},
        ))
        c.clear()
        assert c.results == []


class TestSingleton:
    def test_singleton(self) -> None:
        v1 = get_rls_verifier()
        v2 = get_rls_verifier()
        assert v1 is v2

    def test_reset(self) -> None:
        v1 = get_rls_verifier()
        reset_rls_verifier()
        v2 = get_rls_verifier()
        assert v1 is not v2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import rls_verifier

        assert len(rls_verifier.__all__) == 6


class TestRealisticExample:
    def test_full_tenant_isolation_flow(self) -> None:
        """Realistic: verify no cross-tenant leak для orders table."""
        verifier = get_rls_verifier()
        ctx = TenantContext(tenant_id="t1")

        # 1. Verify SQL has tenant filter.
        safe_query = (
            "SELECT order_id FROM orders WHERE tenant_id = :tenant AND status = 'open'"
        )
        assert verifier.verify_query(safe_query, ctx) is True

        # 2. Unsafe query — no tenant filter.
        unsafe_query = "SELECT * FROM orders WHERE status = 'open'"
        assert verifier.verify_query(unsafe_query, ctx) is False

        # 3. Run matrix.
        checker = TenantIsolationChecker()
        tenant_a_orders = {"o1", "o2"}
        tenant_b_orders = {"o3"}

        def loader(ctx):
            return tenant_a_orders if ctx.tenant_id == "t1" else tenant_b_orders

        results = checker.run_matrix(
            [
                TenantContext(tenant_id="t1"),
                TenantContext(tenant_id="t2"),
            ],
            loader,
        )
        assert all(r.passed for r in results)
