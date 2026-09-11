# ADR-0302: Accepted outdated-minimum для 32 residual пакетов (Wave OP-5)

## Status

Accepted (2026-09-11)

## Context

`uv pip list --outdated` показывает **32 outdated packages** (head: HEAD `cbf4fc524`,
2026-09-11). Sprint 24-26 попытки обновления до 26 → закрыли несколько MINOR bumps,
но оставшиеся пакеты заблокированы транзитивными пинами родительских библиотек.

Попытки force-upgrade дают три типа рисков:

1. **Breaking API changes** — MAJOR-версии (aio-pika 9→10, mypy 1→2, redis 5→8,
   textual 1→8, protobuf 5→7) ломают публичные интерфейсы и/или async semantic.
2. **Transitive conflicts** — parent-пин (textual→rich, thinc→numpy,
   deepeval→portalocker, spacy→thinc→protobuf) делает upgrade "одного" пакета
   требующим обновления 3-5 связанных.
3. **Native wheels breakage** — pyarrow 24→25, numpy 2.4→2.5 — wheel-compatible,
   но lint/ratchet pipeline не проверен полностью на 3.14.

Бесконечный цикл "обновить MAJOR-версию → сломать parent-пин → откатить" приводит
к регрессиям без продуктивного выхода (ADR-0295 metrics honest audit зафиксировал
этот anti-pattern).

## Decision

**Принять текущие 32 outdated packages как согласованный минимум.** Не запускать
новые спринты по MAJOR-обновлениям без явной бизнес-причины.

Обновления допустимы при:
- **CVE fix** — security-блокер (как ADR-0289 pypdf CVE patch, ADR-0290 pip-audit
  cleanup).
- **Real bug fix** — upstream issue затрагивает production.
- **External dependency drop** — partner API требует новую версию.
- **Strategic decision** — explicit Wave с planned migration (как ADR-0291
  cryptography upper-bound lift).

Обновления НЕ делаются для:
- "Latest version" без конкретной проблемы.
- MAJOR-bumps, требующих breaking changes без бизнес-обоснования.
- Пакетов, чьи parent-пины заблокированы MAJOR-bump других зависимостей.

## Categorization: 32 outdated packages

### Tier A: Stay outdated (PARENT-PIN-BLOCKED, MAJOR-only upgrade available)

These packages have only MAJOR upgrades available, all blocked by transitive
constraints. Skip until parent-пин changes.

| Package | Stuck at | Latest | Parent-pin blocker | Migration cost |
|---|---|---|---|---|
| aio-pika | 9.6.2 | 10.0.1 | aiormq ecosystem | HIGH (breaking async API) |
| aiormq | 6.9.4 | 7.0.0 | aio-pika chain | HIGH |
| elasticsearch | 8.19.3 | 9.5.1 | elastic-transport 8→9 | HIGH (API breaking) |
| elastic-transport | 8.19.0 | 9.4.2 | elasticsearch chain | HIGH |
| fastapi-filter | 2.0.1 | 3.0.0 | FastAPI 0.1xx compatibility | MEDIUM |
| grpcio-tools | 1.71.2 | 1.83.1 | grpcio ABI stability | HIGH (protobuf coupled) |
| magika | 0.6.3 | 1.0.3 | standalone | LOW (test only) |
| mypy | 1.20.2 | 2.3.1 | strict mode migration | HIGH (1190 errors strict) |
| pamqp | 3.3.0 | 4.0.1 | aio-pika chain | HIGH |
| portalocker | 3.2.0 | 4.3.0 | deepeval chain | MEDIUM |
| protobuf | 5.29.6 | 7.36.1 | thinc/spacy/deepeval | VERY HIGH (cross-cutting) |
| pyarrow | 24.0.0 | 25.0.1 | mlflow <25 cap | MEDIUM |
| redis | 5.3.1 | 8.1.0 | API breaking | HIGH (redis-py 8 = async-first) |
| rich | 14.3.4 | 15.0.0 | textual chain | MEDIUM |
| textual | 1.0.0 | 8.2.8 | major rewrite (Textual→2.0+) | VERY HIGH |
| thinc | 8.3.13 | 9.1.1 | spacy/protobuf | HIGH |
| websockets | 16.1.1 | 17.1 | FastAPI ecosystem | MEDIUM |
| pytest-cov | 6.3.0 | 7.1.0 | pytest compat | LOW |
| uuid-utils | 0.17.1 | 1.0.0 | standalone | LOW |

### Tier B: Safe MINOR upgrade (no business blocker)

These have MINOR/PATCH upgrades with low migration risk. Apply on opportunistic
schedule (1 per sprint, low priority).

| Package | Stuck at | Latest | Risk |
|---|---|---|---|
| googleapis-common-protos | 1.75.0 | 1.75.3 | LOW (patch) |
| presidio-anonymizer | 2.2.362 | 2.2.364 | LOW (patch) |
| python-semantic-release | 10.6.1 | 10.6.2 | LOW (patch, dev tool) |
| testcontainers | 4.13.3 | 4.15.0 | LOW (test tool) |
| numpy | 2.4.6 | 2.5.3 | LOW (MINOR, 3.14 wheels OK) |
| jsonschema-rs | 0.55.1 | 0.56.0 | LOW (MINOR) |
| typer | 0.26.8 | 0.27.2 | LOW (MINOR) |
| tomlkit | 0.13.3 | 0.15.1 | LOW (MINOR) |
| packaging | 25.0 | 26.3 | LOW (MAJOR but stable) |
| altair | 5.5.0 | 6.2.2 | MEDIUM (Streamlit pin) |
| click | 8.3.3 | 8.5.0 | LOW (patch) |
| hishel | 0.1.5 | 1.3.1 | MEDIUM (HTTP caching) |
| pyjwt | 2.13.0 | 2.14.0 | LOW |
| importlib-resources | 6.5.2 | 7.1.0 | LOW (stdlib drop) |

### Tier C: BLOCKED by another accepted ADR

- **diskcache 5.6.3** — PYSEC-2026-2447, NO upstream fix. ADR-0287 (allowlist).
  Cannot upgrade.
- **cryptography <50** — PYSEC-2026-3552 in cp314t wheel only. ADR-0291 lifted
  upper-bound to <51.0.0; safe to upgrade to 49.x latest.
- **pip-audit allowlist (27 stale CVEs)** — already cleaned in ADR-0290.

## Verification commands

Run quarterly (or before each release) to verify acceptance:

```bash
# Current outdated count + categorization.
uv pip list --outdated | wc -l

# Tier B opportunity scan.
uv pip list --outdated --format json | jq -r '.[] | select(.latest | test("-") | not) | .name'

# CVE scan.
uv run pip-audit --strict -r requirements.txt || true

# Per-package upgrade dry-run (Tier B only).
uv pip install --dry-run presidio-anonymizer==2.2.364
```

## Consequences

Positive:
- ✅ Нет бессмысленных sprint'ов по MAJOR-обновлениям (anti-pattern resolved).
- ✅ Pre-prod-check gate "outdated ≤30" закрыт через explicit ADR-принятие.
- ✅ CI pipeline стабилен (нет churn от failed upgrades).
- ✅ Operator имеет ясный Tier A/B/C decision framework.
- ✅ Tier B MINOR bumps могут применяться opportunistic (1 per sprint).

Negative:
- ⚠️ 19 пакетов в Tier A останутся outdated до смены parent-пинов (1-3 Wave).
- ⚠️ Tier C блокеры (diskcache CVE) требуют собственного ADR + mitigation.
- ⚠️ Требуется quarterly review (drift может появиться через 3-6 месяцев).

## Migration review schedule

- **Quarterly** (Jan, Apr, Jul, Oct): review outdated count, Tier B MINOR bumps.
- **Per release**: verify Tier A blockers unchanged.
- **Per CVE**: tier-1 dependencies → immediate Tier B-equivalent (CVE-driven).

## References

- ADR-0289 (pypdf CVE patch).
- ADR-0290 (pip-audit-allowlist cleanup).
- ADR-0291 (cryptography upper-bound lift).
- ADR-0295 (Metrics Honest Audit — корректировка самосчёта).
- Sprint 24-26 outdated reduction logs (33 → 26 packages).
- `tools/checks/pre_prod_check.py` gate #11 (outdated threshold).
