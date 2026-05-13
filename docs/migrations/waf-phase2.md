# WAF Phase-2 Migration Guide

> Связано с: ADR-0050 (single-entry), ADR-0053 (Phase-2 default-on),
> V15 R-V15-5, V18.1 §S1/S3 (К1 stream).
> Аудитория: команды К2–К5, plugin authors, integration owners.

## Status

* **Phase-2 default-on**: `outbound_via_facade=True` стал значением по
  умолчанию в `core/config/waf.py` начиная с коммита
  `50fb226 [wave:s1/k1-waf-phase2]` (2026-05-12).
* **Phase-2 strict-mode**: `strict=False` остаётся по умолчанию.
  Flip `strict=True` запланирован на **К1 W3** после per-team review
  allow-list-а.
* **CI gate**: `make check-waf-coverage` (alias на
  `python tools/check_waf_coverage.py`) — non-strict;
  `python tools/check_waf_coverage.py --strict` — release-gate.

## Что изменилось

До Phase-2 (commit `50fb226`):

* `BaseExternalAPIClient` имел ветку `if waf_settings.outbound_via_facade`,
  но флаг был `False` — все business-clients (DadataClient, SkbClient, ...)
  использовали `httpx.AsyncClient` напрямую через legacy-конструктор.
* CI gate `make check-waf-coverage` пропускал любой allowlist-эталон.

После Phase-2:

* Все наследники `BaseExternalAPIClient` автоматически направляют
  запросы в `OutboundHttpClient` — WAF allow/deny-list применяется
  без правки вызывающего кода.
* CI gate отражает фактическое покрытие; миграционный долг
  (39 callsite-ов) явно зафиксирован в
  `tools/check_waf_coverage_allowlist.txt`.

## Migration Checklist для команд К2–К5

Каждый callsite из allowlist-а мигрирует одинаково:

1. **Прочитать** `tools/check_waf_coverage_allowlist.txt` —
   подтвердить, что файл относится к зоне вашей команды.
2. **Заменить** `httpx.AsyncClient(...)` на
   `OutboundHttpClient(policy=..., capability_check=..., plugin=...)`.
3. **Объявить capability** в `plugin.toml` (для extensions) либо
   передать `plugin="core"` (для core/infrastructure).
4. **Прогнать тесты**: `pytest tests/unit/<область>/`.
5. **Удалить запись** из allowlist-а в том же PR.
6. **Запустить** `python tools/check_waf_coverage.py --strict` —
   проверить, что `--strict` остаётся зелёным (после удаления
   соответствующего файла).

### Зоны ответственности по командам

| Команда | Файлы | ETA |
| --- | --- | --- |
| К2 (AI/observability) | `services/ai/ai_providers.py`, `services/ai/ai_moderation.py`, `dsl/engine/processors/ml_inference.py` | Sprint 3 W2 |
| К3 (DSL/Sinks) | `dsl/engine/processors/proxy/forward.py`, `infrastructure/sinks/http_sink.py`, `infrastructure/sinks/webhook_sink.py`, `infrastructure/sources/polling.py` | Sprint 3 W2 |
| К3 (entrypoints) | `entrypoints/api/v1/endpoints/imports.py`, `entrypoints/webhook/handler.py`, `entrypoints/webhook/transformer.py` | Sprint 3 W3 |
| К4 (clickhouse/policy) | `infrastructure/clients/storage/clickhouse.py`, `infrastructure/policy/opa.py` | Sprint 3 W3 |
| К5 (ops) | `services/ops/notification_adapters.py`, `services/ops/notification_hub.py`, `services/ops/webhook_scheduler.py`, `infrastructure/resilience/components/express_chain.py` | Sprint 3 W3 |
| К5 (external clients) | `infrastructure/clients/external/{express_bot,telegram_bot,search_providers}.py` | Sprint 4 (требует plugin.toml::capabilities) |
| К1 (security/secrets) | `core/security/vault_cipher.py` (hvac internals, не httpx — допустимо оставить в allowlist навсегда) | N/A |

## Strict-mode Follow-up Plan (К1 W3)

После полной миграции allowlist-а:

1. Удалить allowlist-файл (или оставить только глобально-exempt
   transport-core записи).
2. Установить `strict=True` в `core/config/waf.py`.
3. Добавить ADR-0054 «WAF strict deny-by-default».
4. Включить `python tools/check_waf_coverage.py --strict` в
   `make ci` композит (сейчас вызывается только через `make security`).
5. Обновить allowlist-документацию в `core/net/waf.py`.

## Rollback Guide

Если Phase-2 default-on вызывает регрессии в production:

### Опция 1 — env-override без рестарта

Установить переменную окружения и перезапустить процесс:

```bash
export OUTBOUND_VIA_FACADE=false
# или для systemd-сервиса:
# Environment="OUTBOUND_VIA_FACADE=false"
```

После рестарта `WafSettings().outbound_via_facade` будет `False`,
все клиенты вернутся к pre-Phase-2 поведению (прямой `httpx.AsyncClient`).

### Опция 2 — code-level revert

```python
# scratch / hot-fix only:
from src.backend.core.config.waf import waf_settings
waf_settings.outbound_via_facade = False  # noqa: SLF001 — emergency revert
```

Это shadow-override на уровне singleton-а; **не рекомендуется**
для production — используйте env-переменную.

### Опция 3 — git revert

```bash
git revert 50fb226  # commit Phase-2 default-on
```

Полный rollback на код Phase-1 (`outbound_via_facade=False`).

## Verification после миграции callsite-а

```bash
# 1. Юнит-тесты затронутого модуля
pytest tests/unit/<область>/ -x

# 2. WAF-coverage gate (без allowlist-а — release-уровень)
python tools/check_waf_coverage.py --strict

# 3. Интеграционные тесты WAF
pytest tests/integration/security/test_waf_facade_default_on.py -v

# 4. Композит CI (если в зоне)
make lint && make type-check
```

## Ссылки

* [ADR-0050 — net/waf strict + single entry](../adr/0050-net-waf-strict-single-entry.md)
* [ADR-0053 — WAF Phase-2 default-on](../adr/0053-waf-phase2-migration.md)
* `tools/check_waf_coverage.py` — gate-сканер
* `tools/check_waf_coverage_allowlist.txt` — known-debt список
* `src/backend/core/net/outbound_http.py` — `OutboundHttpClient`
* `src/backend/core/net/waf.py` — `WafPolicy` + `WafBypassError`
