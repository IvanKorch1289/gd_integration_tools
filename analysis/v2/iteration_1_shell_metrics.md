# V2 Итерация 1: Shell-метрики (факт)

## Layer violations (grep imports)
| Направление | Количество | Примеры |
|-------------|-----------|---------|
| core → infrastructure | 72 | `get_logger` из `infrastructure.logging.factory` (svcs_registry.py, task_watchdog.py, rpa_policy.py, retry_budget.py, degradation.py...) |
| services → infrastructure | 171 | logging.factory, database, cache, clients |
| entrypoints → infrastructure | 82 | cache.metrics, audit.event_log, workflow.factory |
| extensions → infrastructure | 16 | database.models, session_manager, repositories.base |
| extensions → services | 20 | core.base, integrations.skb, auth.ad_directory_client |
| **ИТОГО** | **361** | Больше чем 316 в V1 |

## Размер слоёв
| Слой | Файлы | LOC |
|------|-------|-----|
| core | 311 | 45,769 |
| dsl | 329 | 67,398 |
| infrastructure | 364 | 53,878 |
| services | 291 | 43,175 |
| entrypoints | 184 | 27,062 |
| schemas | 20 | 1,185 |
| extensions | 74 | ~? |
| tests | 1,303 | ~? |

## TODO / Scaffold / NotImplemented
- TODO/FIXME: 216
- `pass #` (scaffold): 5
- NotImplementedError: 111
- Примеры: `TODO(B1-phase-2)`, `TODO(S40-W6)`, `TODO S20`

## Самые большие файлы
| Файл | LOC |
|------|-----|
| plugins/composition/lifecycle.py | 1,142 |
| dsl/builders/transport.py | 990 |
| entrypoints/api/generator/actions.py | 986 |
| dsl/engine/processors/ai_banking.py | 828 |
| dsl/engine/processors/rpa.py | 823 |
| dsl/builders/agent_dsl.py | 771 |
| dsl/commands/setup.py | 756 |
| dsl/engine/processors/format_convert.py | 744 |
| dsl/engine/processors/streaming.py | 737 |
| core/config/validator.py | 729 |

## Ruff (baseline-aware)
- F401/F811/F841: 0 (всё в baseline или ignore)
- Import дубли: 0
