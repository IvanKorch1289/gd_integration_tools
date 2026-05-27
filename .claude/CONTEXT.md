# CONTEXT.md

## Текущее состояние (2026-05-27 16:58)

**HEAD**: `07aef42d` — [carryover] S31 w1 foundation
**Session summary**: `vault/session-2026-05-27-1658-summary.md` (S27 architecture migration)

---

### S27 Architecture Violations Migration ✅ DONE

| Что | Файлы | Результат |
|-----|-------|-----------|
| TYPE_CHECKING detection | `tools/check_layers.py` | ✅ DLQEnvelope violation fixed |
| Lazy-import detection (bridge pattern) | `tools/check_layers.py` | ✅ bypass runtime-only infra imports |
| CircuitBreakerMetricsRecorder protocol | `core/interfaces/observability.py` | ✅ +2 protocols added |
| CorrelationIdProvider protocol | `core/interfaces/observability.py` | ✅ +2 protocols added |
| Breaker bridge pattern | `core/resilience/breaker.py` | ✅ indirect infra import removed |
| OutboundHttp bridge pattern | `core/net/outbound_http.py` | ✅ indirect infra import removed |
| Email utils refactoring | `infrastructure/sources/email_utils.py` | **NEW** — parse_email extracted |
| Email source fix | `infrastructure/sources/email.py` | ✅ no more entrypoints import |

**Allowlist**: 3 entries eliminated, 21 stale pending cleanup (→ `--update-allowlist`)

### Code review (subagent a54558ac219924094)

✅ All S27 changes correctly implemented — no blocking issues
⚠️ Dead code: `_parse_email()` дублируется в `imap_monitor.py:333`
⚠️ `grpc_server.py → correlation` не вошло в S27 (separate tech-debt)
ℹ️ Рекомендация: unit-тесты для `check_layers.py` в `tests/unit/tools/`

---

### S31 w1 foundation (carryover from earlier session)

**Изменённые файлы (14):**
- `core/config/validator.py` — feature flag dependency rules
- `entrypoints/mcp/mcp_server.py` — ADR-0070 capability check per namespace
- `scheduler/cron_validator.py` — second_at_beginning для 6-полевых cron
- `sources/factory.py` — directory → path mapping
- `routes/manifest_v11.py` — SpecifierSet.contains() fix

---

### Следующий шаг

**Очистить allowlist** (ожидает подтверждения):
```bash
python tools/check_layers.py --update-allowlist  # удалит 21 стейл-запись
```

**S31 w2**: MetricsRegistry canonical labels verification (🟡 PLANNED)

---

### Открытые риски

| Риск | Уровень |
|------|---------|
| 21 стейл-запись в allowlist | HIGH → pending `--update-allowlist` |
| `imap_monitor.py` дублирует `_parse_email()` | LOW → мёртвый код |
| `grpc_server.py` → `infrastructure.observability.correlation` | MEDIUM → separate tech-debt |
| vault_rotator.py + test_manifest_v11.py не закоммичены | LOW |

---

## Проверки (S27 session)

```bash
python tools/check_layers.py  # 0 новых, 21 стейл
python -c "import ast; [ast.parse(open(f).read()) for f in [...]]"  # AST valid
```
