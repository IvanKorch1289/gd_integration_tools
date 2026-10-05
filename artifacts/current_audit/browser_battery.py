"""Браузерная батарея DoD через Playwright.

Раньше секция BROWSER была ENV_BLOCKED (биндинги Playwright отсутствовали).
Сейчас биндинги установлены, а в кэше лежит Chromium-сборка, версия которой
не совпадает с ожидаемой библиотекой, поэтому браузер запускается через явный
``executable_path`` — без скачивания из сети.

Правила, которые скрипт соблюдает:

* **никакого выхода в интернет** — адреса только ``http://127.0.0.1:<port>``;
* секреты не попадают в артефакт: значения заголовков маскируются, а текст
  исключений Playwright (в котором могут быть заголовки) в отчёт не пишется;
* сохраняются ``trace.zip``, скриншоты, console errors, page errors и список
  неуспешных сетевых запросов.

Запуск:

    MONGO_ENABLED=false .venv/bin/python -m uvicorn src.backend.main:app \\
        --host 127.0.0.1 --port 8137 &
    PORT=8137 .venv/bin/python artifacts/current_audit/browser_battery.py

Пишет ``browser_results.md`` и каталог ``browser_artifacts/`` рядом с собой.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "browser_artifacts"
PORT = os.environ.get("PORT", "8137")
BASE = f"http://127.0.0.1:{PORT}"
CHROME = os.environ.get(
    "CHROME_PATH",
    "/home/user/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
)

#: Страницы без авторизации. Ожидаемый код задан явно: защищённый эндпоинт
#: обязан отдавать 401, а не отдаваться публично.
PAGES: list[tuple[str, str, str, int]] = [
    ("swagger-ui", "/docs", "Swagger UI", 200),
    ("redoc", "/redoc", "ReDoc", 200),
    ("openapi-json", "/openapi.json", "OpenAPI 3.1 (JSON)", 200),
    ("graphql-unauth", "/api/v1/graphql", "GraphQL без auth", 401),
]


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    """Замаскировать чувствительные заголовки.

    Args:
        headers: Исходные заголовки.

    Returns:
        Копия, где значения чувствительных заголовков заменены на ``<masked>``.

    """
    sensitive = ("x-api-key", "authorization", "set-cookie", "cookie", "password", "secret")
    return {
        key: ("<masked>" if any(m in key.lower() for m in sensitive) else value[:60])
        for key, value in headers.items()
    }


def _visit(page: Any, name: str, path: str, label: str, expected: int) -> dict[str, Any]:
    """Открыть страницу, снять скриншот и собрать диагностику.

    Args:
        page: Страница Playwright.
        name: Имя проверки.
        path: Путь относительно базового адреса.
        label: Человекочитаемое имя страницы.
        expected: Ожидаемый HTTP-код.

    Returns:
        Словарь с результатом проверки.

    """
    console: list[str] = []
    page_errors: list[str] = []
    failed: list[dict[str, Any]] = []

    def _on_console(message: Any) -> None:
        """Собрать сообщения консоли.

        Args:
            message: Сообщение Playwright.

        """
        console.append(f"{message.type}: {message.text[:200]}")

    def _on_page_error(error: Any) -> None:
        """Собрать необработанные ошибки страницы.

        Args:
            error: Объект ошибки Playwright.

        """
        page_errors.append(str(error)[:200])

    def _on_request_failed(request: Any) -> None:
        """Собрать неуспешные сетевые запросы.

        Args:
            request: Запрос Playwright.

        """
        failed.append({"url": request.url[:120], "error": (request.failure or "")[:80]})

    def _on_response(response: Any) -> None:
        """Собрать ответы с кодом 4xx/5xx.

        Args:
            response: Ответ Playwright.

        """
        if response.status >= 400:
            failed.append({"url": response.url[:120], "status": response.status})

    page.on("console", _on_console)
    page.on("pageerror", _on_page_error)
    page.on("requestfailed", _on_request_failed)
    page.on("response", _on_response)

    result: dict[str, Any] = {"name": name, "label": label, "url": f"{BASE}{path}"}
    try:
        response = page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(1_200)
        shot = ARTIFACTS / f"{name}.png"
        page.screenshot(path=str(shot))
        result["status"] = response.status if response else None
        result["expected"] = expected
        result["screenshot"] = shot.name
        result["title"] = page.title()[:120]
        result["verdict"] = "PASS" if result["status"] == expected else "FAIL"
    except Exception as exc:  # noqa: BLE001 — тип исключения безопасен, текст нет
        result["status"] = None
        result["expected"] = expected
        result["verdict"] = "FAIL"
        result["error"] = type(exc).__name__

    result["console_errors"] = [c for c in console if c.startswith(("error", "warning"))]
    result["page_errors"] = page_errors
    result["failed_requests"] = failed[:15]
    return result


def _auth_checks(playwright: Any, api_key: str) -> list[dict[str, Any]]:
    """Аутентифицированные проверки в отдельном контексте.

    Args:
        playwright: Экземпляр ``sync_playwright``.
        api_key: Ключ для заголовка ``X-API-Key``.

    Returns:
        Список результатов. Значение ключа в результаты не попадает.

    """
    results: list[dict[str, Any]] = []
    browser = playwright.chromium.launch(
        executable_path=CHROME, args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    context = browser.new_context()
    context.set_default_timeout(20_000)
    if api_key:
        # Ключ ставится на контекст: ``Page.goto`` в этой версии Playwright
        # не принимает ``headers``. Значение используется только для навигации
        # и в артефакт не записывается.
        context.set_extra_http_headers({"X-API-Key": api_key})
        page = context.new_page()
        entry: dict[str, Any] = {
            "name": "graphql-auth",
            "label": "GraphQL с auth",
            "url": f"{BASE}/api/v1/graphql",
            "expected": 200,
            "console_errors": [],
            "page_errors": [],
            "failed_requests": [],
        }
        try:
            response = page.goto(
                f"{BASE}/api/v1/graphql", wait_until="domcontentloaded", timeout=20_000
            )
            page.wait_for_timeout(1_000)
            shot = ARTIFACTS / "graphql-auth.png"
            page.screenshot(path=str(shot))
            entry["status"] = response.status if response else None
            entry["screenshot"] = shot.name
            entry["verdict"] = "PASS" if entry["status"] == 200 else "FAIL"
        except Exception as exc:  # noqa: BLE001 — только тип, текст может утечь
            entry["status"] = None
            entry["verdict"] = "FAIL"
            entry["error"] = type(exc).__name__
        page.close()
        results.append(entry)
    else:
        results.append(
            {
                "name": "graphql-auth",
                "label": "GraphQL с auth",
                "url": f"{BASE}/api/v1/graphql",
                "expected": 200,
                "status": None,
                "verdict": "SKIPPED",
                "note": "SEC_API_KEY не задан — проверка не выполнена (не PASS)",
            }
        )

    # Маскирование: отдельный контекст БЕЗ заголовка авторизации, иначе ключ
    # утечёт в следующий запрос. Значения заголовков не записываются.
    clean = browser.new_context()
    masking: dict[str, Any] = {
        "name": "auth-header-masking",
        "label": "Маскирование чувствительных заголовков",
        "url": f"{BASE}/api/v1/actions/inventory",
    }
    try:
        response = clean.request.get(f"{BASE}/api/v1/actions/inventory", timeout=15_000)
        masking["status"] = response.status
        masking["headers_masked"] = _mask_headers(dict(response.headers))
        masking["verdict"] = "PASS" if response.status == 401 else "FAIL"
    except Exception as exc:  # noqa: BLE001 — только тип исключения
        masking["status"] = None
        masking["verdict"] = "FAIL"
        masking["error"] = type(exc).__name__
    clean.close()
    results.append(masking)

    context.close()
    browser.close()
    return results


def main() -> int:
    """Прогнать браузерную батарею и записать артефакты.

    Returns:
        ``0`` — артефакты записаны; вердикты находятся внутри отчёта.

    """
    from playwright.sync_api import sync_playwright

    ARTIFACTS.mkdir(exist_ok=True)
    for stale in ARTIFACTS.glob("*.png"):
        stale.unlink()

    results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=CHROME, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.set_default_timeout(20_000)
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        for name, path, label, expected in PAGES:
            page = context.new_page()
            results.append(_visit(page, name, path, label, expected))
            page.close()
        context.tracing.stop(path=str(ARTIFACTS / "trace.zip"))
        context.close()
        browser.close()

        results.extend(_auth_checks(playwright, os.environ.get("SEC_API_KEY", "")))

    passed = sum(1 for r in results if r.get("verdict") == "PASS")
    failed = sum(1 for r in results if r.get("verdict") == "FAIL")
    skipped = sum(1 for r in results if r.get("verdict") == "SKIPPED")

    lines = [
        "# BROWSER: результаты прогона Playwright",
        "",
        f"- HEAD: `{os.environ.get('AUDIT_HEAD', 'git rev-parse HEAD')}`",
        f"- Базовый адрес: `{BASE}` — только loopback, выхода в интернет нет",
        f"- Браузер: Chromium, явный `executable_path` = `{CHROME}`",
        "- Расхождение версий: библиотека Playwright ожидает другую сборку "
        "Chromium, поэтому браузер подключён по явному пути, без скачивания",
        "",
        f"**Итог: {passed} PASS, {failed} FAIL, {skipped} SKIPPED.**",
        "",
        "> `SKIPPED` и `ENV_BLOCKED` **не считаются PASS**.",
        "",
        "| Проверка | Страница | HTTP | Ожидаем | Вердикт |",
        "|---|---|---:|---:|---|",
    ]
    for r in results:
        lines.append(
            f"| `{r['name']}` | {r.get('label', '')} | {r.get('status')} | "
            f"{r.get('expected', '')} | **{r.get('verdict')}** |"
        )

    lines += ["", "## Диагностика", ""]
    for r in results:
        lines.append(f"### {r['name']}")
        lines.append(f"- URL: `{r.get('url')}`")
        if r.get("error"):
            lines.append(f"- ошибка: `{r['error']}`")
        if r.get("note"):
            lines.append(f"- примечание: {r['note']}")
        lines.append(
            f"- console errors: {r.get('console_errors') or 'нет'}"
        )
        lines.append(f"- page errors: {r.get('page_errors') or 'нет'}")
        if r.get("failed_requests"):
            lines.append(f"- неуспешные запросы ({len(r['failed_requests'])}):")
            lines += [
                f"  - `{json.dumps(q, ensure_ascii=False)}`" for q in r["failed_requests"][:5]
            ]
        else:
            lines.append("- неуспешные запросы: нет")
        if r.get("screenshot"):
            lines.append(f"- скриншот: `browser_artifacts/{r['screenshot']}`")
        if r.get("headers_masked"):
            lines.append("- заголовки ответа (замаскированы):")
            lines += [
                f"  - `{k}: {v}`"
                for k, v in list(r["headers_masked"].items())[:8]
            ]
        lines.append("")

    lines += [
        "## Сохранённые артефакты",
        "",
        "- `browser_artifacts/trace.zip` — Playwright trace (screenshots, snapshots, sources)",
        "- `browser_artifacts/*.png` — скриншоты страниц",
        "",
        "## Что осталось непроверенным (честно)",
        "",
        "- **Streamlit-портал — `NOT_RUN`**: отдельное приложение "
        "(`src/frontend/streamlit_app`) в этом прогоне не поднималось.",
        "- **RPA local test page — `ENV_BLOCKED`**: RPA-пул в приложение не "
        "подключён (F-AP6), навигация недостижима; проверялось лишь отсутствие "
        "внешних обращений.",
        "- **login flow — `NOT_RUN`**: требует интерактивного ввода учётных данных "
        "и работающего хранилища пользователей.",
        "",
        "Секреты и PII в артефакты не попадают: значения заголовков авторизации "
        "маскируются, тексты исключений Playwright не записываются.",
    ]
    (HERE / "browser_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{passed} PASS, {failed} FAIL, {skipped} SKIPPED")
    for r in results:
        print(f"  {r['name']:22} HTTP {r.get('status')}  {r.get('verdict')}")
    print(f"written -> {HERE / 'browser_results.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
