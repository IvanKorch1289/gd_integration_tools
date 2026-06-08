"""YAML ↔ steps синхронизация для DSL Visual Editor (S77 W3 split).

Извлечено из ``31_DSL_Visual_Editor.py``. Pure-функции ``yaml_to_steps``
и ``build_yaml_from_steps`` не зависят от Streamlit; ``sync_yaml``
использует ``st.session_state`` (lazy import для совместимости с
test-runs без ``[frontend]`` extra).

API backward-compatible: private имена из оригинала
(``_default_yaml``, ``_sync_yaml``, ``_try_load``, ``_yaml_to_steps``,
``_build_yaml_from_steps``) → public без underscore для unit-тестов.

Wave: ``[wave:s77/w3-dsl-editor-split]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml as _yaml

from src.backend.services.dsl_portal import Pipeline, load_pipeline_from_yaml

if TYPE_CHECKING:
    pass

__all__ = (
    "build_yaml_from_steps",
    "sync_yaml",
    "try_load",
    "yaml_to_steps",
)

# Re-export default_yaml из constants.py для backward-compat с
# местами, которые импортировали его из yaml_sync.


def yaml_to_steps(yaml_str: str) -> tuple[dict, list[dict]]:
    """Извлекает meta (route_id/source/description) и список шагов из YAML.

    Args:
        yaml_str: YAML-исходник.

    Returns:
        Tuple ``(meta, steps)``:
        * ``meta`` — ``{"route_id": ..., "source": ..., "description": ...}``
        * ``steps`` — ``[{"type": str, "params": dict}, ...]``

        На любой ошибке парсинга возвращает ``({}, [])``.
    """
    try:
        data = _yaml.safe_load(yaml_str) or {}
    except _yaml.YAMLError:
        return {}, []
    if not isinstance(data, dict):
        return {}, []
    meta = {
        "route_id": data.get("route_id", ""),
        "source": data.get("source", ""),
        "description": data.get("description", ""),
    }
    raw = data.get("processors", []) or []
    steps: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            steps.append({"type": item, "params": {}})
        elif isinstance(item, dict) and len(item) == 1:
            name = next(iter(item))
            params = item[name] if isinstance(item[name], dict) else {}
            steps.append({"type": name, "params": params})
    return meta, steps


def build_yaml_from_steps(meta: dict, steps: list[dict]) -> str:
    """Собирает YAML из meta и шагов (формат, понятный ``yaml_loader``).

    Args:
        meta: ``{"route_id", "source", "description"}``.
        steps: ``[{"type": str, "params": dict}, ...]``.

    Returns:
        YAML-строка с UTF-8 unicode и sort_keys=False (порядок полей
        сохраняется: route_id → source → description → processors).
    """
    out: dict = {"route_id": meta.get("route_id") or "my.route"}
    if meta.get("source"):
        out["source"] = meta["source"]
    if meta.get("description"):
        out["description"] = meta["description"]
    if steps:
        out["processors"] = [{s["type"]: s.get("params") or {}} for s in steps]
    return _yaml.dump(out, allow_unicode=True, sort_keys=False)


def try_load(yaml_str: str) -> tuple[Pipeline | None, str | None]:
    """Локально парсит YAML в :class:`Pipeline`.

    Args:
        yaml_str: YAML-исходник.

    Returns:
        ``(pipeline, None)`` при успехе, ``(None, error_str)`` при ошибке.
    """
    try:
        return load_pipeline_from_yaml(yaml_str), None
    except Exception as exc:  # noqa: BLE001 — UI должен показать любую ошибку.
        return None, str(exc)


def sync_yaml() -> None:
    """Re-serialize ``canvas_steps`` → ``yaml_output`` в session state.

    Используется в Canvas-режиме после любого изменения
    ``canvas_steps`` или ``meta_route`` для синхронизации
    YAML preview с текущим состоянием.

    Lazy-imports ``streamlit`` — функция не нужна вне Streamlit-runtime
    (tests для ``yaml_to_steps`` / ``build_yaml_from_steps`` не вызывают
    её). Без lazy-import тесты ломаются при отсутствии ``[frontend]``
    extra в venv.
    """
    import streamlit as st

    st.session_state.yaml_output = build_yaml_from_steps(
        st.session_state.meta_route, st.session_state.canvas_steps
    )
