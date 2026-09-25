"""Unit-тесты check_deadline_propagation.py (Sprint 12, ADR-0305).

Тестирует статический анализатор, который проверяет полноту интеграции
``RequestContext.deadline_budget`` в DSL processors.

Покрываемые функции:
- ``_find_wait_for_calls``: AST-поиск ``asyncio.wait_for`` вызовов.
- ``_file_has_text``: generic text search для deadline references.
- ``_file_has_admission_control``: эвристика для admission control блока.
- ``_file_has_narrowing``: эвристика для timeout narrowing.
- ``classify_processor``: основная классификация файла.
- ``scan``: full scan ``src/backend/dsl/engine/processors/``.
- ``render_human`` / ``render_json``: output форматы.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# tools/checks/ — добавлено в sys.path для импорта checker.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

from checks.check_deadline_propagation import (  # noqa: E402
    ProcessorStatus,
    _file_has_admission_control,
    _file_has_narrowing,
    _file_has_text,
    _find_wait_for_calls,
    classify_processor,
    render_human,
    render_json,
)


def _write(tmp_path: Path, name: str, src: str) -> Path:
    """Записать файл и вернуть путь."""
    path = tmp_path / name
    path.write_text(src, encoding="utf-8")
    return path


# ============================================================================
# _find_wait_for_calls: AST-поиск
# ============================================================================


class TestFindWaitForCalls:
    """``_find_wait_for_calls`` находит ``asyncio.wait_for(...)`` через AST."""

    def test_no_wait_for_returns_empty(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "p.py", "x = 1\ny = 2\n")
        assert _find_wait_for_calls(path) == []

    def test_finds_single_wait_for(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            "import asyncio\nawait asyncio.wait_for(coro, timeout=10.0)\n",
        )
        calls = _find_wait_for_calls(path)
        assert len(calls) == 1
        assert calls[0].line == 2

    def test_finds_multiple_wait_for(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            (
                "import asyncio\n"
                "await asyncio.wait_for(coro1, timeout=1.0)\n"
                "await asyncio.wait_for(coro2, timeout=2.0)\n"
            ),
        )
        calls = _find_wait_for_calls(path)
        assert len(calls) == 2
        assert [c.line for c in calls] == [2, 3]

    def test_ignores_non_asyncio_wait_for(self, tmp_path: Path) -> None:
        """``my.wait_for`` НЕ должен считаться ``asyncio.wait_for``."""
        path = _write(tmp_path, "p.py", "import my\nmy.wait_for(coro, timeout=10.0)\n")
        assert _find_wait_for_calls(path) == []

    def test_handles_syntax_error_gracefully(self, tmp_path: Path) -> None:
        """SyntaxError → пустой список (не бросает)."""
        path = _write(tmp_path, "p.py", "def broken(:\n")
        assert _find_wait_for_calls(path) == []


# ============================================================================
# _file_has_text: generic text search
# ============================================================================


class TestFileHasText:
    """``_file_has_text`` — case-sensitive substring search."""

    def test_returns_true_for_present_needle(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "p.py", "x = deadline_budget.y\n")
        assert _file_has_text(path, "deadline_budget")

    def test_returns_false_for_absent_needle(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "p.py", "x = 1\n")
        assert not _file_has_text(path, "deadline_budget")

    def test_returns_true_if_any_needle_present(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "p.py", "y = is_expired\n")
        assert _file_has_text(path, "deadline_budget", "is_expired")

    def test_returns_false_for_syntax_error(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "p.py", "def broken(:\n")
        assert not _file_has_text(path, "deadline_budget")


# ============================================================================
# _file_has_admission_control
# ============================================================================


class TestFileHasAdmissionControl:
    """``_file_has_admission_control`` — эвристика для admission блока."""

    def test_no_request_context_returns_false(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "p.py", "if budget.is_expired():\n    pass\n")
        assert not _file_has_admission_control(path)

    def test_is_expired_with_request_context(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            (
                "from src.backend.core.request_context import RequestContext\n"
                "ctx = RequestContext.current()\n"
                "if ctx.deadline_budget.is_expired():\n"
                "    return\n"
            ),
        )
        assert _file_has_admission_control(path)

    def test_remaining_le_zero_with_request_context(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            (
                "from src.backend.core.request_context import RequestContext\n"
                "ctx = RequestContext.current()\n"
                "if remaining() <= 0:\n"
                "    return\n"
            ),
        )
        assert _file_has_admission_control(path)


# ============================================================================
# _file_has_narrowing
# ============================================================================


class TestFileHasNarrowing:
    """``_file_has_narrowing`` — эвристика для timeout narrowing."""

    def test_min_with_timeout_and_remaining(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "p.py", "effective_timeout = min(self._timeout, remaining)\n"
        )
        assert _file_has_narrowing(path)

    def test_effective_timeout_min(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            "effective_timeout = min(self.timeout_seconds, remaining)\n",
        )
        assert _file_has_narrowing(path)

    def test_budget_share(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            "branch_budget = ctx.deadline_budget.share(1.0 / n_branches)\n",
        )
        assert _file_has_narrowing(path)

    def test_no_narrowing_pattern(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "p.py", "await asyncio.wait_for(coro, timeout=self.timeout)\n"
        )
        assert not _file_has_narrowing(path)


# ============================================================================
# classify_processor
# ============================================================================


class TestClassifyProcessor:
    """``classify_processor`` классифицирует processor файл по verdict."""

    def test_no_pattern_returns_no_pattern(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            "from src.backend.dsl.engine.processors.base import BaseProcessor\n"
            "class P(BaseProcessor):\n"
            "    async def process(self, exchange, context):\n"
            "        exchange.out_message = exchange.in_message\n",
        )
        result = classify_processor(path)
        assert result.verdict == "no-pattern"
        assert result.wait_for_calls == ()
        assert result.has_fanout is False

    def test_legacy_with_wait_for_no_integration(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            (
                "import asyncio\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        await asyncio.wait_for(coro, timeout=10.0)\n"
            ),
        )
        result = classify_processor(path)
        assert result.verdict == "legacy"
        assert len(result.wait_for_calls) == 1

    def test_integrated_with_narrowing(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            (
                "import asyncio\n"
                "from src.backend.core.async_utils.deadline_budget import DeadlineBudget\n"
                "from src.backend.core.request_context import RequestContext\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        ctx = RequestContext.current()\n"
                "        if ctx.deadline_budget:\n"
                "            remaining = ctx.deadline_budget.remaining()\n"
                "            effective = min(self.timeout, remaining)\n"
                "        await asyncio.wait_for(coro, timeout=effective)\n"
            ),
        )
        result = classify_processor(path)
        assert result.verdict == "integrated"
        assert result.has_narrowing is True

    def test_integrated_with_admission_control(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            (
                "from src.backend.core.async_utils.deadline_budget import DeadlineBudget\n"
                "from src.backend.core.request_context import RequestContext\n"
                "import asyncio\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        ctx = RequestContext.current()\n"
                "        if ctx is not None and ctx.deadline_budget is not None:\n"
                "            if ctx.deadline_budget.is_expired():\n"
                "                exchange.fail('admission')\n"
                "                return\n"
                "        await asyncio.gather(*[])\n"
            ),
        )
        result = classify_processor(path)
        assert result.verdict == "integrated"
        assert result.has_admission_control is True
        assert result.has_fanout is True
        assert "asyncio.gather" in result.fanout_patterns

    def test_partial_when_deadline_refs_without_integration(
        self, tmp_path: Path
    ) -> None:
        """Если файл ссылается на deadline_budget, но не narrowing/admission."""
        path = _write(
            tmp_path,
            "p.py",
            (
                "import asyncio\n"
                "from src.backend.core.request_context import RequestContext\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        # DeadlineBudget mentioned but not used for narrowing.\n"
                "        await asyncio.wait_for(coro, timeout=10.0)\n"
            ),
        )
        result = classify_processor(path)
        # deadline_refs есть (RequestContext), но admission_control нет,
        # narrowing нет → partial (НЕ legacy, потому что есть deadline_refs).
        assert result.verdict == "partial"
        assert result.has_deadline_refs is True
        assert result.has_admission_control is False
        assert result.has_narrowing is False

    def test_legacy_fanout_only(self, tmp_path: Path) -> None:
        """Fanout (asyncio.gather) без admission control → legacy."""
        path = _write(
            tmp_path,
            "p.py",
            (
                "import asyncio\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        results = await asyncio.gather(*tasks)\n"
            ),
        )
        result = classify_processor(path)
        assert result.verdict == "legacy"
        assert result.has_fanout is True
        assert "asyncio.gather" in result.fanout_patterns

    def test_subprocess_fanout_detected(self, tmp_path: Path) -> None:
        """``asyncio.create_subprocess_exec`` → fanout pattern."""
        path = _write(
            tmp_path,
            "p.py",
            (
                "import asyncio\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        proc = await asyncio.create_subprocess_exec('ls')\n"
            ),
        )
        result = classify_processor(path)
        assert result.has_fanout is True
        assert any("create_subprocess" in p for p in result.fanout_patterns)

    def test_subpipeline_executor_fanout_detected(self, tmp_path: Path) -> None:
        """``SubPipelineExecutor.execute_route`` → fanout pattern."""
        path = _write(
            tmp_path,
            "p.py",
            (
                "from src.backend.dsl.engine.processors.base import SubPipelineExecutor\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        result, error = await SubPipelineExecutor.execute_route(\n"
                "            'r1', body, headers, context\n"
                "        )\n"
            ),
        )
        result = classify_processor(path)
        assert result.has_fanout is True
        assert any("SubPipelineExecutor" in p for p in result.fanout_patterns)


# ============================================================================
# render_human / render_json
# ============================================================================


class TestRenderHuman:
    """``render_human`` — human-readable отчёт."""

    def test_includes_summary_header(self) -> None:
        results: list[ProcessorStatus] = []
        output = render_human(results)
        assert "Deadline Propagation Completeness Check" in output
        assert "Summary:" in output
        assert "integrated=0" in output
        assert "legacy=0" in output
        assert "partial=0" in output

    def test_includes_legacy_section(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            (
                "import asyncio\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        await asyncio.wait_for(coro, timeout=10.0)\n"
            ),
        )
        result = classify_processor(path)
        output = render_human([result])
        assert "LEGACY" in output
        assert "asyncio.wait_for" in output

    def test_includes_integrated_section(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            (
                "from src.backend.core.async_utils.deadline_budget import DeadlineBudget\n"
                "from src.backend.core.request_context import RequestContext\n"
                "import asyncio\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        ctx = RequestContext.current()\n"
                "        if ctx and ctx.deadline_budget:\n"
                "            remaining = ctx.deadline_budget.remaining()\n"
                "            effective = min(self.timeout, remaining)\n"
                "        await asyncio.wait_for(coro, timeout=effective)\n"
            ),
        )
        result = classify_processor(path)
        output = render_human([result])
        assert "INTEGRATED" in output
        assert "narrowing" in output


class TestRenderJson:
    """``render_json`` — machine-readable JSON output."""

    def test_json_is_valid_and_includes_summary(self) -> None:
        output = render_json([])
        data = json.loads(output)
        assert "summary" in data
        assert data["summary"]["integrated"] == 0
        assert data["summary"]["legacy"] == 0
        assert data["summary"]["partial"] == 0
        assert data["summary"]["no-pattern"] == 0
        assert data["total_processors"] == 0

    def test_json_includes_fanout_patterns(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "p.py",
            (
                "import asyncio\n"
                "from src.backend.core.request_context import RequestContext\n"
                "from src.backend.core.async_utils.deadline_budget import DeadlineBudget\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        ctx = RequestContext.current()\n"
                "        if ctx and ctx.deadline_budget:\n"
                "            if ctx.deadline_budget.is_expired():\n"
                "                return\n"
                "        await asyncio.gather(*[])\n"
            ),
        )
        result = classify_processor(path)
        output = render_json([result])
        data = json.loads(output)
        assert data["total_processors"] == 1
        proc = data["processors"][0]
        assert proc["verdict"] == "integrated"
        assert proc["has_fanout"] is True
        assert "asyncio.gather" in proc["fanout_patterns"]

    def test_json_uses_unicode_escapes(self) -> None:
        """``ensure_ascii=False`` → Cyrillic без escapes в JSON output."""
        # Тест: создаём ProcessorStatus с file path, содержащим кириллицу.
        # Это типично для multi-tenant проектов с RU именами.
        result = ProcessorStatus(
            file=Path("тест/processor.py"),
            wait_for_calls=(),
            has_deadline_refs=False,
            has_admission_control=False,
            has_narrowing=False,
            has_fanout=False,
            fanout_patterns=(),
            verdict="no-pattern",
        )
        output = render_json([result])
        # ensure_ascii=False → "тест" без escapes
        assert "тест" in output
        # Verify it's parseable JSON.
        data = json.loads(output)
        assert data["processors"][0]["file"].endswith("тест/processor.py")


# ============================================================================
# Edge cases — fanout-only with admission control (no narrowing)
# ============================================================================


class TestEdgeCasesFanoutOnlyAdmission:
    """Fanout-only file (no wait_for) с admission control → integrated."""

    def test_fanout_with_admission_control_only(self, tmp_path: Path) -> None:
        """``asyncio.gather`` + admission_control (no wait_for) → integrated."""
        path = _write(
            tmp_path,
            "p.py",
            (
                "import asyncio\n"
                "from src.backend.core.async_utils.deadline_budget import DeadlineBudget\n"
                "from src.backend.core.request_context import RequestContext\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        ctx = RequestContext.current()\n"
                "        if ctx is not None and ctx.deadline_budget is not None:\n"
                "            if ctx.deadline_budget.is_expired():\n"
                "                exchange.fail('admission')\n"
                "                return\n"
                "        await asyncio.gather(*[])\n"
            ),
        )
        result = classify_processor(path)
        # Есть admission_control И deadline_refs → integrated.
        # has_fanout=True (asyncio.gather), wait_for_calls=().
        assert result.verdict == "integrated"
        assert result.has_admission_control is True
        assert result.has_fanout is True
        assert result.wait_for_calls == ()


class TestEdgeCasesEmptyFile:
    """Empty / pure-comment file → no-pattern."""

    def test_empty_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "p.py", "")
        result = classify_processor(path)
        assert result.verdict == "no-pattern"

    def test_only_comments(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "p.py", "# Just a comment\n# Another comment\n")
        result = classify_processor(path)
        assert result.verdict == "no-pattern"

    def test_only_imports(self, tmp_path: Path) -> None:
        """File только с imports → no-pattern."""
        path = _write(tmp_path, "p.py", "import asyncio\nfrom typing import Any\n")
        result = classify_processor(path)
        assert result.verdict == "no-pattern"


class TestEdgeCasesMixedWaitForAndFanout:
    """Файл с wait_for + fanout → classified по обоим паттернам."""

    def test_wait_for_plus_asyncio_gather(self, tmp_path: Path) -> None:
        """wait_for + asyncio.gather в одном файле → narrowing применяется."""
        path = _write(
            tmp_path,
            "p.py",
            (
                "import asyncio\n"
                "from src.backend.core.async_utils.deadline_budget import DeadlineBudget\n"
                "from src.backend.core.request_context import RequestContext\n"
                "class P:\n"
                "    async def process(self, exchange, context):\n"
                "        ctx = RequestContext.current()\n"
                "        if ctx is not None and ctx.deadline_budget is not None:\n"
                "            remaining = ctx.deadline_budget.remaining()\n"
                "            if remaining <= 0.0:\n"
                "                exchange.fail('admission')\n"
                "                return\n"
                "            effective = min(self.timeout, remaining)\n"
                "        await asyncio.wait_for(coro, timeout=effective)\n"
                "        await asyncio.gather(*[])\n"
            ),
        )
        result = classify_processor(path)
        assert result.verdict == "integrated"
        # И wait_for, и fanout detected.
        assert len(result.wait_for_calls) == 1
        assert result.has_fanout is True
        assert "asyncio.gather" in result.fanout_patterns


class TestEdgeCasesRealFiles:
    """Integration тесты с реальными файлами в repo."""

    def test_real_scatter_gather_is_integrated(self) -> None:
        """``scatter_gather.py`` в repo → integrated (cycle 140)."""
        repo_path = (
            Path(__file__).resolve().parents[3]
            / "src/backend/dsl/engine/processors/eip/routing/scatter_gather.py"
        )
        if not repo_path.exists():
            pytest.skip("scatter_gather.py not found")
        result = classify_processor(repo_path)
        assert result.verdict == "integrated"
        assert result.has_narrowing is True

    def test_real_parallel_is_integrated(self) -> None:
        """``parallel.py`` в repo → integrated."""
        repo_path = (
            Path(__file__).resolve().parents[3]
            / "src/backend/dsl/engine/processors/control_flow/parallel.py"
        )
        if not repo_path.exists():
            pytest.skip("parallel.py not found")
        result = classify_processor(repo_path)
        assert result.verdict == "integrated"

    def test_real_base_py_excluded(self) -> None:
        """``base.py`` исключён из проверки (utility module)."""
        from checks.check_deadline_propagation import _iter_dsl_processor_files

        files = _iter_dsl_processor_files()
        base_path = (
            Path(__file__).resolve().parents[3]
            / "src/backend/dsl/engine/processors/base.py"
        )
        # base.py не должен быть в списке.
        assert base_path not in files

    def test_real_init_excluded(self) -> None:
        """``__init__.py`` исключён из проверки (re-exports)."""
        from checks.check_deadline_propagation import _iter_dsl_processor_files

        files = _iter_dsl_processor_files()
        # Ни один файл с именем __init__.py не должен быть в списке.
        for f in files:
            assert f.name != "__init__.py"

    def test_real_script_runner_excluded(self) -> None:
        """``script_runner.py`` исключён (DISABLED per cycle-6/D-AUDIT-602)."""
        from checks.check_deadline_propagation import _iter_dsl_processor_files

        files = _iter_dsl_processor_files()
        sr_path = (
            Path(__file__).resolve().parents[3]
            / "src/backend/dsl/engine/processors/script_runner.py"
        )
        if sr_path.exists():
            assert sr_path not in files


class TestEdgeCasesRelPathHelper:
    """``_rel_path`` graceful rendering."""

    def test_rel_path_inside_repo(self) -> None:
        """Path внутри REPO_ROOT → relative path."""
        from checks.check_deadline_propagation import _rel_path

        repo_path = (
            Path(__file__).resolve().parents[3]
            / "src/backend/dsl/engine/processors/base.py"
        )
        rel = _rel_path(repo_path)
        # Должен вернуть relative path, не абсолютный.
        assert not rel.is_absolute()

    def test_rel_path_outside_repo(self, tmp_path: Path) -> None:
        """Path вне REPO_ROOT → fallback на absolute."""
        from checks.check_deadline_propagation import _rel_path

        outside = tmp_path / "test.py"
        rel = _rel_path(outside)
        # Fallback на absolute path.
        assert rel.is_absolute()
        assert rel == outside
