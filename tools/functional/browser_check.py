"""Функциональная проверка HTTP-слоя из реального браузера (Chromium).

Зачем отдельный инструмент, если есть :mod:`tools.functional.http_check`
---------------------------------------------------------------------------
cURL-батарея этот класс дефектов пропускала систематически:

* ``curl`` без ``--compressed`` не шлёт ``Accept-Encoding: gzip`` вовсе, то есть
  не воспроизводит поведение браузера;
* ``curl`` на рассогласованный заголовок/тело (``Content-Encoding: gzip``
  при несжатом JSON) **молча** отдаёт мусор и завершается с кодом 0;
* ``httpx`` на то же самое падает с ``DecodingError``, но cURL-прогон этого
  не показывал.

Chromium же всегда запрашивает ``Accept-Encoding: gzip, deflate, br``, поэтому
именно браузерный прогон воспроизводит P0-баг 2026-10-06: компрессия стояла
ВНУТРИ ``DataMaskingMiddleware``, маскер получал gzip-байты, падал на
``decode("utf-8")`` и подменял ответ заглушкой
``{"error": "response_masking_failed", ...}`` с исходным заголовком
``Content-Encoding: gzip``. Настоящие данные терялись, клиент получал HTTP 200.

Проверка идёт через ``page.evaluate(fetch(...))`` — то есть тем же путём, каким
Streamlit-портал грузит данные: из браузера, с его собственными заголовками.

Запуск::

    .venv/bin/python tools/functional/browser_check.py \\
        --base-url http://127.0.0.1:8199 --api-key local-func-test-key
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

#: Пути с JSON-телом заметно больше gzip_minimum_size (500).
CHECK_PATHS = ("/api/v1/admin/actions", "/ready", "/openapi.json")

#: Заглушка, которую подставлял сломанный конвейер масок��в.
MASKING_STUB = "response_masking_failed"

#: Кандидаты исполняемого файла Chromium — версия ревизии playwright в venv
#: может не совпадать с установленной, поэтому путь задаётся явно.
CHROMIUM_CANDIDATES = (
    "/home/user/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
)

#: JS, исполняемый в контексте страницы. Возвращает диагностику одним объектом,
#: потому что исключение внутри fetch нельзя прокинуть наружу как объект.
_FETCH_JS = """
async ({path, apiKey}) => {
  const headers = {'X-API-Key': apiKey};
  try {
    const resp = await fetch(path, {headers, cache: 'no-store'});
    const text = await resp.text();
    return {
      ok: true,
      status: resp.status,
      contentEncoding: resp.headers.get('content-encoding') || '',
      contentType: resp.headers.get('content-type') || '',
      length: text.length,
      head: text.slice(0, 200),
      isJson: (() => { try { JSON.parse(text); return true; } catch { return false; } })(),
      keys: (() => { try { return Object.keys(JSON.parse(text)).slice(0, 8); }
                     catch { return []; } })(),
    };
  } catch (err) {
    return {ok: false, error: String(err && err.message || err)};
  }
}
"""


@dataclass
class Result:
    """Результат одной браузерной проверки."""

    name: str
    status: str
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _first_existing(candidates: tuple[str, ...]) -> str | None:
    """Первый существующий путь из списка кандидатов."""
    from pathlib import Path

    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def run_checks(base_url: str, api_key: str, executable: str | None) -> list[Result]:
    """Прогнать браузерные проверки и вернуть результаты."""
    results: list[Result] = []
    launch_kwargs: dict[str, Any] = {
        "args": ["--no-sandbox", "--disable-dev-shm-usage"]
    }
    if executable:
        launch_kwargs["executable_path"] = executable

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(**launch_kwargs)
        except PlaywrightError as exc:
            return [
                Result(
                    "browser:launch", "SKIP", f"Chromium недоступен: {str(exc)[:120]}"
                )
            ]

        try:
            page = browser.new_page()
            # Базовый origin нужен, чтобы fetch шёл относительными путями.
            page.goto(
                f"{base_url}/health", wait_until="domcontentloaded", timeout=30_000
            )

            results.append(
                Result(
                    "browser:version",
                    "PASS",
                    f"Chromium {browser.version}, страница {page.url}",
                )
            )

            for path in CHECK_PATHS:
                name = f"browser:{path}"
                data = page.evaluate(_FETCH_JS, {"path": path, "apiKey": api_key})

                if not data.get("ok"):
                    results.append(
                        Result(
                            name,
                            "FAIL",
                            f"fetch упал в браузере: {data.get('error', '?')}",
                        )
                    )
                    continue

                if data.get("status") == 401:
                    results.append(Result(name, "SKIP", "ключ не принят — 401"))
                    continue

                head = data.get("head", "")
                if MASKING_STUB in head:
                    results.append(
                        Result(
                            name,
                            "FAIL",
                            "ответ подменён заглушкой маскирования "
                            f"(status={data.get('status')}): {head[:90]}",
                        )
                    )
                    continue

                if not data.get("isJson"):
                    results.append(
                        Result(
                            name, "FAIL", f"тело не разбирается как JSON: {head[:90]}"
                        )
                    )
                    continue

                encoding = data.get("contentEncoding", "")
                results.append(
                    Result(
                        name,
                        "PASS",
                        f"status={data.get('status')} "
                        f"encoding={encoding or '-'} "
                        f"len={data.get('length')} keys={data.get('keys')}",
                    )
                )
        finally:
            browser.close()

    return results


def main(argv: list[str] | None = None) -> int:
    """Прогнать браузерные проверки и вернуть код exit."""
    parser = argparse.ArgumentParser(
        description="Функциональная проверка HTTP-слоя из реального браузера"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8185")
    parser.add_argument("--api-key", default="local-func-test-key")
    parser.add_argument("--chromium", default="")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    executable = args.chromium or _first_existing(CHROMIUM_CANDIDATES)

    results = run_checks(base, args.api_key, executable or None)

    width = max((len(r.name) for r in results), default=10)
    for r in results:
        print(f"  {r.status:4s}  {r.name:{width}s}  {r.detail}")

    passed = sum(1 for r in results if r.status == "PASS")
    failed = [r for r in results if r.status == "FAIL"]
    skipped = [r for r in results if r.status == "SKIP"]
    print()
    print(f"### {base}")
    print(
        f"### PASS {passed} | FAIL {len(failed)} | SKIP {len(skipped)} | всего {len(results)}"
    )
    if skipped:
        print("### SKIP означает ограничение окружения, а не пройденную проверку.")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "base_url": base,
                    "results": [
                        {
                            "name": r.name,
                            "status": r.status,
                            "detail": r.detail,
                            **r.extra,
                        }
                        for r in results
                    ],
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
        print(f"### JSON -> {args.json_out}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
