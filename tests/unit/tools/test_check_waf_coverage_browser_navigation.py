"""F-AP2 (re-audit 2026-10-01, HEAD 2037f9d59) — gate не должен быть слеп к браузеру.

``tools/check_waf_coverage.py`` — обязательный CI-гейт (V15 R-V15-5,
``make check-waf-coverage``). До фикса он знал только ``httpx.AsyncClient``
/ ``httpx.Client``: ``grep -c "goto\\|playwright\\|browser"`` по исходнику
давал 0, и гейт рапортовал «WAF coverage OK: 0 violations» при 10
реальных ``page.goto(...)`` без валидации URL.

Тесты фиксируют: гейт обязан видеть браузерную навигацию, exempt-prefix
на transport-каталог не должен скрывать ``browser.py``, а allowlist
обязан содержать осознанные записи с обоснованием.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_TOOL = Path("tools/check_waf_coverage.py")


def _load_tool():
    """Загружает tools/check_waf_coverage.py как модуль (пакет tools не импортируется)."""
    spec = importlib.util.spec_from_file_location("_waf_cov_under_test", _TOOL)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def waf() -> object:
    """Загруженный модуль гейта."""
    return _load_tool()


class TestBrowserNavigationIsDetected:
    """page.goto / context.goto / self._page.goto — нарушение."""

    @staticmethod
    def _call_node(source: str):
        """Достаёт ast.Call из тела ``async def``: ``await`` невалиден в eval-режиме."""
        import ast

        module = ast.parse(f"async def _probe():\n    {source}\n")
        fn = module.body[0]
        assert isinstance(fn, ast.AsyncFunctionDef)
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                return node
        raise AssertionError(f"не найден Call в {source!r}")

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("await page.goto(url)", True),
            ("await context.goto(url)", True),
            ("await self._page.goto(url)", True),
            ("await self.page.goto(url)", True),
            ("await tab.goto(url)", True),
            ("await browser_context.goto(url)", True),
            ("await page.reload()", True),
        ],
    )
    def test_navigation_calls_are_violations(
        self, waf: object, source: str, expected: bool
    ) -> None:
        """Каждый наблюдавшийся в коде вид навигации обязан ловиться."""
        node = self._call_node(source)
        assert waf._is_browser_navigation_violation(node) is expected

    @pytest.mark.parametrize(
        "source",
        [
            "service.goto(url)",
            "queue.put(item)",
            "client.get(url)",
            "obj.navigate(url)",
        ],
    )
    def test_non_browser_calls_are_not_violations(
        self, waf: object, source: str
    ) -> None:
        """Чужие ``.goto()`` у не-браузерных объектов — ложных срабатываний нет."""
        node = self._call_node(source)
        assert waf._is_browser_navigation_violation(node) is False


class TestExemptionIsNotBlanket:
    """Exempt-префикс transport-каталога не должен скрывать browser.py."""

    def test_browser_transport_is_not_exempt(self, waf: object) -> None:
        """F-AP2: browser.py обязан сканироваться гейтом."""
        assert not waf._is_internal_exempt(
            "src/backend/infrastructure/clients/transport/browser.py"
        )

    def test_browser_processor_is_not_exempt(self, waf: object) -> None:
        """rpa_browser.py и dsl_browser.py не exempt'ятся."""
        assert not waf._is_internal_exempt(
            "src/backend/dsl/engine/processors/rpa_browser.py"
        )
        assert not waf._is_internal_exempt("src/backend/core/dsl_browser/dsl.py")

    @pytest.mark.parametrize(
        "rel_path",
        [
            "src/backend/core/net/waf.py",
            "src/backend/infrastructure/clients/transport/http_httpx.py",
            "src/backend/infrastructure/clients/transport/http_upstream.py",
            "src/backend/infrastructure/clients/transport/httpx_cache_adapter.py",
            "src/backend/infrastructure/clients/transport/http/session_mixin.py",
        ],
    )
    def test_waf_http_plumbing_stays_exempt(self, waf: object, rel_path: str) -> None:
        """Собственная HTTP-обвязка WAF остаётся exempt — регрессии нет."""
        assert waf._is_internal_exempt(rel_path)


class TestRealRepoState:
    """Реальный код репозитория: контракт изменился с F-AP1.

    До фикса браузерная навигация была **объявлена** в allowlist как долг.
    Теперь url-guard написан (``core/net/url_guard.py``), навигация идёт
    через guard, а гейт научен распознавать защищённый callsite. Поэтому
    прежние утверждения «навигация flagged» и «файлы в allowlist» больше
    не верны — и были бы прямой ложью, если бы их оставили.
    """

    def test_navigation_is_no_longer_flagged_because_it_is_guarded(
        self, waf: object
    ) -> None:
        """Защищённая навигация не нарушение — гейт проверяет guard."""
        path = Path("src/backend/infrastructure/clients/transport/browser.py")
        assert not waf._scan_file(path), (
            "browser.py под url_guard не должен давать нарушений"
        )

    def test_browser_modules_reference_the_url_guard(self) -> None:
        """Все три точки входа в браузер зовут канонический guard."""
        for rel in (
            "src/backend/dsl/engine/processors/rpa_browser.py",
            "src/backend/infrastructure/clients/transport/browser.py",
            "src/backend/core/dsl_browser/dsl.py",
        ):
            text = Path(rel).read_text(encoding="utf-8")
            assert "assert_safe_url" in text, f"{rel} не вызывает url_guard"

    def test_allowlist_no_longer_carries_browser_entries(self) -> None:
        """Долг снят: браузерных записей в allowlist больше нет."""
        text = Path("tools/check_waf_coverage_allowlist.txt").read_text(
            encoding="utf-8"
        )
        entries = [
            line
            for line in text.splitlines()
            if line.strip().startswith("src/backend/")
            and not line.strip().startswith("#")
        ]
        assert not entries, f"в allowlist остались записи: {entries}"

    def test_url_guard_module_exists(self) -> None:
        """Канонический guard лежит в core/net и является единственным."""
        path = Path("src/backend/core/net/url_guard.py")
        assert path.exists(), "core/net/url_guard.py обязателен (F-AP1)"
        text = path.read_text(encoding="utf-8")
        assert "def assert_safe_url" in text
        assert "def is_safe_url" in text
