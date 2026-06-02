# TECH DEBT — общий ledger технического долга

> **Append-only** ledger техдолга, видимый обоим агентам (Claude Code + Kimi Code).
> Заполняется постепенно по мере обнаружения проблем. **НЕ удалять** закрытые записи
> в течение 30 дней (для ретроспективы).

## Формат

```
## [YYYY-MM-DD HH:MM] <agent> — <slug>
**Status:** open | accepted | rejected | superseded | closed
**Severity:** low | medium | high | critical
**Location:** <file:line или модуль>
**Description:** <короткое описание проблемы>
**Impact:** <что ломается / замедляется / падает>
**Workaround:** <как обходить если есть>
**Plan:** <как планируется починить>
**Owner:** <когда будет чиниться>
**Related:** <ссылки на ADR / issues / commits>
```

## Open

<!-- append below -->

## Closed (за последние 30 дней)

<!-- append below -->
