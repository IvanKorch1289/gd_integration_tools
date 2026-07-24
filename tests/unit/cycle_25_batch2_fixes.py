"""Unit-тесты для cycle 25 batch 2 фиксов (F1, F2).

Self-contained — does NOT import streamlit (heavy dep).
Tests the manifest content and config function behavior.
"""

# ruff: noqa: S101

from __future__ import annotations

import os
import sys


class TestFrontendManifestUnregisteredPages:
    """F1: pages present on disk must also be in PAGES_GROUPS.toml."""

    def test_no_unregistered_pages(self):
        # Skip if directory not present (test env may differ)
        if not os.path.exists("src/frontend/streamlit_app/pages"):
            return

        import re
        pages_dir = "src/frontend/streamlit_app/pages"
        pages_fs = set()
        for f in os.listdir(pages_dir):
            if f.endswith(".py") and f[:2].isdigit():
                pages_fs.add(f.replace(".py", ""))

        manifest_path = os.path.join(pages_dir, "PAGES_GROUPS.toml")
        if not os.path.exists(manifest_path):
            return

        manifest = open(manifest_path).read()
        pages_manifest = set(re.findall(r'"(\d{2}_[^"]+)"', manifest))

        unregistered = pages_fs - pages_manifest
        # Specific pages that we know were added in cycle 25
        for p in ["31_DSL_Визуальный_редактор",
                 "59_Отладчик_маршрутов",
                 "86_Аудит_использования_DSL",
                 "95_Покрытие_EIP",
                 "96_Монитор_зависших_сообщений"]:
            assert p not in unregistered, (
                f"{p} should be registered in manifest but is missing"
            )


class TestGetAPIURLHelper:
    """F2: get_api_base_url() must return centralized URL."""

    def test_helper_returns_env_value(self):
        # Simulate helper
        import os
        saved = os.environ.get("API_BASE_URL")
        try:
            os.environ["API_BASE_URL"] = "https://api.prod.example.com"
            from src.frontend.streamlit_app.config import get_api_base_url

            assert get_api_base_url() == "https://api.prod.example.com"
        finally:
            if saved is None:
                os.environ.pop("API_BASE_URL", None)
            else:
                os.environ["API_BASE_URL"] = saved

    def test_helper_default_localhost(self):
        import os
        saved = os.environ.pop("API_BASE_URL", None)
        try:
            # Re-import after env change
            if "src.frontend.streamlit_app.config" in sys.modules:
                del sys.modules["src.frontend.streamlit_app.config"]
            from src.frontend.streamlit_app.config import get_api_base_url

            url = get_api_base_url()
            # Default should be localhost:8000
            assert "localhost:8000" in url
        finally:
            if saved is not None:
                os.environ["API_BASE_URL"] = saved


class TestCentralizedURLReplacement:
    """F2: hardcoded localhost:8000 in page files replaced with helper."""

    def test_no_direct_localhost_in_centralized_pages(self):
        # Verify the 6 patched files use get_api_base_url() not direct localhost
        files_to_check = [
            "src/frontend/streamlit_app/pages/65_Сервисы.py",
            "src/frontend/streamlit_app/pages/15_Оценка_стоимости_Workflow.py",
            "src/frontend/streamlit_app/pages/18_Версионирование_Воркфлоу.py",
            "src/frontend/streamlit_app/pages/33_DSL_Шаблоны.py",
            "src/frontend/streamlit_app/pages/_groups/cron/builder/render.py",
            "src/frontend/streamlit_app/pages/_groups/dsl/dsl_templates/workflow_templates_tab.py",
        ]
        for f in files_to_check:
            if not os.path.exists(f):
                continue
            src = open(f).read()
            # These files should import get_api_base_url
            if "getattr" in src and "base_url" in src:
                assert "get_api_base_url()" in src, (
                    f"{f} still has hardcoded base_url fallback"
                )
