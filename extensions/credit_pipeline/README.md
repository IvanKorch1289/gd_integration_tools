# credit_pipeline

> **Статус**: scaffold (Sprint 7 Team T2 → Team T3 owners).
> **Версия плагина**: 0.0.1 (пустой stub).

Этот плагин — место для первого реального бизнес-клиента (СКБ-Техно / НБКИ /
CBR / Spark) в новой архитектуре V11 (см. CLAUDE.md §V15-1, R-V15-16,
PLAN.md Sprint 8+).

## Цели плагина (Team T3)

* мигрировать существующую логику кредитного конвейера из `src/backend/services/integrations/`
  (SKB / Dadata / Spark / CBR) и `src/backend/workflows/` в плагин;
* собрать declarative-pipeline через DSL: `routes/<credit_*>/{route.toml,*.dsl.yaml}`
  + `workflows/credit_assessment.workflow.yaml`;
* подключить SCB-клиент через `services/clients/skb.py` с собственными
  per-service timeouts (R-V15-13) и через `OutboundHttpClient` (WAF, R-V15-5);
* зарегистрировать actions: `credit.application.create`, `credit.score.calculate`,
  `credit.report.fetch`, `credit.decision.publish`;
* подключить domain-модели `CreditApplication`, `BkiReport`, `CreditDecision`.

## Дорожная карта подкаталогов

```
credit_pipeline/
├── plugin.toml          # ✓ scaffold готов (capabilities декларированы)
├── plugin.py            # ✓ CreditPipelinePlugin stub
├── README.md            # ✓ этот файл
├── domain/
│   └── models.py        # TODO T3: Pydantic-модели CreditApplication, BkiReport, ...
├── services/
│   └── clients/
│       ├── skb.py       # TODO T3: SKB-Техно клиент (BaseExternalAPIClient + timeouts)
│       ├── nbki.py      # TODO T3: НБКИ клиент
│       └── cbr.py       # TODO T3: ЦБ-РФ клиент
├── functions/
│   └── normalize.py     # TODO T3: call_function-helpers (apply_rules, normalize_response)
├── routes/
│   └── <route_name>/    # TODO T3: route.toml + *.dsl.yaml
├── workflows/
│   └── credit_assessment.workflow.yaml  # TODO T3: Temporal-pipeline через Workflow DSL
└── tests/
    └── test_scaffold_load.py  # ✓ scaffold smoke-test
```

## Capabilities (plugin.toml)

| capability       | scope                  | назначение                                |
|------------------|------------------------|-------------------------------------------|
| `net.outbound`   | `*.skb-techno.ru`      | внешний API СКБ-Техно (через WAF)         |
| `net.outbound`   | `*.nbki.ru`            | внешний API НБКИ (через WAF)              |
| `db.read`/`db.write` | `credit_applications` | таблица заявок                        |
| `db.read`/`db.write` | `credit_reports`     | таблица отчётов БКИ                    |
| `mq.publish`     | `credit.events.*`      | публикация событий конвейера              |

## Следующие шаги для Team T3

1. Перенос SKB-клиента: `src/backend/services/integrations/skb.py` →
   `extensions/credit_pipeline/services/clients/skb.py` (с `BaseExternalAPIClient` +
   per-service timeouts).
2. Перенос workflows из `src/backend/workflows/` в `workflows/*.workflow.yaml`.
3. Создание `routes/credit_check_v2/route.toml` + `pipeline.dsl.yaml`.
4. Domain-модели в `domain/models.py` (Pydantic + validation).
5. Backward-compat shims для legacy-импортёров (по образцу users/orders/orderkinds/files).
6. Unit-тесты CRUD + smoke-pipeline.
7. Обновить `plugin.toml::provides` после реализации actions/repos.

См. также: `extensions/example_plugin/` (reference V11) и
`extensions/core_entities/{users,orders,orderkinds,files}/` (миграции CRUD).
