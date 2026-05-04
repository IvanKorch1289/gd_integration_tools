# Tutorial — RPA Script

Цель: автоматизировать UI-действие через Playwright-скрипт.

## Что вы узнаете
- Как описать RPA-script в формате проекта.
- Как зарегистрировать его как action.
- Как запустить из DSL/REST.

## Шаги

1. Установите extra:
   ```bash
   uv sync --extra rpa
   ```
2. Создайте `src/services/rpa/scripts/login_flow.py`:
   ```python
   from playwright.async_api import async_playwright

   async def run(payload: dict) -> dict:
       """Логинится в UI и возвращает session-cookie."""
       async with async_playwright() as p:
           browser = await p.chromium.launch()
           page = await browser.new_page()
           await page.goto(payload["url"])
           await page.fill("#login", payload["user"])
           await page.fill("#pwd", payload["pwd"])
           await page.click("button[type=submit]")
           cookies = await page.context.cookies()
           await browser.close()
           return {"cookies": cookies}
   ```
3. Зарегистрируйте action `rpa.login_flow`.
4. Вызов: `curl -X POST /api/v1/invocations/invoke -d '{"action":"rpa.login_flow", ...}'`.

## Проверка
- В headless логе видно успешный flow.
- Возвращённые cookies валидны.

## Next steps
- [DSL route с RPA](write-dsl-route.md)
- [RPA guide](../RPA_GUIDE.md)
