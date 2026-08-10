# credit_pipeline

> **Статус**: implemented (Sprint 7 Team T2 → Team T3 done).
> **Версия плагина**: 0.1.0.
> **Cycle-20 (D-AUDIT-2001)**: README обновлён — все TODO T3 закрыты.

Кредитный pipeline плагин: scoring, document parsing, decision agents
(см. CLAUDE.md §V15-1, R-V15-16, PLAN.md Sprint 8+).

## Текущая структура

```
credit_pipeline/
├── plugin.toml          # ✓ capabilities + models_module + endpoints
├── plugin.py            # ✓ CreditPipelinePlugin (lifecycle hooks)
├── README.md            # ✓ этот файл
├── domain/
│   └── models.py        # ✓ CreditApplication / CreditReport / CreditDecision
├── services/
│   └── clients/
│       └── skb.py       # ✓ SKB-Техно клиент (httpx + per-service timeouts)
├── functions/
│   └── normalize.py     # ✓ call_function-helpers (apply_rules, normalize_response)
├── agents/              # ✓ scoring / parse / decide agent stubs
├── workflows/           # ✓ Temporal scaffolding
├── routes/              # ✓ lightweight routes placeholder
└── tests/
    ├── test_scaffold_load.py
    ├── test_actions_registration.py
    ├── test_credit_pipeline_v2_flag.py
    ├── test_skb_client_smoke.py
    ├── test_domain_models.py
    ├── test_normalize.py
    └── test_workflow_yaml.py
```

## Capabilities (plugin.toml)

| capability       | scope                  | назначение                                |
|------------------|------------------------|-------------------------------------------|
| `db.read`/`db.write` | `credit_applications` | таблица заявок                        |
| `db.read`/`db.write` | `credit_reports`     | таблица отчётов БКИ                    |
| `mq.publish`     | `credit.events.*`      | публикация событий конвейера              |

NB: оригинальные `net.outbound` для SKB/NBKI/CBR scopes удалены при
S180+ — реальные HTTP-вызовы идут через capability-gated
``OutboundHttpClient`` (WAF, R-V15-5), а не через per-domain
capability declarations. Это согласуется с S103 W1 split-brain.

## Provides

* **Actions**: `credit_pipeline.score`, `credit_pipeline.parse`,
  `credit_pipeline.decide`
* **Endpoints** (D-AUDIT-1506, cycle-15): REST/GraphQL/gRPC/MCP parity
  через ``tools/check_protocol_sync.py``.

## Тесты (S76+S168)

* `test_scaffold_load.py` — manifest + plugin class smoke
* `test_actions_registration.py` — actions registration
* `test_skb_client_smoke.py` — SKB HTTP client mock
* `test_domain_models.py` — Pydantic models
* `test_normalize.py` — function call helpers
* `test_workflow_yaml.py` — Temporal scaffolding YAML validation

См. также: `extensions/example_plugin/` (reference V11) и
`extensions/core_entities/{users,orders,orderkinds,files}/` (миграции CRUD).