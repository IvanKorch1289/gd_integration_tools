"""Contract Test Harness — runner (Wave 1 P0 #7)."""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Union

from src.backend.core.contract_testing.case import (
    CompatibilityTest,
    ContractTestCase,
    ContractTestResult,
)
from src.backend.core.contract_testing.validator import validate_against_schema

logger = logging.getLogger(__name__)

__all__ = ("ContractTestHarness", "get_contract_test_harness")

# Route function: ``def route(payload) -> dict`` or async ``async def route(payload) -> dict``.
RouteFn = Union[
    Callable[[Any], Any],
    Callable[[Any], Awaitable[Any]],
]


class ContractTestHarness:
    """Runner для contract tests."""

    def __init__(self) -> None:
        self._results: list[ContractTestResult] = []

    def run(
        self,
        test_case: ContractTestCase,
        route_fn: RouteFn,
    ) -> ContractTestResult:
        """Run one contract test.

        Args:
            test_case: :class:`ContractTestCase`.
            route_fn: sync или async callable (payload) -> output.

        Returns:
            :class:`ContractTestResult` с passed=True/False и details.

        """
        start = time.time()
        result = ContractTestResult(test_name=test_case.name, passed=True)
        try:
            output = self._invoke(route_fn, test_case.input_payload)
        except Exception as exc:
            # Error path.
            if test_case.expect_error:
                if test_case.error_type is None or isinstance(
                    exc, test_case.error_type
                ):
                    result.passed = True
                    result.expected_error = True
                else:
                    result.passed = False
                    result.actual_error = (
                        f"expected {test_case.error_type.__name__}, "
                        f"got {type(exc).__name__}: {exc}"
                    )
            else:
                # Unexpected error.
                result.passed = False
                result.actual_error = f"{type(exc).__name__}: {exc}"
            result.duration_ms = (time.time() - start) * 1000
            self._results.append(result)
            return result

        # Happy path — validate output.
        if test_case.expected_output_schema:
            schema_errors = validate_against_schema(
                output, test_case.expected_output_schema
            )
            if schema_errors:
                result.passed = False
                result.schema_errors = schema_errors

        if test_case.expected_output is not None:
            if output != test_case.expected_output:
                result.passed = False
                result.output_mismatch = True

        result.duration_ms = (time.time() - start) * 1000
        self._results.append(result)
        return result

    def run_suite(
        self,
        test_cases: list[ContractTestCase],
        route_fn: RouteFn,
    ) -> list[ContractTestResult]:
        """Run multiple contract tests."""
        return [self.run(tc, route_fn) for tc in test_cases]

    def run_compatibility(
        self,
        compat: CompatibilityTest,
        route_fn: RouteFn,
    ) -> ContractTestResult:
        """Verify backward-compat: old_payload should still work."""
        # Reuse ContractTestCase semantics.
        tc_old = ContractTestCase(
            name=f"{compat.name}_legacy",
            input_payload=compat.old_payload,
            expected_output_schema={},  # no strict schema check
        )
        result = self.run(tc_old, route_fn)
        if not result.passed:
            result.test_name = f"{compat.name}_compat_v{compat.contract_version}"
        return result

    @property
    def history(self) -> list[ContractTestResult]:
        """История всех прогонов."""
        return list(self._results)

    def clear_history(self) -> None:
        self._results.clear()

    def _invoke(self, route_fn: RouteFn, payload: Any) -> Any:
        """Invoke sync or async route_fn."""
        import asyncio
        import inspect

        result = route_fn(payload)
        if inspect.iscoroutine(result):
            # Run async to completion.
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Create a task in the running loop and wait.
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        future = ex.submit(
                            asyncio.run, self._await_coro(result)
                        )
                        return future.result()
                else:
                    return loop.run_until_complete(result)
            except RuntimeError:
                return asyncio.run(self._await_coro(result))
        return result

    async def _await_coro(self, coro: Any) -> Any:
        return await coro


_harness: ContractTestHarness | None = None


def get_contract_test_harness() -> ContractTestHarness:
    global _harness
    if _harness is None:
        _harness = ContractTestHarness()
    return _harness


def reset_contract_test_harness() -> None:
    global _harness
    _harness = None
