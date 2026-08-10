"""S176 #4: тесты для FileWatchProcessor multi-pattern + multi-directory + max_results.

Проверяет новые параметры:
- ``patterns`` (tuple из glob patterns, mutually exclusive с ``pattern``)
- ``directories`` (tuple директорий, mutually exclusive с ``directory``)
- ``max_results`` (лимит на количество файлов)
- exchange property overrides: ``watch_directory``, ``watch_patterns``, ``watch_max_results``
- Validation: pattern+patterns mutually exclusive, directory+directories mutually exclusive,
  хотя бы один из них должен быть указан.
"""


from __future__ import annotations

import os
import tempfile

import pytest

from src.backend.dsl.engine.processors.file_watch import FileWatchProcessor


class TestPatterns:
    """S176 #4: ``patterns`` (tuple) вместо ``pattern`` (str)."""

    @pytest.mark.asyncio
    async def test_multiple_patterns_matches_all(self) -> None:
        """Несколько patterns — match для каждого pattern'а."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "a.csv"), "w").close()
            open(os.path.join(tmpdir, "b.json"), "w").close()
            open(os.path.join(tmpdir, "c.txt"), "w").close()

            proc = FileWatchProcessor(
                directory=tmpdir,
                patterns=("*.csv", "*.json"),
            )
            from src.backend.dsl.engine.exchange import Exchange, Message

            exchange = Exchange(in_message=Message(body=None, headers={}))
            await proc.process(exchange, MagicMockCtx())

            result = exchange.properties.get("matched_files", [])
            names = {f["name"] for f in result}
            assert names == {"a.csv", "b.json"}

    @pytest.mark.asyncio
    async def test_single_pattern_still_works_backward_compat(self) -> None:
        """Single ``pattern`` (str) — backward-compat."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "x.csv"), "w").close()
            open(os.path.join(tmpdir, "y.txt"), "w").close()

            proc = FileWatchProcessor(directory=tmpdir, pattern="*.csv")
            from src.backend.dsl.engine.exchange import Exchange, Message

            exchange = Exchange(in_message=Message(body=None, headers={}))
            await proc.process(exchange, MagicMockCtx())

            result = exchange.properties.get("matched_files", [])
            assert len(result) == 1
            assert result[0]["name"] == "x.csv"


class TestDirectories:
    """S176 #4: ``directories`` (tuple) вместо ``directory`` (str)."""

    @pytest.mark.asyncio
    async def test_multiple_directories_aggregate_results(self) -> None:
        """Несколько директорий — aggregate results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_a = os.path.join(tmpdir, "a")
            dir_b = os.path.join(tmpdir, "b")
            os.makedirs(dir_a)
            os.makedirs(dir_b)
            open(os.path.join(dir_a, "file1.csv"), "w").close()
            open(os.path.join(dir_b, "file2.csv"), "w").close()

            proc = FileWatchProcessor(
                directories=(dir_a, dir_b),
                pattern="*.csv",
            )
            from src.backend.dsl.engine.exchange import Exchange, Message

            exchange = Exchange(in_message=Message(body=None, headers={}))
            await proc.process(exchange, MagicMockCtx())

            result = exchange.properties.get("matched_files", [])
            paths = {f["path"] for f in result}
            assert len(result) == 2
            assert any("file1.csv" in p for p in paths)
            assert any("file2.csv" in p for p in paths)

    @pytest.mark.asyncio
    async def test_single_directory_still_works_backward_compat(self) -> None:
        """Single ``directory`` — backward-compat."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "f.txt"), "w").close()

            proc = FileWatchProcessor(directory=tmpdir, pattern="*.txt")
            from src.backend.dsl.engine.exchange import Exchange, Message

            exchange = Exchange(in_message=Message(body=None, headers={}))
            await proc.process(exchange, MagicMockCtx())

            assert len(exchange.properties.get("matched_files", [])) == 1


class TestMaxResults:
    """S176 #4: ``max_results`` cap."""

    @pytest.mark.asyncio
    async def test_max_results_caps_output(self) -> None:
        """max_results ограничивает количество файлов в результате."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(10):
                open(os.path.join(tmpdir, f"f{i}.txt"), "w").close()

            proc = FileWatchProcessor(
                directory=tmpdir, pattern="*.txt", max_results=3
            )
            from src.backend.dsl.engine.exchange import Exchange, Message

            exchange = Exchange(in_message=Message(body=None, headers={}))
            await proc.process(exchange, MagicMockCtx())

            result = exchange.properties.get("matched_files", [])
            assert len(result) == 3

    @pytest.mark.asyncio
    async def test_no_max_results_means_unlimited(self) -> None:
        """max_results=None → unlimited (все файлы)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(5):
                open(os.path.join(tmpdir, f"f{i}.txt"), "w").close()

            proc = FileWatchProcessor(directory=tmpdir, pattern="*.txt")
            from src.backend.dsl.engine.exchange import Exchange, Message

            exchange = Exchange(in_message=Message(body=None, headers={}))
            await proc.process(exchange, MagicMockCtx())

            result = exchange.properties.get("matched_files", [])
            assert len(result) == 5


class TestExchangePropertyOverrides:
    """S176 #4: ``watch_directory`` / ``watch_patterns`` / ``watch_max_results`` overrides."""

    @pytest.mark.asyncio
    async def test_watch_directory_override(self) -> None:
        """``exchange.properties['watch_directory']`` override'ит directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            override_dir = os.path.join(tmpdir, "override")
            os.makedirs(override_dir)
            open(os.path.join(override_dir, "a.txt"), "w").close()

            proc = FileWatchProcessor(directory="/wrong/path", pattern="*.txt")
            from src.backend.dsl.engine.exchange import Exchange, Message

            exchange = Exchange(
                in_message=Message(body=None, headers={}),
                properties={"watch_directory": override_dir},
            )
            await proc.process(exchange, MagicMockCtx())

            result = exchange.properties.get("matched_files", [])
            assert len(result) == 1
            assert "override" in result[0]["path"]

    @pytest.mark.asyncio
    async def test_watch_patterns_override(self) -> None:
        """``exchange.properties['watch_patterns']`` override'ит patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "a.csv"), "w").close()
            open(os.path.join(tmpdir, "b.json"), "w").close()

            proc = FileWatchProcessor(directory=tmpdir, pattern="*.csv")
            from src.backend.dsl.engine.exchange import Exchange, Message

            exchange = Exchange(
                in_message=Message(body=None, headers={}),
                properties={"watch_patterns": ["*.csv", "*.json"]},
            )
            await proc.process(exchange, MagicMockCtx())

            result = exchange.properties.get("matched_files", [])
            names = {f["name"] for f in result}
            assert names == {"a.csv", "b.json"}

    @pytest.mark.asyncio
    async def test_watch_max_results_override(self) -> None:
        """``exchange.properties['watch_max_results']`` override'ит max_results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(10):
                open(os.path.join(tmpdir, f"f{i}.txt"), "w").close()

            proc = FileWatchProcessor(
                directory=tmpdir, pattern="*.txt", max_results=10
            )
            from src.backend.dsl.engine.exchange import Exchange, Message

            exchange = Exchange(
                in_message=Message(body=None, headers={}),
                properties={"watch_max_results": 2},
            )
            await proc.process(exchange, MagicMockCtx())

            result = exchange.properties.get("matched_files", [])
            assert len(result) == 2


class TestValidation:
    """S176 #4: validation mutual exclusivity + required params."""

    def test_pattern_and_patterns_mutually_exclusive(self) -> None:
        """pattern + patterns → ValueError."""
        with pytest.raises(ValueError, match="pattern.*patterns|patterns.*pattern"):
            FileWatchProcessor(
                directory="/tmp", pattern="*.csv", patterns=("*.csv", "*.json")
            )

    def test_directory_and_directories_mutually_exclusive(self) -> None:
        """directory + directories → ValueError."""
        with pytest.raises(ValueError, match="directory.*directories|directories.*directory"):
            FileWatchProcessor(
                directory="/a", directories=("/a", "/b"), pattern="*.csv"
            )

    def test_no_directory_raises(self) -> None:
        """Ни directory, ни directories → ValueError."""
        with pytest.raises(ValueError, match="directory"):
            FileWatchProcessor(pattern="*.csv")


class TestToSpec:
    """S176 #4: to_spec сериализация."""

    def test_to_spec_single_dir_single_pattern_backward_compat(self) -> None:
        """Single dir + single pattern → legacy format."""
        proc = FileWatchProcessor(directory="/data", pattern="*.csv")
        spec = proc.to_spec()
        assert spec == {
            "file_watch": {
                "directory": "/data",
                "pattern": "*.csv",
                "result_property": "matched_files",
            }
        }

    def test_to_spec_multi_directory(self) -> None:
        """Multi-directory → new format."""
        proc = FileWatchProcessor(
            directories=("/a", "/b"), pattern="*.csv", max_results=5
        )
        spec = proc.to_spec()
        assert spec == {
            "file_watch": {
                "directories": ["/a", "/b"],
                "patterns": ["*.csv"],
                "result_property": "matched_files",
                "max_results": 5,
            }
        }

    def test_to_spec_multi_pattern(self) -> None:
        """Multi-pattern → new format."""
        proc = FileWatchProcessor(
            directory="/data",
            patterns=("*.csv", "*.json"),
            include_subdirs=True,
        )
        spec = proc.to_spec()
        assert spec == {
            "file_watch": {
                "directory": "/data",
                "patterns": ["*.csv", "*.json"],
                "result_property": "matched_files",
                "include_subdirs": True,
            }
        }


class MagicMockCtx:
    """Minimal stub for ExecutionContext (не используется в process())."""

    pass
