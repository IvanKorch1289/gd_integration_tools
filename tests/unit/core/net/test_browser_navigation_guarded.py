"""F-AP1: браузерная навигация обязана проходить через url-guard.

Тест-контракт для трёх точек входа в Playwright:

* ``BrowserClient._safe_goto`` (``infrastructure/clients/transport/browser.py``);
* ``rpa_browser._guarded_goto`` (``dsl/engine/processors/rpa_browser.py``);
* ``BrowserDSL._guarded_goto`` (``core/dsl_browser/dsl.py``).

Сам ``url_guard`` проверяется в ``tests/unit/core/net/test_url_guard.py``.
Здесь важно другое: что ни одна точка навигации не обходит guard, и что
исторические payload'ы не доходят до ``page.goto``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

BROWSER_PATHS = (
    "src/backend/infrastructure/clients/transport/browser.py",
    "src/backend/dsl/engine/processors/rpa_browser.py",
    "src/backend/core/dsl_browser/dsl.py",
)

#: Payload'ы, каждый из которых реально доходил до браузера (9/9 в репро).
PAYLOADS: tuple[str, ...] = (
    "file:///etc/passwd",
    "data:text/html,<script>alert(1)</script>",
    "chrome://settings",
    "about:blank",
    "javascript:alert(1)",
    "http://169.254.169.254/latest/meta-data/",
    "http://2130706433/",
    "http://127.0.0.1:8080/admin",
    "http://localhost/admin",
)


class TestNoUnguardedNavigation:
    """В каждом файле навигация обязана быть обёрнута в guard."""

    @pytest.mark.parametrize("rel_path", BROWSER_PATHS)
    def test_every_goto_goes_through_guard(self, rel_path: str) -> None:
        """Каждый ``*.goto`` лежит внутри функции с url-guard.

        Args:
            rel_path: Путь проверяемого модуля относительно корня.

        """
        path = REPO_ROOT / rel_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents: dict[int, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[id(child)] = parent

        guarded: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    func = inner.func
                    name = getattr(func, "id", None) or getattr(func, "attr", None)
                    if name in {"assert_safe_url", "is_safe_url"}:
                        guarded.add(node.lineno)
                        break

        offenders: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "goto":
                continue
            # Метод самой обёртки — та точка, где guard применяется.
            receiver = getattr(func.value, "attr", None) or getattr(
                func.value, "id", None
            )
            if receiver in {"_safe_goto", "_guarded_goto"}:
                continue
            chain: list[ast.AST] = []
            cursor: ast.AST | None = node
            while cursor is not None:
                cursor = parents.get(id(cursor))
                if cursor is not None:
                    chain.append(cursor)
            if not any(
                isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                and parent.lineno in guarded
                for parent in chain
            ):
                offenders.append(node.lineno)

        assert not offenders, (
            f"{rel_path}: навигация вне url-guard на строках {offenders}"
        )

    def test_allowlist_has_no_browser_entries(self) -> None:
        """Долг снят: браузерных callsite'ов в allowlist быть не должно.

        До фикса три файла числились в allowlist как «явный долг». Теперь
        защита проверяется гейтом, поэтому список снова пуст.
        """
        allowlist = REPO_ROOT / "tools" / "check_waf_coverage_allowlist.txt"
        text = allowlist.read_text(encoding="utf-8")
        entries = [
            line
            for line in text.splitlines()
            if line.strip().startswith("src/backend/")
            and not line.strip().startswith("#")
        ]
        assert not entries, f"в allowlist остались записи: {entries}"


class TestWafGateUnderstandsGuard:
    """Гейт WAF обязан отличать защищённую навигацию от голой."""

    def test_gate_passes_with_guard_and_no_allowlist(self) -> None:
        """С guard'ом и пустым allowlist гейт зелёный."""
        import subprocess
        import sys

        result = subprocess.run(  # noqa: S603 — литеральный argv, shell=False
            [sys.executable, str(REPO_ROOT / "tools" / "check_waf_coverage.py")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_gate_flags_navigation_without_guard(self, tmp_path: Path) -> None:
        """Без guard'а гейт обязан поймать тот же файл.

        Это защита от «забыли применить guard в новом методе»: гейт
        останавливает прогон, а не ждёт ручной allowlist.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "waf_gate", REPO_ROOT / "tools" / "check_waf_coverage.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        unguarded = tmp_path / "unguarded_browser.py"
        unguarded.write_text(
            "async def navigate(page, url):\n    return await page.goto(url)\n",
            encoding="utf-8",
        )
        guarded = tmp_path / "guarded_browser.py"
        guarded.write_text(
            "async def navigate(page, url):\n"
            "    from src.backend.core.net.url_guard import assert_safe_url\n"
            "    return await page.goto(assert_safe_url(url))\n",
            encoding="utf-8",
        )

        assert module._scan_file(unguarded), "голый page.goto должен быть нарушением"
        assert not module._scan_file(guarded), "page.goto под guard не нарушение"


class TestPayloadsRejectedBeforeBrowser:
    """Исторические payload'ы не доходят до браузера."""

    @pytest.mark.parametrize("url", PAYLOADS)
    def test_payload_blocked(self, url: str) -> None:
        """Guard отбивает payload до навигации.

        Args:
            url: Проверяемый payload.

        """
        from src.backend.core.net.url_guard import UrlNotAllowedError, assert_safe_url

        with pytest.raises(UrlNotAllowedError):
            assert_safe_url(url)


class TestRedirectIsGuarded:
    """B-3 (adversarial review): редиректы не должны обходить guard.

    ``page.goto`` следует за редиректами внутри браузера, поэтому проверки
    только начального URL недостаточно: публичный URL с ``302 ->
    http://169.254.169.254/`` уходил бы во внутреннюю сеть. Поэтому на
    страницу вешается route-handler, перепроверяющий каждый запрос.
    """

    @staticmethod
    def _client() -> object:
        """Собрать минимальный экземпляр BrowserClient без запуска браузера.

        Returns:
            Экземпляр с одним нужным полем ``_allow_private``.

        """
        from src.backend.infrastructure.clients.transport.browser import BrowserClient

        client = BrowserClient.__new__(BrowserClient)
        client._allow_private = False  # noqa: SLF001
        return client

    @staticmethod
    def _fake_page() -> object:
        """Фейковая страница: накапливает route-handler и вызовы goto.

        Returns:
            Объект с ``route``/``goto`` и журналом вызовов.

        """

        class _Route:
            def __init__(self) -> None:
                self.aborted = False
                self.continued = False

            async def abort(self) -> None:
                self.aborted = True

            async def continue_(self) -> None:
                self.continued = True

        class _Request:
            def __init__(self, url: str) -> None:
                self.url = url

        class _Page:
            def __init__(self) -> None:
                self.handlers: list[object] = []
                self.routes: list[object] = []
                self.goto_calls: list[str] = []
                self.goto_result = "response"

            async def route(self, pattern: str, handler: object) -> None:
                self.routes.append(pattern)
                self.handlers.append(handler)

            async def goto(self, url: str, **kwargs: object) -> str:
                self.goto_calls.append(url)
                return self.goto_result

        return _Page()

    @pytest.mark.asyncio
    async def test_route_handler_installed_once(self) -> None:
        """Handler ставится на страницу один раз, до ухода в сеть."""
        import inspect

        from src.backend.core.net.url_guard import UrlNotAllowedError

        page = self._fake_page()
        client = self._client()
        with pytest.raises(UrlNotAllowedError):
            await client._safe_goto(page, "http://169.254.169.254/")  # noqa: SLF001
        assert page.routes == [], "unsafe URL must be rejected BEFORE any route is set"
        assert page.goto_calls == []

        await client._safe_goto(page, "https://example.com/")  # noqa: SLF001
        assert page.routes == ["**/*"]
        await client._safe_goto(page, "https://example.com/2")  # noqa: SLF001
        assert len(page.handlers) == 1, "handler must not be registered twice"
        assert inspect.iscoroutinefunction(page.handlers[0])

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "hop",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1:5432/",
            "http://10.0.0.5/admin",
            "http://localhost./",
            "http://0x7f.0.0.1/",
            "http://100.64.1.1/",
            "file:///etc/passwd",
        ],
    )
    async def test_unsafe_redirect_hop_is_aborted(self, hop: str) -> None:
        """Каждый хоп редиректа перепроверяется; небезопасный — abort."""
        page = self._fake_page()
        client = self._client()
        await client._safe_goto(page, "https://example.com/")  # noqa: SLF001
        handler = page.handlers[0]

        class _Route:
            def __init__(self) -> None:
                self.aborted = False
                self.continued = False

            async def abort(self) -> None:
                self.aborted = True

            async def continue_(self) -> None:
                self.continued = True

        class _Request:
            def __init__(self, url: str) -> None:
                self.url = url

        route = _Route()
        await handler(route, _Request(hop))
        assert route.aborted and not route.continued, f"{hop} должен быть прерван"

    @pytest.mark.asyncio
    async def test_public_redirect_hop_is_continued(self) -> None:
        """Публичный хоп редиректа пропускается — guard не ломает CDN-редиректы."""
        page = self._fake_page()
        client = self._client()
        await client._safe_goto(page, "https://example.com/")  # noqa: SLF001
        handler = page.handlers[0]

        class _Route:
            def __init__(self) -> None:
                self.aborted = False
                self.continued = False

            async def abort(self) -> None:
                self.aborted = True

            async def continue_(self) -> None:
                self.continued = True

        class _Request:
            def __init__(self, url: str) -> None:
                self.url = url

        route = _Route()
        await handler(route, _Request("https://cdn.example.org/asset.js"))
        assert route.continued and not route.aborted
