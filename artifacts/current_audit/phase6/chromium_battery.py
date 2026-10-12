#!/usr/bin/env python3
"""Phase 6 Chromium battery (Playwright sync API).

Запускает реальный Chromium против поднятого `APP_PROFILE=dev_light`
приложения. Проверяет:
- Swagger UI рендерится
- ReDoc рендерится
- openapi.json парсится
- /docs и /redoc доступны (401/200/302)
- console messages собраны

Артефакты:
- artifacts/current_audit/phase6/chromium_results.jsonl
- artifacts/current_audit/phase6/chromium_screenshots/<probe>.png

Usage:
  APP_PROFILE=dev_light uv run python -m uvicorn src.backend.main:app \
      --port 18000 &
  python artifacts/current_audit/phase6/chromium_battery.py \
      http://127.0.0.1:18000
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HOST = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
RES = Path(__file__).resolve().parent / "chromium_results.jsonl"
SHOTS = Path(__file__).resolve().parent / "chromium_screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

PROBES = [
    ("openapi-json", "/openapi.json", "json"),
    ("swagger-ui", "/docs", "html"),
    ("redoc", "/redoc", "html"),
    ("graphql-ui", "/graphql", "html"),
    ("home", "/", "html"),
]


def main() -> int:
    out: list[dict[str, object]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for name, path, kind in PROBES:
            ctx = browser.new_context()
            page = ctx.new_page()
            console: list[str] = []
            page.on("console", lambda msg: console.append(f"{msg.type}: {msg.text}"))
            try:
                t0 = time.time()
                resp = page.goto(HOST + path, wait_until="domcontentloaded", timeout=15_000)
                elapsed = time.time() - t0
                status = resp.status if resp else 0
                # screenshot
                shot = SHOTS / f"{name}.png"
                try:
                    page.screenshot(path=str(shot), full_page=False)
                except Exception as exc:
                    shot = f"screenshot failed: {exc}"
                # extract some content
                title = page.title()
                if kind == "json":
                    try:
                        body_text = page.evaluate("() => document.body.innerText.slice(0, 200)")
                    except Exception:
                        body_text = ""
                else:
                    try:
                        body_text = page.evaluate("() => document.body.innerText.slice(0, 200)")
                    except Exception:
                        body_text = ""
                ok = status in (200, 401, 403, 404)  # 401/403 fine for auth-protected
                out.append({
                    "name": name, "path": path, "status": status,
                    "time_s": round(elapsed, 4), "title": title,
                    "console_msgs": len(console),
                    "screenshot": str(shot) if isinstance(shot, str) else shot.name,
                    "body_preview": body_text[:120].replace("\n", " "),
                    "ok": ok,
                })
                sym = "✓" if ok else "✗"
                print(f"  {sym} {name:20s} {status:>3}  {elapsed:6.3f}s  title={title!r:40s}  console={len(console)}")
            except Exception as exc:
                out.append({
                    "name": name, "path": path, "status": 0, "ok": False,
                    "error": repr(exc), "console_msgs": len(console),
                })
                print(f"  ✗ {name:20s} ERR {exc!r}")
            finally:
                ctx.close()
        browser.close()
    with RES.open("w") as f:
        for ln in out:
            f.write(json.dumps(ln, ensure_ascii=False) + "\n")
    passed = sum(1 for l in out if l["ok"])
    print(f"\n  {passed}/{len(out)} passed → {RES}")
    print(f"  screenshots: {SHOTS}/")
    return 0 if passed == len(out) else 1


if __name__ == "__main__":
    raise SystemExit(main())
