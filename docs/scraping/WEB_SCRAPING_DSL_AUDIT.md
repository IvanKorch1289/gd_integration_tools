# Web-Scraping + Tavily + Perplexity DSL Audit (S171 M19)

## Существующий функционал

| Компонент | Файл | Status |
|-----------|------|--------|
| **TavilyProvider** | `core/integrations/web_search.py` | ✅ (через facade) |
| **PerplexityProvider** | `core/integrations/web_search.py` | ✅ (через facade) |
| **SearXNGProvider** | `core/integrations/web_search.py` | ✅ (через facade) |
| **WebSearchService** | `core/integrations/web_search.py` | ✅ (capability-checked) |
| **WebSearchProcessor (DSL)** | `dsl/engine/processors/web_search.py` | ✅ generic web search |
| **BrowserLaunchProcessor** | `dsl/engine/processors/rpa_browser.py` | ✅ Playwright launch |
| **NavigateProcessor** | `dsl/engine/processors/rpa_browser.py` | ✅ page navigation |
| **ClickProcessor** | `dsl/engine/processors/rpa_browser.py` | ✅ element click |
| **FillProcessor** | `dsl/engine/processors/rpa_browser.py` | ✅ form input |
| **ExtractProcessor** | `dsl/engine/processors/rpa_browser.py` | ✅ text/attribute |
| **WaitForProcessor** | `dsl/engine/processors/rpa_browser.py` | ✅ explicit wait |
| **ScreenshotProcessor** | `dsl/engine/processors/rpa_browser.py` | ✅ page screenshot |
| **CitrixSessionProcessor** | `dsl/engine/processors/rpa_banking.py` | ✅ terminal emulation |
| **PlaywrightBrowserPool** | `services/rpa/browser_pool.py` | ✅ pool с lazy init |

## GAPS (per user directive)

| Gap | Описание | Priority |
|-----|----------|----------|
| **Tavily DSL processor** | Отдельный processor для Tavily API (search_depth, include_answer, max_results) | P1 |
| **Perplexity DSL processor** | С явной моделью (sonar, sonar-pro) | P1 |
| **Table extraction** | `extract_table()` — структурированное извлечение HTML table → JSON | P2 |
| **Structured selector** | `find_by(role/aria-label/test-id)` — accessibility-first | P2 |
| **XPath support** | Уже есть через selector (xpath=...), но нет first()/all() helpers | P3 |
| **Pagination walker** | `next_page()` + click next button + extract (per user) | P1 |
| **Search result parser** | Tavily → structured (answer, results, follow_up_questions) | P2 |

## DSL usage examples

```yaml
# Generic web search
- web_search:
    query: "новости Python 2026"
    provider: tavily
    max_results: 10
    to: body.search_results

# Tavily specific (P1 GAP)
- tavily_search:
    query: "{{ body.query }}"
    search_depth: advanced
    include_answer: true
    max_results: 5
    to: body.answer

# Perplexity specific (P1 GAP)
- perplexity_search:
    query: "{{ body.question }}"
    model: sonar-pro
    max_tokens: 1000
    to: body.answer

# Browser scraping
- browser_launch: headless
- navigate: url="https://example.com"
- wait_for: selector="div.content"
- extract:
    selector: "h1"
    to: body.title
- extract:
    selector: "table#products"
    attribute: "outerHTML"
    to: body.table_html
- screenshot: path="/tmp/page.png"
- browser_close
```

## Audit verdict

M19 audit: web-scraping + Tavily/Perplexity infrastructure есть.
**GAPS**: 2 dedicated processors (Tavily/Perplexity DSL) + structured extraction.
Per user request "DSL удобство использования" — рекомендую добавить
Tavily + Perplexity dedicated processors в M20 (next sprint).

Refs:
- D249 (CDC polling pattern)
- D250 (Source pluggable architecture)
- User directive: 'web-scraping + Tavily + Perplexity'
