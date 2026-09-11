"""RLS Verifier + Tenant Isolation Checker (Wave 4 P0 #36)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = (
    "IsolationTestCase",
    "IsolationTestResult",
    "RLSVerifier",
    "TenantContext",
    "TenantIsolationChecker",
    "get_rls_verifier",
)


@dataclass(slots=True)
class TenantContext:
    """Tenant context для RLS verification."""

    tenant_id: str
    user_id: str = ""
    role: str = ""
    is_admin: bool = False
    allowed_tenants: list[str] = field(default_factory=list)


@dataclass(slots=True)
class IsolationTestCase:
    """Один property-based test cross-tenant isolation."""

    name: str
    tenant_a: TenantContext
    tenant_b: TenantContext
    resource_loader: Callable[[TenantContext], Any]
    expected_isolation: bool = True


@dataclass(slots=True)
class IsolationTestResult:
    """Результат matrix test."""

    test_name: str
    passed: bool
    leaked_resources: list[Any] = field(default_factory=list)
    notes: str = ""


class RLSVerifier:
    """Static + runtime verification multi-tenant queries."""

    FORBIDDEN_PATTERNS = (
        re.compile(r"SELECT\s+\*\s+FROM\s+\w+\s*(?:;|$)", re.IGNORECASE),
        # SELECT * without WHERE.
        re.compile(r"DELETE\s+FROM\s+\w+\s*(?!.*WHERE)", re.IGNORECASE),
        # DELETE without WHERE.
    )

    TENANT_FILTER_PATTERNS = (
        re.compile(r"\btenant_id\s*=\s*[:$@]", re.IGNORECASE),
        re.compile(r"\bWHERE\s+.*tenant", re.IGNORECASE),
    )

    def verify_query(
        self, query: str, context: TenantContext
    ) -> bool:
        """Verify query respects tenant isolation.

        Returns:
            True если query is safe (has tenant filter).
            False если query может leak cross-tenant.

        """
        # Admins bypass RLS.
        if context.is_admin:
            return True

        # Check for forbidden patterns.
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern.search(query):
                logger.warning(
                    "RLSVerifier: forbidden pattern in query: %s", query[:100]
                )
                return False

        # Must have tenant_id filter.
        has_tenant_filter = any(
            p.search(query) for p in self.TENANT_FILTER_PATTERNS
        )
        if not has_tenant_filter:
            logger.warning(
                "RLSVerifier: missing tenant filter in query: %s", query[:100]
            )
            return False

        return True

    def verify_access(
        self,
        *,
        resource_tenant_id: str,
        context: TenantContext,
    ) -> bool:
        """Verify context can access resource."""
        if context.is_admin:
            return True
        if context.allowed_tenants:
            return resource_tenant_id in context.allowed_tenants
        return resource_tenant_id == context.tenant_id


class TenantIsolationChecker:
    """Property-based matrix tester."""

    def __init__(self) -> None:
        self._results: list[IsolationTestResult] = []

    def run_test(self, test: IsolationTestCase) -> IsolationTestResult:
        """Run single isolation test."""
        # Load resources for tenant A.
        resources_a = test.resource_loader(test.tenant_a)
        # Verify tenant B doesn't see them.
        resources_b = test.resource_loader(test.tenant_b)
        # Resources from A shouldn't appear in B's view.
        leaked: list[Any] = []
        if test.expected_isolation:
            ids_a = self._extract_ids(resources_a)
            ids_b = self._extract_ids(resources_b)
            intersection = ids_a & ids_b
            if intersection:
                leaked = list(intersection)

        result = IsolationTestResult(
            test_name=test.name,
            passed=(not leaked) if test.expected_isolation else (len(resources_b) > 0),
            leaked_resources=leaked,
        )
        self._results.append(result)
        return result

    def run_matrix(
        self,
        tenants: list[TenantContext],
        resource_loader: Callable[[TenantContext], Any],
    ) -> list[IsolationTestResult]:
        """Run all-pairs matrix."""
        results = []
        for i, a in enumerate(tenants):
            for j, b in enumerate(tenants):
                if i == j:
                    continue
                test = IsolationTestCase(
                    name=f"{a.tenant_id}_vs_{b.tenant_id}",
                    tenant_a=a,
                    tenant_b=b,
                    resource_loader=resource_loader,
                )
                results.append(self.run_test(test))
        return results

    def _extract_ids(self, resources: Any) -> set[Any]:
        """Extract IDs из resources."""
        if isinstance(resources, dict):
            return set(resources.keys())
        if isinstance(resources, list):
            return set(range(len(resources)))
        if isinstance(resources, set):
            return resources
        return set()

    @property
    def results(self) -> list[IsolationTestResult]:
        return list(self._results)

    def clear(self) -> None:
        self._results.clear()


_verifier: RLSVerifier | None = None


def get_rls_verifier() -> RLSVerifier:
    global _verifier
    if _verifier is None:
        _verifier = RLSVerifier()
    return _verifier


def reset_rls_verifier() -> None:
    global _verifier
    _verifier = None
