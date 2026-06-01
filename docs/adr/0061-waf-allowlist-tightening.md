# ADR-0061 — WAF allowlist tightening для Sprint 9

* Статус: Accepted (Wave [s9/k1-w3-waf-allowlist-tightening], 2026-05-18)
* Связано с: ADR-0050 (WAF strict single entry), ADR-0053 (Phase-2 default-ON),
  V15 R-V15-5, A-2 техдолг (PLAN.md V19.1 §1.2).

## Контекст

После Sprint 8 closure (Phase-2 BLOCKER #3 закрыт — 0 violations) WAF
allowlist содержал 21 baseline callsite. Эти исключения легитимны
(:internal или legacy-libraries), но требуют формализации:

1. каждая запись помечается owner-командой (K1-K5);
2. каждая запись имеет target sprint для миграции на `OutboundHttpClient`;
3. CI gate `make check-waf-coverage-strict` игнорирует allowlist
   полностью — для финального BLUE-GREEN deploy.

## Решение

* `tools/check_waf_coverage_allowlist.txt` — формат расширен
  ``<file_path>  # owner=<team> | target=<sprint> | reason=<note>``.
* Файлы без явного owner отклоняются (ошибка валидации).
* `tools/check_waf_coverage.py --strict` для финального gate
  игнорирует allowlist полностью; baseline-mode используется только в
  daily CI.
* Sprint 10 migration targets:
  - K1: `webhook/handler.py`, `webhook/transformer.py`, `imports.py`
    (3 файла — все управляются ASGI middleware, миграция тривиальна).
  - K2: `infrastructure/sinks/{http,webhook}_sink.py` (2 файла — Sink
    base class рефакторится в S10).
  - K3: `dsl/engine/processors/{ml_inference,proxy/forward}.py` (2 файла).
  - K4: `services/ai/{ai_moderation,ai_providers}.py` (2 файла).
  - K5: `services/ops/notification_*.py` (3 файла — notification stack).

## Контроль

* `make check-waf-coverage` — daily mode (allowlist разрешён, baseline tracking).
* `make check-waf-coverage-strict` — gate для pre-prod-check (DoD-10),
  падает если хотя бы один файл вне allowlist использует прямой httpx.
* После каждой миграции в S10 строка удаляется из allowlist'а.

## Открытые вопросы

* `infrastructure/clients/storage/clickhouse.py` — ClickHouse использует
  собственный HTTP-pool через httpx; миграция требует расширения
  `OutboundHttpClient` для не-OAS клиентов (S11 R3).
* `core/security/vault_cipher.py` — внутренний HMAC-rotator через Vault;
  миграция требует Vault namespace в capability-policy (S11 R3).
