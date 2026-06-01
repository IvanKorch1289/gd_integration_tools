# ruff: noqa: S101
"""Тесты миграции DSL blueprints в пакет ``src.backend.dsl.blueprints``.

Sprint 7 / K3 (``[wave:s7/k3-dsl-blueprints-migrate]``):
    Проверяет, что после переноса legacy-модулей публичные импорты
    работают как через новый путь, так и через legacy shim.
"""

from __future__ import annotations

import warnings

import pytest


class TestBlueprintsPackageImport:
    """Импорт всех публичных функций через новый путь ``blueprints``."""

    def test_python_blueprints_via_package(self) -> None:
        from src.backend.dsl.blueprints import (
            api_normalize_persist_webhook,
            cdc_enrich_publish,
            file_watch_parse_validate_action,
            request_response_with_compensation,
        )

        assert callable(api_normalize_persist_webhook)
        assert callable(cdc_enrich_publish)
        assert callable(file_watch_parse_validate_action)
        assert callable(request_response_with_compensation)

    def test_macros_via_package(self) -> None:
        from src.backend.dsl.blueprints import (
            ai_qa_pipeline,
            crud_with_audit,
            etl_pipeline,
            format_bridge,
            polling_etl,
            safe_action,
            scrape_and_store,
            webhook_relay,
        )

        for fn in (
            ai_qa_pipeline,
            crud_with_audit,
            etl_pipeline,
            format_bridge,
            polling_etl,
            safe_action,
            scrape_and_store,
            webhook_relay,
        ):
            assert callable(fn)

    def test_python_blueprints_submodule(self) -> None:
        from src.backend.dsl.blueprints._python_blueprints import (
            api_normalize_persist_webhook,
        )

        assert callable(api_normalize_persist_webhook)

    def test_macros_submodule(self) -> None:
        from src.backend.dsl.blueprints.macros import etl_pipeline, safe_action

        assert callable(etl_pipeline)
        assert callable(safe_action)


class TestLegacyShim:
    """Импорт через legacy путь ``src.backend.dsl.macros`` (shim)."""

    def test_shim_re_exports_macros(self) -> None:
        from src.backend.dsl import macros as legacy_macros
        from src.backend.dsl.blueprints import macros as new_macros

        # safe_action — один и тот же объект через оба пути.
        assert legacy_macros.safe_action is new_macros.safe_action
        assert legacy_macros.etl_pipeline is new_macros.etl_pipeline
        assert legacy_macros.crud_with_audit is new_macros.crud_with_audit

    def test_shim_all_exports_match(self) -> None:
        from src.backend.dsl import macros as legacy_macros
        from src.backend.dsl.blueprints import macros as new_macros

        assert set(legacy_macros.__all__) == set(new_macros.__all__)

    def test_shim_deprecation_warning_under_feature_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если feature_flag активен, импорт shim должен выдавать DeprecationWarning."""
        import importlib

        from src.backend.core.config.features import feature_flags

        monkeypatch.setattr(feature_flags, "dsl_blueprints_migrate", True)

        import src.backend.dsl.macros as shim_module

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always", DeprecationWarning)
            importlib.reload(shim_module)

        # Проверяем, что хотя бы один DeprecationWarning связан с миграцией.
        relevant = [
            w
            for w in captured
            if issubclass(w.category, DeprecationWarning)
            and "blueprints" in str(w.message).lower()
        ]
        assert relevant, "ожидался DeprecationWarning при активном feature flag"
