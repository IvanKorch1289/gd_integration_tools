# ADR-0063 — Presidio + ru NER как обязательный AI Safety layer (PII)

* Статус: **Accepted** (2026-05-22, после S24 W1 closure — landed коммитами `33e1f280` / `4d9621b3` / `8070067d` / `f274ae71`).
* Связано с: GAP-2026-05-22 P0-1 (`gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md` Зона 7), PLAN.md V22.3 §S24 (AI Safety Hardening), ADR-NEW-16.
* Память: [[feedback_gap_analysis_ai_2026_05_22]], [[feedback_wave_k1_security]], [[feedback_wave_s1_security]].

## Контекст

Действующий PII-стек банка ограничен:

1. `src/backend/core/security/pii_masker` — 8 regex-паттернов (CC, SSN, email, phone, IP, passport, IBAN, SNILS).
2. `src/backend/services/ai/ai_agent.py:47` — `AIDataSanitizer` маскирует input LLM по regex.
3. `src/backend/services/ai/pii/retrieval_masker.py` — RAG retrieval masking (feature-flag `rag_pii_retrieval_mask`, **default-OFF**).
4. `presidio-analyzer` подключён в extra `[security]`, но `AnalyzerEngine` не инстанцируется в default-config.

**Не покрыто**: русские ФИО, адреса, организации, номера договоров, ИНН, СНИЛС в нестандартных форматах, номер кредитного дела. NER-движок отсутствует.

**Compliance-риск (H)**: банковский домен, утечка PII русскоязычных клиентов = нарушение 152-ФЗ.

## Решение (Draft)

**Включить Microsoft Presidio как обязательный AI Safety layer для production-config**:

1. **`presidio-analyzer` + `presidio-anonymizer`** — multi-language engine (`en` + `ru`).
2. **spaCy `ru_core_news_lg`** — Russian NER модель для PERSON / ORG / LOC.
3. **Custom recognizers** (под доменные сущности банка):
   - INN (ИНН): 10/12 цифр с checksum-валидацией.
   - СНИЛС: 11 цифр с control-digit алгоритмом.
   - Паспорт РФ: серия+номер форматов.
   - Номер кредитного дела / договора: банковский regex+context.
   - ФИО кириллица (через NER + custom).
4. **Применение pipeline**:
   - Input LLM (`AIDataSanitizer` → Presidio).
   - Output LLM (новый `LLMOutputSanitizer`).
   - RAG retrieval (`retrieval_masker` default-ON).
   - Langfuse traces (callback) — см. ADR-NEW для P1-5.
   - DLQ payload (audit-safe).
5. **GLiNER (opt-in)** — transformers-based NER для специфичных entity (feature-flag `pii_gliner_enabled` default-OFF).
6. **CI-gate `make pii-audit`** — gold-suite 1000 ru-документов, precision/recall ≥ 0.9.

## Альтернативы (отвергнуто на этом этапе)

* **Чисто regex-расширение** — не масштабируется на NER-задачи (ФИО, организации).
* **Standalone GLiNER без Presidio** — нет фреймворка для anonymize / customize, нет community recognizers.
* **Внешний SaaS PII (AWS Macie / Azure Purview)** — narnia compliance + WAF egress + cost.

## Открытые вопросы (решаются в wave S24 W1)

* **Latency overhead Presidio** — bench на p95 input/output (target ≤ 20ms p95 на 4kb текста).
* **Multi-language switching** — определять язык документа auto (langdetect) или per-tenant config?
* **Custom recognizer priority order** — Presidio ScorerEngine: какие entity-типы блокируют LLM-вызов (block) vs anonymize (replace token)?
* **GLiNER как primary vs opt-in** — стоимость inference на CPU vs Presidio.
* **Compliance audit trail** — каждое маскирование в audit-log (Postgres + immutable) с tenant_id + entity_type + redacted_hash.

## Зависимости

* `presidio-analyzer>=2.2`, `presidio-anonymizer>=2.2`, `spacy>=3.7` + `ru_core_news_lg` weights (1.5GB).
* Опционально: `gliner>=0.2.x`, `transformers` (уже в стеке).
* Capability: `pii.read.<tenant>`, `pii.audit.<tenant>` (расширение plugin.toml).

## DoD-критерии (статус 2026-05-22 после S24 W1 closure)

* [x] **Engine реализован** — `PresidioSanitizerAdapter` с lazy-init + ru NER (`ru_core_news_lg`) + en NER + 4 custom recognizers (`grep -rn "AnalyzerEngine\(\)" src/backend/services/ai/pii/` ≥ 1 ✅).
* [x] **`make pii-audit-{smoke,full}` CI-gate** реализован в `tools/checks/pii_audit.py` (hybrid gold-set: ~30 banking templates + faker[ru_RU] augmentation × 33 + 8 hand-curated edge cases ≈ 1000 docs). Threshold 0.85 (smoke) / 0.9 (full DoD-2).
* [x] **Capability `pii.{read,write,audit}` зарегистрированы** в `core/security/capabilities/vocabulary.py` (commit `33e1f280` backbone).
* [x] **Feature-flag `PRESIDIO_PII_ENABLED` (default-OFF)** + DI-провайдер switch `core/di/providers.py::get_ai_sanitizer_provider()` (commit `f274ae71`).
* [x] **Audit-event emission** `pii.{detected,anonymized,blocked}` через structured log (Langfuse callback) — immutable Postgres audit-sink в S24 closure-carryover.
* [x] **Tests** 19/19 unit + integration passing (+1 skipped: `test_pii_recognizers.py` через `pytest.importorskip` до установки extra `[ai-safety]`).
* [x] **AsyncPIISanitizerProtocol** добавлен в `core/interfaces/ai_clients.py` без breaking sync callers (Q4 решение пользователя).
* [ ] **PoC precision/recall ≥ 0.9 empirical** — требует `make pii-bootstrap` (загрузка `ru_core_news_lg` ~1.5GB) + установка `[ai-safety]` extra. **Carryover S24 nightly CI.**
* [ ] **Latency bench p95 ≤ 20ms на 4kb текста** — требует presidio-installed environment. **Carryover S24 perf wave.**
* [ ] **Default-ON в production-config + `rag_pii_retrieval_mask=true`** — после P/R verify. **Carryover S24 closure flip.**
* [ ] **Sphinx page** `docs/source/ai/pii_layer.md` — **carryover S24 W3 closure (docs batch).**

## Связи с другими ADR

* ADR-0050 (WAF strict single-entry) — PII layer работает после WAF.
* ADR-NEW-17 (NeMo + Llama Guard 3) — defense-in-depth, PII последний этап.
* ADR-NEW-S22-followup (Langfuse PII callback) — observability compliance.
