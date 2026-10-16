"""Regression-тесты для ``tools/scaffold.py`` processor template.

2026-10-15 (out-of-scope item из re-audit): шаблон процессора был
no-op (``return None`` + ``# TODO: реализуйте бизнес-логику``), что
делало сгенерированный файл бесполезным стартовой точкой.

Тесты проверяют:

1. Сгенерированный код **компилируется** (``compile()``);
2. Код **импортируется** и класс доступен (реальный import machinery);
3. Класс наследует ``BaseProcessor`` и объявляет ``side_effect``,
   ``compensatable``, ``required_capability``;
4. ``process()`` действительно мутирует exchange (не no-op) —
   вызывается ``set_result`` с body.* и properties.* targets;
5. Service/Route шаблоны тоже компилируются (регрессия на синтаксис).

Не проверяем: docstring-качество, форматирование, бизнес-логику
(это ответственность разработчика).
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # tests/unit/tools → repo root
SCAFFOLD_PATH = PROJECT_ROOT / "tools" / "scaffold.py"


@pytest.fixture(scope="module")
def scaffold_module() -> Any:
    """Загружает tools/scaffold.py как модуль."""
    spec = importlib.util.spec_from_file_location("scaffold_mod", SCAFFOLD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestProcessorTemplateQuality:
    """Качество processor-шаблона (out-of-scope fix 2026-10-15)."""

    def test_template_compiles(self, scaffold_module: Any) -> None:
        """Сгенерированный код синтаксически валиден."""
        code = scaffold_module.processor_template("DemoComp")
        compile(code, "<generated>", "exec")  # noqa: S102 — это и есть проверка

    def test_template_not_noop(self, scaffold_module: Any) -> None:
        """Шаблон НЕ содержит no-op ``return None`` как единственную логику."""
        code = scaffold_module.processor_template("DemoNoop")
        # Раньше тело process() было ровно "# TODO\n return None"
        assert "# TODO: реализуйте бизнес-логику" not in code, (
            "Processor template всё ещё содержит no-op TODO вместо "
            "рабочего паттерна (regression 2026-10-15)"
        )
        # Должна быть демонстрация set_result
        assert "set_result" in code, (
            "Processor template должен демонстрировать BaseProcessor.set_result"
        )

    def test_template_declares_side_effect_class_vars(
        self, scaffold_module: Any
    ) -> None:
        """Шаблон объявляет SideEffectKind / compensatable / capability.

        Engine использует эти ClassVar для retry-стратегии и Saga
        compensation; шаблон должен показывать разработчику, что их
        нужно задавать осознанно.
        """
        code = scaffold_module.processor_template("DemoVars")
        assert "side_effect" in code
        assert "SideEffectKind" in code
        assert "compensatable" in code
        assert "required_capability" in code
        assert (
            "from src.backend.core.types.side_effect import SideEffectKind" in code
        ), (
            "SideEffectKind импортируется из src.backend.core.types.side_effect "
            "(НЕ из processors.base — там только re-export/использование)"
        )

    def test_generated_class_instantiates_and_processes(
        self, scaffold_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Сгенерированный класс реально работает: создаётся, process() мутирует exchange.

        Полный round-trip: сгенерировать → записать в tmp → импортировать →
        инстанцировать → вызвать process() → проверить мутации exchange.
        """
        from src.backend.dsl.engine.context import ExecutionContext
        from src.backend.dsl.engine.exchange import Exchange, Message
        from src.backend.dsl.engine.processors.base import BaseProcessor

        code = scaffold_module.processor_template("DemoRun")
        target = tmp_path / "demo_run_processor.py"
        target.write_text(code, encoding="utf-8")

        # Импорт по уникальному имени (чтобы не конфликтовать с sys.modules).
        mod_name = f"gen_demo_run_{uuid.uuid4().hex[:8]}"
        spec = importlib.util.spec_from_file_location(mod_name, target)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        try:
            spec.loader.exec_module(module)
            cls = getattr(module, "DemoRunProcessor")

            # 1. Наследует BaseProcessor
            assert issubclass(cls, BaseProcessor), (
                f"Generated class must subclass BaseProcessor, got {cls.__mro__}"
            )

            # 2. Инстанцируется с default name
            proc = cls()
            assert proc.name == "demorun", f"Default name wrong: {proc.name!r}"
            assert proc.side_effect is not None
            assert proc.compensatable is True
            assert proc.required_capability is None

            # 3. process() мутирует exchange (не no-op)
            msg = Message(body={"initial": True})
            exchange: Any = Exchange(in_message=msg)
            ctx: Any = ExecutionContext(route_id="demo-run-route")
            asyncio.run(proc.process(exchange, ctx))

            # body.* target записан
            assert msg.body.get("demorun_processed") is True, (
                f"set_result('body.demorun_processed', True) не применился; "
                f"body={msg.body!r}"
            )
            # properties.* target записан (correlation_id из exchange.meta —
            # именно оттуда он берётся на runtime, НЕ из ExecutionContext).
            exchange_cid = exchange.meta.correlation_id
            assert exchange_cid, "Exchange.meta.correlation_id должен быть заполнен"
            assert exchange.get_property("demorun_correlation_id") == exchange_cid, (
                "set_result('properties.demorun_correlation_id', ...) "
                "не применился или записал неверное значение; "
                f"expected={exchange_cid!r}, "
                f"got={exchange.get_property('demorun_correlation_id')!r}"
            )
            # route_id из ExecutionContext тоже пробрасывается
            assert exchange.get_property("demorun_route_id") == "demo-run-route", (
                "set_result('properties.demorun_route_id', context.route_id) "
                "не применился"
            )
        finally:
            sys.modules.pop(mod_name, None)


class TestOtherTemplatesCompile:
    """Service и Route шаблоны — синтаксис не должен регрессировать."""

    def test_service_template_compiles(self, scaffold_module: Any) -> None:
        code = scaffold_module.service_template("DemoSvc")
        compile(code, "<generated>", "exec")  # noqa: S102

    def test_route_template_compiles(self, scaffold_module: Any) -> None:
        code = scaffold_module.route_template("demo.route", "timer:60s")
        compile(code, "<generated>", "exec")  # noqa: S102
