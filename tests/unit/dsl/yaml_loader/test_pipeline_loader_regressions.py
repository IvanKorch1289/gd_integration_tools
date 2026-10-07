"""Регрессия: YAML-загрузчик pipeline (правки 2026-10-06).

Найдено при разборе цепочки блокеров DSL-роутов
(``tools/route_blockers_report.py``). Подсистема V11-роутов была выключена
по умолчанию (``V11_ROUTE_LOADER_ENABLED=false``), поэтому её reference-роуты
никогда не проходили регистрацию и дефекты накопились незамеченными.

1. ``route_id`` требовался и в pipeline-YAML, хотя он уже объявлен в
   ``route.toml`` (``[route] name``). Дублирование создавало рассинхрон и
   роняло ``echo_demo`` / ``health_proxy_demo`` с
   ``Missing required field: route_id``. Теперь V11-путь передаёт имя из
   манифеста через ``default_route_id``; автономная загрузка YAML остаётся
   строгой.

2. Элемент YAML-списка, состоящий только из комментариев, разбирается в
   ``None`` и ронял загрузку с ``ValueError: Invalid processor spec: None``.
   На живых данных это ломало ``hello_route`` (3 таких элемента) и
   ``test_route_w1`` (2). Пустые узлы теперь отбрасываются; настоящие шаги
   проходят ту же валидацию.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.yaml_loader.loaders import load_pipeline_from_yaml


def _yaml(body: str) -> str:
    return body


class TestDefaultRouteId:
    """Проброс route_id из route.toml."""

    def test_absent_route_id_still_raises_without_default(self) -> None:
        """Автономная загрузка остаётся строгой — регресс не тихо ослаблен."""
        with pytest.raises(ValueError, match="Missing required field: route_id"):
            load_pipeline_from_yaml(_yaml("steps: []\n"))

    def test_default_route_id_used_when_absent(self) -> None:
        pipeline = load_pipeline_from_yaml(
            _yaml("steps: []\n"), default_route_id="demo"
        )
        assert pipeline.route_id == "demo"

    def test_explicit_route_id_wins_over_default(self) -> None:
        """Явный route_id в YAML не перебивается значением из манифеста."""
        pipeline = load_pipeline_from_yaml(
            _yaml("route_id: from_yaml\nsteps: []\n"), default_route_id="from_manifest"
        )
        assert pipeline.route_id == "from_yaml"

    def test_empty_route_id_falls_back_to_default(self) -> None:
        """Пустая строка не должна ломать роут — берётся имя из манифеста."""
        pipeline = load_pipeline_from_yaml(
            _yaml('route_id: ""\nsteps: []\n'), default_route_id="from_manifest"
        )
        assert pipeline.route_id == "from_manifest"


class TestCommentOnlySteps:
    """Комментарий-only элементы списка не должны ронять загрузку."""

    def test_comment_only_item_is_skipped(self) -> None:
        spec = (
            "route_id: r\n"
            "steps:\n"
            "- # просто комментарий\n"
            "- # второй комментарий\n"
            "- normalize:\n"
        )
        pipeline = load_pipeline_from_yaml(spec)
        assert pipeline.route_id == "r"
        assert len(pipeline.processors) == 1

    def test_empty_item_is_skipped(self) -> None:
        """Пустой узел (None) — эквивалент комментария."""
        spec = "route_id: r\nsteps:\n-\n-\n- normalize:\n"
        pipeline = load_pipeline_from_yaml(spec)
        assert len(pipeline.processors) == 1

    def test_all_comment_only_steps_yields_empty_pipeline(self) -> None:
        spec = "route_id: r\nsteps:\n- # только комментарии\n- # и ещё\n"
        pipeline = load_pipeline_from_yaml(spec)
        assert pipeline.route_id == "r"
        assert not pipeline.processors

    def test_real_invalid_step_still_rejected(self) -> None:
        """Отбрасывание пустых узлов не ослабляет валидацию настоящих шагов."""
        spec = "route_id: r\nsteps:\n- # комментарий\n- no_such_processor_exists\n"
        with pytest.raises(ValueError, match="Unknown or forbidden processor"):
            load_pipeline_from_yaml(spec)

    def test_malformed_step_still_rejected(self) -> None:
        """Шаг с несколькими ключами по-прежнему отвергается."""
        spec = "route_id: r\nsteps:\n- a: 1\n  b: 2\n"
        with pytest.raises(ValueError, match="must have one key"):
            load_pipeline_from_yaml(spec)


class TestNestedSteps:
    """Тот же фильтр применяется к вложенным control-flow спискам."""

    def test_nested_comment_only_item_is_skipped(self) -> None:
        # do_try принимает try_processors/catch_processors/finally_processors
        # (не 'body' — такой ключ просто игнорируется, и вложенный список
        # уходит в метод как есть).
        spec = (
            "route_id: r\n"
            "steps:\n"
            "- do_try:\n"
            "    try_processors:\n"
            "    - # комментарий\n"
            "    - normalize:\n"
        )
        pipeline = load_pipeline_from_yaml(spec)
        assert pipeline.route_id == "r"
