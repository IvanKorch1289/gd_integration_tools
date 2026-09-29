# 08 privacy-lifecycle: ENV-bound анализ (протокол: tool/env failure ≠ code failure)

- clean checkout без .env: exit 1, 5 backends UNVERIFIED (fail-closed по дизайну —
  модель-импорт требует ПОЛНЫЙ app settings, включая секреты внешних API:
  dadata api_key и др. из .env, который агенту читать ЗАПРЕЩЕНО).
- DB_TYPE=sqlite: ValidationError «SSL доступен только для PostgreSQL».
- Полный postgres-env (фиктивные креды): ValidationError DadataAPISettings
  (Field required api_key) — стена секретов.
- В основном worktree (с .env, непрочитанным агентом): exit 0, маркеры ✅ —
  тот же SHA 24693c41b.
- КОМПЕНСИРУЮЩАЯ code-level evidence: runtime privacy contract тесты
  tests/unit/core/privacy + tools-тесты гейта — 755 passed в кластере
  (см. runtime-фазу этого аудита).

ВЕРДИКТ: gate корректен (fail-closed), код privacy-адаптеров верифицирован
unit-контрактами; cross-backend runtime contract tests требуют живых
PG/Redis/S3/Qdrant (отдельная env-волна).
