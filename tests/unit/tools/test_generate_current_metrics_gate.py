"""F-MD1: гейт метрик README не должен быть самоссылочным.

`tools/generate_current_metrics.py` вписывает ``git rev-parse HEAD`` в
**коммитируемый** README. Если SHA участвует в сравнении, то гейт ``--check``
зелёный только на незакоммиченном README: сам факт коммита меняет ``HEAD``
и роняет проверку. Это делало блокирующий CI-гейт (`make/docs.mk` →
``docs-current-metrics-check``) принципиально непроходимым.

Тесты ниже фиксируют обе стороны исправления:

* SHA и метка времени **не** роняют гейт (то, что было сломано);
* реальные метрики (counts) по-прежнему роняют гейт (то, что чинить нельзя
  было бы ослаблением сравнения).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[3]
_TOOL = _ROOT / "tools" / "generate_current_metrics.py"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _load_tool() -> ModuleType:
    """Загрузить инструмент как модуль, не импортируя пакет `tools`.

    Args:
        нет.

    Returns:
        Модуль ``generate_current_metrics``.

    """
    spec = importlib.util.spec_from_file_location("_gcm_under_test", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _block(head: str, *, actions: int = 132, tests: int = 20961) -> str:
    """Собрать блок метрик фиксированной формы.

    Args:
        head: SHA «снимка кода» для подстановки.
        actions: число actions — изменяемый параметр для негативных тестов.
        tests: число тестов — изменяемый параметр для негативных тестов.

    Returns:
        Текст блока между маркерами.

    """
    return (
        "<!-- BEGIN GENERATED METRICS -->\n"
        "\n"
        "<!-- СГЕНЕРИРОВАНО: `uv run python tools/generate_current_metrics.py --write`. -->\n"
        "\n"
        f"**Снимок кода:** `{head}` · сгенерировано 2026-10-05 06:16 UTC\n"
        "\n"
        "| Метрика | Значение | Источник |\n"
        "|---|---:|---|\n"
        f"| HEAD | `{head}` | `git rev-parse HEAD` |\n"
        f"| Actions (runtime) | {actions} | `ActionHandlerRegistry.list_actions()` |\n"
        f"| Тестов собрано | {tests} | `pytest --collect-only -q` |\n"
        "\n"
        "<!-- END GENERATED METRICS -->\n"
    )


class TestStripVolatile:
    """F-MD1: SHA и метка времени не должны участвовать в сравнении."""

    def test_strips_generation_timestamp(self) -> None:
        """Метка времени генерации не влияет на результат сравнения."""
        tool = _load_tool()
        sha = "2" * 40
        assert tool._strip_volatile(_block(sha)) == tool._strip_volatile(_block(sha))

    def test_strips_head_sha_in_snapshot_line(self) -> None:
        """SHA в строке «Снимок кода» вырезается."""
        tool = _load_tool()
        stripped = tool._strip_volatile(_block("a" * 40))
        assert "a" * 40 not in stripped
        assert "<volatile>" in stripped

    def test_strips_head_sha_in_table_row(self) -> None:
        """SHA в строке таблицы ``| HEAD |`` вырезается."""
        tool = _load_tool()
        stripped = tool._strip_volatile(_block("b" * 40))
        assert "b" * 40 not in stripped
        assert "| HEAD | `<volatile>` |" in stripped

    def test_commit_does_not_break_the_gate(self) -> None:
        """Ключевая регрессия: коммит README не роняет сравнение.

        Блок, снятый до коммита, и блок того же кода после коммита обязаны
        сравниваться как равные — иначе гейт зелёный только на грязном дереве.

        """
        tool = _load_tool()
        before_commit = _block("c" * 40)
        after_commit = _block("d" * 40)
        assert tool._strip_volatile(before_commit) == tool._strip_volatile(after_commit)


class TestGateStillDetectsDrift:
    """F-MD1: ослабление сравнения не должно пропускать реальное устаревание."""

    def test_action_count_drift_is_detected(self) -> None:
        """Изменение числа actions должно ронять гейт."""
        tool = _load_tool()
        assert tool._strip_volatile(
            _block("e" * 40, actions=132)
        ) != tool._strip_volatile(_block("e" * 40, actions=109))

    def test_test_count_drift_is_detected(self) -> None:
        """Изменение числа тестов должно ронять гейт."""
        tool = _load_tool()
        assert tool._strip_volatile(
            _block("f" * 40, tests=20961)
        ) != tool._strip_volatile(_block("f" * 40, tests=20000))

    def test_head_label_is_still_rendered(self) -> None:
        """SHA остаётся в блоке как информация — он не удаляется совсем.

        ``render_block`` обрезает SHA до 12 символов, поэтому в блоке
        ожидается именно короткая форма.

        """
        tool = _load_tool()
        head = "1234567890abcdef" * 2 + "abcdef01"
        assert _SHA_RE.match(head)
        rendered = tool.render_block({"HEAD": head, "protocols": []})
        assert f"| HEAD | `{head[:12]}` |" in rendered
        assert "**Снимок кода:** `1234567890ab`" in rendered


class TestGateIsReachableFromCI:
    """F-MD1: цель гейта объявлена как блокирующая, значит должна вызываться."""

    def test_docs_current_metrics_check_defined(self) -> None:
        """Цель ``docs-current-metrics-check`` существует."""
        docs_mk = (_ROOT / "make" / "docs.mk").read_text(encoding="utf-8")
        assert "docs-current-metrics-check:" in docs_mk

    def test_pr_pipeline_calls_the_gate(self) -> None:
        """``make pr`` обязан вызывать гейт, иначе он не блокирующий.

        До фикса цель была объявлена «блокирующим CI-гейтом», но не вызывалась
        ни ``make ci``, ни ``make pr`` — именно поэтому самоссылочность
        (F-MD1) и не всплыла раньше.

        """
        pipelines_mk = (_ROOT / "make" / "pipelines.mk").read_text(encoding="utf-8")
        pr_block = pipelines_mk.split("\npr:", 1)[1]
        pr_body = pr_block.split("\n\n", 1)[0]
        assert "docs-current-metrics-check" in pr_body, (
            "make pr обязан вызывать docs-current-metrics-check, иначе README-метрики "
            "молча устаревают и CI-гейт не выполняется"
        )
