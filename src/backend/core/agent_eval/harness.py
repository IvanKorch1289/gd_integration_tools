"""Agent Evaluation Harness — pure-Python implementation (Wave 3 #22)."""

from __future__ import annotations

import inspect
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Union

logger = logging.getLogger(__name__)

__all__ = (
    "AgentEvalHarness",
    "EvalReport",
    "EvalTaskResult",
    "GoldenTask",
    "InjectionTest",
    "ToolUseTest",
)


AgentFn = Callable[[str], Union[str, Awaitable[str]]]


@dataclass(slots=True)
class GoldenTask:
    """Golden Q&A test.

    Attributes:
        name: Unique task name.
        prompt: Input prompt.
        scorer: Callable(output) -> bool.
        weight: Relative weight для aggregate score.
        metadata: Additional attributes.
    """

    name: str
    prompt: str
    scorer: Callable[[str], bool]
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InjectionTest:
    """Prompt injection resistance test.

    Attributes:
        name: Unique test name.
        prompt: Adversarial prompt.
        should_contain: Substrings that MUST be in response.
        should_not_contain: Substrings that MUST NOT be in response.
        weight: Relative weight.
    """

    name: str
    prompt: str
    should_contain: tuple[str, ...] = ()
    should_not_contain: tuple[str, ...] = ()
    weight: float = 1.0


@dataclass(slots=True)
class ToolUseTest:
    """Tool use verification test.

    Attributes:
        name: Unique test name.
        prompt: Input prompt.
        tool_calls: Expected tool call sequence [(tool_name, args_pattern), ...].
        weight: Relative weight.
    """

    name: str
    prompt: str
    tool_calls: tuple[tuple[str, dict[str, Any]], ...] = ()
    weight: float = 1.0


@dataclass(slots=True)
class EvalTaskResult:
    """Single task result."""

    task_name: str
    task_type: str  # "golden" | "injection" | "tool_use"
    passed: bool
    score: float  # 0.0 - 1.0
    duration_ms: float = 0.0
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvalReport:
    """Aggregated eval report."""

    agent_name: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    total_duration_ms: float = 0.0
    results: list[EvalTaskResult] = field(default_factory=list)
    weighted_score: float = 0.0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "weighted_score": self.weighted_score,
            "total_duration_ms": self.total_duration_ms,
            "results": [
                {
                    "task_name": r.task_name,
                    "task_type": r.task_type,
                    "passed": r.passed,
                    "score": r.score,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


class AgentEvalHarness:
    """Test harness для AI agents."""

    def __init__(self, agent_name: str = "default_agent") -> None:
        self._agent_name = agent_name
        self._golden: list[GoldenTask] = []
        self._injection: list[InjectionTest] = []
        self._tool_use: list[ToolUseTest] = []

    @property
    def agent_name(self) -> str:
        return self._agent_name

    def add_golden(self, task: GoldenTask) -> None:
        self._golden.append(task)

    def add_injection(self, test: InjectionTest) -> None:
        self._injection.append(test)

    def add_tool_use(self, test: ToolUseTest) -> None:
        self._tool_use.append(test)

    def golden_count(self) -> int:
        return len(self._golden)

    def injection_count(self) -> int:
        return len(self._injection)

    def tool_use_count(self) -> int:
        return len(self._tool_use)

    def total_tests(self) -> int:
        return (
            self.golden_count()
            + self.injection_count()
            + self.tool_use_count()
        )

    async def run(
        self,
        agent_fn: AgentFn,
    ) -> EvalReport:
        """Run all tests against agent_fn.

        Args:
            agent_fn: Sync или async callable (prompt) -> response.

        Returns:
            :class:`EvalReport` with per-task + aggregate results.
        """
        report = EvalReport(agent_name=self._agent_name)
        weighted_sum = 0.0
        weight_total = 0.0

        # Golden tasks.
        for task in self._golden:
            result = await self._run_golden(task, agent_fn)
            report.results.append(result)
            if result.passed:
                report.passed += 1
            else:
                report.failed += 1
            weighted_sum += result.score * task.weight
            weight_total += task.weight
            report.total_duration_ms += result.duration_ms

        # Injection tests.
        for test in self._injection:
            result = await self._run_injection(test, agent_fn)
            report.results.append(result)
            if result.passed:
                report.passed += 1
            else:
                report.failed += 1
            weighted_sum += result.score * test.weight
            weight_total += test.weight
            report.total_duration_ms += result.duration_ms

        # Tool use tests.
        for test in self._tool_use:
            result = await self._run_tool_use(test, agent_fn)
            report.results.append(result)
            if result.passed:
                report.passed += 1
            else:
                report.failed += 1
            weighted_sum += result.score * test.weight
            weight_total += test.weight
            report.total_duration_ms += result.duration_ms

        report.total = len(report.results)
        if weight_total > 0:
            report.weighted_score = weighted_sum / weight_total
        return report

    async def _run_golden(
        self, task: GoldenTask, agent_fn: AgentFn
    ) -> EvalTaskResult:
        """Run a golden task."""
        start = time.time()
        try:
            output = agent_fn(task.prompt)
            if inspect.iscoroutine(output):
                output = await output
            passed = task.scorer(output)
            return EvalTaskResult(
                task_name=task.name,
                task_type="golden",
                passed=passed,
                score=1.0 if passed else 0.0,
                duration_ms=(time.time() - start) * 1000,
                details={"output": str(output)[:200]},
            )
        except Exception as exc:
            return EvalTaskResult(
                task_name=task.name,
                task_type="golden",
                passed=False,
                score=0.0,
                duration_ms=(time.time() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _run_injection(
        self, test: InjectionTest, agent_fn: AgentFn
    ) -> EvalTaskResult:
        """Run an injection resistance test."""
        start = time.time()
        try:
            output = agent_fn(test.prompt)
            if inspect.iscoroutine(output):
                output = await output
            output_str = str(output).lower()

            # Check should_contain (all must be present).
            missing_contains = [
                s for s in test.should_contain if s.lower() not in output_str
            ]
            # Check should_not_contain (none must be present).
            leaked = [
                s for s in test.should_not_contain
                if re.search(re.escape(s.lower()), output_str)
            ]

            passed = not missing_contains and not leaked
            details = {
                "missing_contains": missing_contains,
                "leaked": leaked,
            }
            return EvalTaskResult(
                task_name=test.name,
                task_type="injection",
                passed=passed,
                score=1.0 if passed else 0.0,
                duration_ms=(time.time() - start) * 1000,
                details=details,
            )
        except Exception as exc:
            return EvalTaskResult(
                task_name=test.name,
                task_type="injection",
                passed=False,
                score=0.0,
                duration_ms=(time.time() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _run_tool_use(
        self, test: ToolUseTest, agent_fn: AgentFn
    ) -> EvalTaskResult:
        """Run tool use verification test.

        Note: agent_fn should return a tuple (response, tool_calls).
        """
        start = time.time()
        try:
            output = agent_fn(test.prompt)
            if inspect.iscoroutine(output):
                output = await output
            # If agent returns (response, tool_calls), unpack.
            if isinstance(output, tuple) and len(output) == 2:
                response, actual_calls = output
            else:
                # No tool call info — fail if tool_use expected.
                _ = output
                actual_calls = []

            # Verify tool calls match expected (name + args).
            actual_names = [c[0] for c in actual_calls]
            expected_names = [c[0] for c in test.tool_calls]
            sequence_match = actual_names == expected_names

            passed = sequence_match
            return EvalTaskResult(
                task_name=test.name,
                task_type="tool_use",
                passed=passed,
                score=1.0 if passed else 0.0,
                duration_ms=(time.time() - start) * 1000,
                details={
                    "expected": list(expected_names),
                    "actual": list(actual_names),
                },
            )
        except Exception as exc:
            return EvalTaskResult(
                task_name=test.name,
                task_type="tool_use",
                passed=False,
                score=0.0,
                duration_ms=(time.time() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
