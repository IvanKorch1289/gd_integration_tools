# browser_results.md — BROWSER verification (Playwright)

**HEAD:** `3b509542e96d89d79df45200d31904cd4fa97947`
**Интерпретатор:** `/home/user/dev/gd_reaudit/.venv/bin/python` (Python 3.14.0)
**Дата замера:** 2026-10-01
**Итоговый статус:** `ENV_BLOCKED` — **не PASS**

---

## 1. Вердикт и почему он не PASS

Все browser-пункты DoD (Swagger UI, ReDoc, GraphQL UI, Streamlit portal,
login flow, route registry, workflow pages, RPA local test page) **не могли быть
выполнены**: Python-биндинги Playwright отсутствуют в каноническом venv.
По правилу аудита `ENV_BLOCKED ≠ PASS`; ни один из этих пунктов не заявляется
как выполненный.

### F-AP3 · HIGH · Отсутствует canonical browser runtime

| Поле | Значение |
|---|---|
| **Severity** | HIGH (блокирует целый раздел DoD) |
| **file:line** | `pyproject.toml` — extras `rpa`, `test-rpa` (playwright/patchright) |
| **Reproduction** | `python -c "import playwright"` → см. фактический вывод ниже |
| **Expected** | `playwright` импортируется в каноническом venv (Python 3.14) |
| **Actual** | `ModuleNotFoundError: No module named 'playwright'` |
| **Impact** | Browser-верификация невозможна; зелёный прогон RPA-тестов доказывает лишь «метод был вызван», но не поведение |
| **Fix** | `uv sync --extra rpa` в канонический venv + закрепление в CI bootstrap-шаге; либо перенос в core-зависимости, если RPA входит в релизный контур |
| **Regression test** | `import playwright` в CI bootstrap-шаге (дешёвый guard против повторного ENV_BLOCKED) |
| **Commit SHA** | не закоммичено (см. §5) |

**Команды и фактический вывод:**

```
$ .venv/bin/python -c "import playwright"
ModuleNotFoundError: No module named 'playwright'

$ .venv/bin/python -c "import patchright"
ModuleNotFoundError: No module named 'patchright'

$ .venv/bin/python -c "from importlib.metadata import version, PackageNotFoundError; ..."
  playwright         MISSING
  patchright         MISSING
  pytest-playwright  MISSING

$ ls ~/.cache/ms-playwright/
chromium-1243
ffmpeg-1011
```

**Важное уточнение:** бинарники Chromium **присутствуют** на диске, отсутствуют
именно Python-биндинги. Это не «браузера нет» — это несобранное окружение:
достаточно `uv sync --extra rpa`, чтобы браузер заработал без загрузки
бинарников. Ошибку легко принять за «окружение без браузера» и неверно
квалифицировать как `NOT_RUN`; корректная формулировка — `ENV_BLOCKED`.

---

## 2. Единственный реальный browser-тест неработоспособен по трём причинам

### F-AP8 · MEDIUM · Тест не является pytest-тестом и не может стать зелёным

| Поле | Значение |
|---|---|
| **Severity** | MEDIUM (ложное чувство покрытия browser-контура) |
| **file:line** | `tests/mcp/test_streamlit_via_playwright.py:1-14, 28, 45, 60, 84, 101` |
| **Reproduction** | `pytest tests/mcp/test_streamlit_via_playwright.py --collect-only -q` |
| **Expected** | тесты собираются и исполняются в стандартном прогоне |
| **Actual** | `no tests collected, 1 error` — `ModuleNotFoundError: No module named 'playwright'` |
| **Impact** | Browser-контур не имеет ни одного исполняемого теста; DoD-пункт BROWSER не может быть закрыт автоматически даже после установки playwright |
| **Fix** | переписать на pytest-форму с `assert`, `pytest.importorskip("playwright")`, локальным fixture-сервером Streamlit вместо внешнего `127.0.0.1:8501`, и снять `--ignore` |
| **Regression test** | один реальный Chromium-тест: открыть локальный fixture, проверить заголовок |
| **Commit SHA** | не закоммичено |

**Фактический вывод:**

```
$ .venv/bin/python -m pytest tests/mcp/test_streamlit_via_playwright.py --collect-only -q
ImportError while importing test module '.../tests/mcp/test_streamlit_via_playwright.py'.
E   ModuleNotFoundError: No module named 'playwright'
no tests collected, 1 error in 0.10s
```

**Три независимых дефекта самого теста** (даже после установки playwright он
останется некорректным):

1. **Не pytest-формы.** Все пять функций объявлены `-> bool` и возвращают
   значение вместо `assert`. Pytest не считает проваленным тест, вернувший
   `False`, — зелёный прогон не означает успеха.
   ```
   28:def test_streamlit_loads() -> bool:
   45:def test_navigation_renders() -> bool:
   60:def test_spa_no_404s() -> bool:
   84:def test_page_screenshot() -> bool:
   101:def test_rpa_admin_check_403() -> bool:
   ```
2. **Хардкод личного пути и запрещённого интерпретатора.** Docstring предписывает
   запуск через Python 3.12:
   ```
   PYTHONPATH=/home/user/.local/lib/python3.12/site-packages \
       /usr/bin/python3 tests/mcp/test_streamlit_via_playwright.py
   ```
   Это нарушает базовое правило проекта «только Python 3.14» и делает тест
   невоспроизводимым на любой другой машине.
3. **Внешняя зависимость без fixture.** Требует уже запущенный Streamlit на
   `http://127.0.0.1:8501`; в чистом CI прогоне падает по таймауту, а не по
   существу проверки.

### F-AP9 · LOW · RPA-тесты зелёные, но проверяют только вызовы

| Поле | Значение |
|---|---|
| **Severity** | LOW |
| **file:line** | `tests/unit/dsl/engine/processors/test_rpa_browser.py`, `tests/unit/services/rpa/test_init.py` |
| **Reproduction** | `pytest tests/unit/services/rpa/ tests/unit/dsl/engine/processors/test_rpa_browser.py -q` |
| **Expected** | доказательство поведения браузера |
| **Actual** | `84 passed in 4.92s` при полностью замоканной странице; `startup`/`shutdown`/`acquire` пула не покрыты вовсе |
| **Impact** | `tests/unit/services/rpa/test_browser_pool.py` — 47 строк, 5 тестов, все — свойства конструктора (`init_explicit_params`, `size_property`, `is_started_false_initially`, `is_started_property_not_callable`, `size_with_chromium_default`); lifecycle пула не проверяется ни одним тестом |
| **Fix** | real-browser job с маркером `@pytest.mark.browser`, `--ignore` снять |
| **Regression test** | — |
| **Commit SHA** | не закоммичено |

---

## 3. Что подтверждено по HTTP вместо браузера (не замена browser PASS)

Пункты cURL-проверки, выполненные против живого uvicorn
(`artifacts/current_audit/curl_results.json`, 27 сценариев), покрывают
контрактную часть, но **не заменяют** browser-верификацию UI:

| Пункт | Статус | Чем подтверждён |
|---|---|---|
| OpenAPI 3.1.0, 414 paths / 142 schemas | PASS (HTTP) | живой сервер |
| `/docs`, `/redoc` отдают контракт | PASS (HTTP) | curl, не рендеринг |
| Security-заголовки присутствуют | PASS (HTTP) | `Referrer-Policy` отсутствует — F-AG |
| 403 `tenant_mismatch` на подмене tenant | PASS (HTTP) | живой стек из 37 middleware |
| Swagger UI / ReDoc **отрисовываются** | NOT_VERIFIED | требует браузера |
| Console errors / page errors | NOT_VERIFIED | требует браузера |
| `trace.zip`, screenshots | NOT_PRODUCED | требует браузера |
| Streamlit portal | NOT_VERIFIED | frontend не входит в изменённую волну |

---

## 4. Риск безопасности RPA, не закрытый из-за ENV_BLOCKED

Отсутствие браузера **не означает** отсутствие дыры. Агент RPA/Playwright
воспроизвёл SSRF на уровне процессора **без** браузера, подменив `page`:

- **F-AP1 · CRITICAL** — ни на одной из 11 точек `page.goto` нет валидации
  URL; 9/9 payload'ов (`169.254.169.254`, `127.0.0.1`, `10.0.0.5`, `192.168.1.1`,
  `[::1]`, `file:///etc/passwd`, `data:`, `chrome://`, `ftp://`) дошли до
  вызова браузера без ошибки; вектор достижим из тела запроса.
- **F-AP2 · HIGH** — `tools/check_waf_coverage.py` матчит только `httpx`,
  поэтому `page.goto` невидим для гейта: гейт отдаёт «0 violations» при
  реально открытом browser-egress. Это ложная assurance, и она не зависит от
  наличия браузера в venv.

Эти находки несут статус **подтверждено кодом и mock-прогоном**, а не
«проверено в браузере». Полное закрытие (real-Chromium проверка отсутствия
утечки в DOM/скриншотах) остаётся `NOT_VERIFIED` до установки playwright.

---

## 5. Статус артефактов браузерной верификации

| Артефакт | Статус | Причина |
|---|---|---|
| `trace.zip` | NOT_PRODUCED | playwright отсутствует |
| screenshots (`/docs`, `/redoc`, portal) | NOT_PRODUCED | playwright отсутствует |
| console errors log | NOT_PRODUCED | playwright отсутствует |
| page errors log | NOT_PRODUCED | playwright отсутствует |
| failed network requests log | NOT_PRODUCED | playwright отсутствует |

**Условие, при котором артефакты становятся производимыми:** одна команда в
каноническом venv — `uv sync --frozen --extra rpa` — плюс переписывание
`test_streamlit_via_playwright.py` в pytest-форму (F-AP8) и снятие `--ignore`.
После этого раздел BROWSER переводится из `ENV_BLOCKED` в исполняемый и
закрывается по DoD.

**Commit SHA:** не закоммичено. Все правки этой сессии — в worktree
`/home/user/dev/gd_reaudit`, HEAD `3b509542e` не изменён; коммит выполняется
только по явной команде владельца.
