# Capability runtime

ADR-044 — открытый registry capabilities. Плагины декларируют
`[[capabilities]]` в `plugin.toml`, runtime gate проверяет каждый
доступ к БД / Redis / HTTP / FS / MQ.

## Зачем

* **Sandbox-gate**: плагин получает только то, что задекларировал.
* **Audit trail**: все denied попытки уходят в `infrastructure/audit/event_log.py`.
* **Marketplace UX**: Streamlit page 71 рисует heatmap
  `plugin × capability` для admin.

## Архитектура

```
plugin.toml
  └── [[capabilities]]
        name = "mq.publish"
        scope = "credit.events.*"
              │
              ▼
     CapabilityVocabulary (ADR-044)
              │
              ▼
   CapabilityGate.check(name, scope)
              │
   ┌──────────┴──────────┐
   │                     │
   ▼                     ▼
 granted             denied
                      │
                      ▼
            emit_audit_event(
              event_type="capability_denied",
              ...
            )
```

## Связанные документы

* [ADR-042 plugin.toml schema](../../docs/adr/ADR-042-plugin-toml-schema.md)
* [ADR-044 capability vocabulary](../../docs/adr/ADR-044-capability-vocabulary.md)
* Streamlit page **71_Capabilities** — live heatmap.
