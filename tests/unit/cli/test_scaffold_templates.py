"""Тесты шаблонов ``src/backend/cli/scaffold.py``.

CLI-scaffold — второй, параллельный генератор (первый — ``tools/scaffold.py``,
который был починен в a053f722e). CLI-версия осталась с no-op шаблоном
процессора и с legacy-путями, запрещёнными R-V15-2.

Тесты проверяют, что CLI-генератор выдаёт рабочий, а не no-op processor и
не пишет в legacy-каталоги:

1. шаблон процессора компилируется и синтаксически валиден;
2. шаблон НЕ содержит ``# TODO: implement processor logic`` (no-op маркер);
3. шаблон демонстрирует рабочий API: ``set_result`` / ``side_effect`` /
   ``correlation_id`` / ``context.route_id``;
4. сгенерированный класс реально инстанцируется и отрабатывает на Exchange;
5. route-шаблон пишет в ``routes/<name>/`` (R-V15-2), а не в ``dsl_routes/``;
6. route-шаблон использует ключ ``steps:`` (актуальный YAML-контракт DSL).

Проверки выполняются в tmp_path, файлы проекта не создаются.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

NOOP_MARKER = "# TODO: implement processor logic"


@pytest.fixture
def cli_scaffold() -> Any:
    """Модуль CLI-scaffold."""
    from src.backend.cli import scaffold as module

    return module


def _extract_processor_source(cli_scaffold: Any, tmp_path: Path) -> str:
    """Вызывает scaffold_processor в tmp_path и читает созданный файл."""
    monkey_target = tmp_path / "src" / "backend" / "dsl" / "engine" / "processors"
    monkey_target.mkdir(parents=True, exist_ok=True)

    # Pre-existing bug: ``original = Path.cwd`` (метод, а не значение) →
    # ``original()`` в finally вычислялся УЖЕ после chdir(tmp_path) → CWD
    # оставался в tmp_path и ломал последующие тесты, читающие файлы
    # относительным путём.
    original = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        cli_scaffold.scaffold_processor("demo_thing")
    finally:
        os.chdir(original)

    generated = monkey_target / "demo_thing.py"
    assert generated.exists(), f"процессор не создан: {generated}"
    return generated.read_text(encoding="utf-8")


class TestCliProcessorTemplate:
    """Шаблон процессора из CLI-scaffold."""

    def test_template_is_valid_python(self, cli_scaffold: Any, tmp_path: Path) -> None:
        """Сгенерированный модуль синтаксически валиден."""
        source = _extract_processor_source(cli_scaffold, tmp_path)
        ast.parse(source)

    def test_template_is_not_noop(self, cli_scaffold: Any, tmp_path: Path) -> None:
        """Нет no-op маркера — это главная регрессия a053f722e для CLI."""
        source = _extract_processor_source(cli_scaffold, tmp_path)
        assert NOOP_MARKER not in source, (
            "CLI-scaffold всё ещё генерирует no-op processor; "
            "используйте processor_template из tools/scaffold.py"
        )

    def test_template_demonstrates_working_api(
        self, cli_scaffold: Any, tmp_path: Path
    ) -> None:
        """Шаблон показывает канонический API процессора."""
        source = _extract_processor_source(cli_scaffold, tmp_path)
        for needle in ("set_result", "side_effect", "correlation_id", "route_id"):
            assert needle in source, (
                f"шаблон процессора не демонстрирует {needle} — "
                "это ломает обучающий шаблон"
            )

    @pytest.mark.asyncio
    async def test_generated_processor_runs(
        self, cli_scaffold: Any, tmp_path: Path
    ) -> None:
        """Сгенерированный процессор инстанцируется и отрабатывает."""
        import importlib.util
        import sys
        import uuid

        source = _extract_processor_source(cli_scaffold, tmp_path)
        target = tmp_path / "generated_demo_thing.py"
        target.write_text(source, encoding="utf-8")

        mod_name = f"gen_cli_demo_{uuid.uuid4().hex[:8]}"
        spec = importlib.util.spec_from_file_location(mod_name, target)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        try:
            spec.loader.exec_module(module)
            cls = getattr(module, "DemoThingProcessor")

            from src.backend.dsl.engine.context import ExecutionContext
            from src.backend.dsl.engine.exchange import Exchange, Message
            from src.backend.dsl.engine.processors.base import BaseProcessor

            assert issubclass(cls, BaseProcessor)

            processor = cls()
            msg = Message(body={"input": 1})
            exchange: Any = Exchange(in_message=msg)
            context = ExecutionContext(route_id="demo_route")
            await processor.process(exchange, context)

            # Ключи шаблона строятся от class_name.lower() ("DemoThing" → "demothing")
            assert msg.body.get("demothing_processed") is True, (
                f"процессор не записал результат через set_result; body={msg.body!r}"
            )
            assert exchange.get_property("demothing_route_id") == "demo_route", (
                "route_id из ExecutionContext не проброшен в properties"
            )
            assert exchange.get_property("demothing_correlation_id") == (
                exchange.meta.correlation_id
            ), "correlation_id из exchange.meta не проброшен в properties"
        finally:
            sys.modules.pop(mod_name, None)


class TestCliRouteTemplate:
    """Route-шаблон из CLI-scaffold."""

    def _generate(self, cli_scaffold: Any, tmp_path: Path, name: str) -> Path:
        import os

        # Pre-existing bug: ``os.chdir(Path.cwd())`` в finally вычислялся
        # УЖЕ после chdir(tmp_path) → CWD оставался в tmp_path и ломал
        # последующие тесты, читающие файлы относительным путём.
        original = Path.cwd()
        try:
            os.chdir(tmp_path)
            cli_scaffold.scaffold_route(name, source="http:POST /api/demo")
        finally:
            os.chdir(original)
        return tmp_path

    def test_route_not_written_to_legacy_dsl_routes(
        self, cli_scaffold: Any, tmp_path: Path
    ) -> None:
        """R-V15-2: DSL-routes живут в routes/<name>/, dsl_routes/ — legacy."""
        root = self._generate(cli_scaffold, tmp_path, "demo_route")
        assert not (root / "dsl_routes").exists(), (
            "scaffold_route пишет в legacy dsl_routes/ — запрещено R-V15-2"
        )
        assert (root / "routes" / "demo_route").is_dir(), (
            "ожидался routes/<name>/ для нового маршрута"
        )

    def test_route_uses_steps_key(self, cli_scaffold: Any, tmp_path: Path) -> None:
        """Актуальный YAML-контракт DSL — массив steps[]."""
        root = self._generate(cli_scaffold, tmp_path, "demo_route")
        yaml_files = list((root / "routes" / "demo_route").glob("*.dsl.yaml"))
        assert yaml_files, "не найден сгенерированный *.dsl.yaml"
        content = yaml_files[0].read_text(encoding="utf-8")
        assert re.search(r"^steps:", content, re.MULTILINE), (
            "YAML-маршрут должен объявлять steps:[] (V15 universal route formula)"
        )
        assert "route_id:" in content, "route_id обязателен в *.dsl.yaml"
