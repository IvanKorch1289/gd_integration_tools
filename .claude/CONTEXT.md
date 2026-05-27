# CONTEXT.md

## Текущее состояние (2026-05-27 18:30)

**HEAD**: `07aef42d` — [carryover] S31 w1 foundation
**Session summary**: `vault/session-2026-05-27-1830-summary.md`

---

### Carryover session 2026-05-27 — исполнено

| Что | Коммит | Статус |
|-----|--------|--------|
| asyncio.create_task → TaskRegistry (file_watcher.py:91) | `b9f130ad` | ✅ DONE |
| S31 w1 foundation (14 файлов, 259+) | `07aef42d` | ✅ DONE |

### S31 w1 foundation — carryover детали

**Изменённые файлы (14):**
- `core/config/validator.py` — feature flag dependency rules (WARNING + CRITICAL pairs)
- `entrypoints/mcp/mcp_server.py` — ADR-0070 capability check per namespace
- `scheduler/cron_validator.py` — second_at_beginning для 6-полевых cron
- `sources/factory.py` — directory → path mapping
- `routes/manifest_v11.py` — SpecifierSet.contains() fix
- `PLAN.md` — S31 w5 TaskRegistry CI-gate → ✅ DONE

### Аудит запрещённых паттернов (финальный)

```
✅ asyncio.create_task (orphan): 0
✅ threading.RLock: 0
✅ ssl.CERT_NONE: 0
✅ except Exception: pass: 0
✅ yaml.load unsafe: 0
```

---

## Следующий шаг

**S31 w2**: MetricsRegistry canonical labels verification (🟡 PLANNED)
- 44 метрики из S17 K2 W1 проверить на canonical labels `{tenant_id, route_id, component, env}`
- Idempotent registration gate

**Pending carryover:**
- `vault_rotator.py` — docstring improvement + first-init callback (modified, not committed)
- `test_manifest_v11.py` — related to manifest fix (modified, not committed)

---

## Открытые риски

| Риск | Уровень |
|------|---------|
| vault_rotator.py + test_manifest_v11.py не закоммичены | LOW |
| S31 w2 MetricsRegistry: ещё не начат | INFO |
| tools/checks/check_task_registry.py существует, интеграция в make ci pending | INFO |

---

## Проверки (из сессии 2026-05-27)

```bash
# Forbidden patterns audit
grep -rn "asyncio\.create_task" src/backend/ --include="*.py" | grep -v task_registry  # 0 writes
grep -rn "threading\.RLock" src/backend/ --include="*.py"  # 0
grep -rn "ssl\.CERT_NONE\|check_hostname=False" src/backend/ --include="*.py"  # 0
grep -rn "except Exception:\s*pass" src/backend/ --include="*.py"  # 0

# Import check (watchfiles missing — dev env only)
python -c "from src.backend.infrastructure.sources.file_watcher import FileWatcherSource"

# TaskRegistry pattern verification
python -c "
import pathlib, re
for f in ['src/backend/infrastructure/sources/file_watcher.py',
          'src/backend/infrastructure/secrets/vault_rotator.py']:
    p = pathlib.Path(f)
    c = p.read_text()
    has_raw = bool(re.search(r'asyncio\.create_task\s*\(', c))
    has_tr = 'get_task_registry()' in c
    print(f'{f}: raw_create_task={has_raw}, uses_TaskRegistry={has_tr}')
"
# → оба файла: raw_create_task=False, uses_TaskRegistry=True ✅
```
