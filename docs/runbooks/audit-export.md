# Runbook — Audit Export

Экспорт audit-логов в архив.

## Symptom
- Юр.запрос на выгрузку логов.
- Compliance-аудит (SOX, PCI и т.д.).
- Регулярная архивация раз в квартал.

## Cause
Внешний запрос или регулярный план.

## Resolution
1. Определить интервал: `from_ts`, `to_ts` (UTC).
2. Запросить через action:
   ```bash
   curl 'https://api/api/v1/search/logs?from=2026-01-01&to=2026-03-31&limit=200'
   ```
3. Для больших объёмов — JSONL-экспорт:
   `tools/audit_export.py --from 2026-01-01 --to 2026-03-31 --out s3://bucket/`.
4. Передать ссылку запросившему через secure channel (Vault / encrypted email).

## Verification
- Размер файла > 0, gzip-валидный.
- `zcat ... | wc -l` ≥ ожидаемого числа событий.
- SHA256 совпадает с записью в `vault/audit-export-YYYY-MM-DD.md`.

## Rollback
Экспорт read-only — rollback не нужен. Если случайно расшарили —
rotate доступы и сделать notice в `#ops`.
