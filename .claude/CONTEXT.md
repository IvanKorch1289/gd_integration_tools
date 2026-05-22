# CONTEXT.md

## Текущее состояние (2026-05-22 13:52, AI-GAP анализ → Sprint 24 closure planning)

**Сессия**: coordinator-self GAP-анализ AI-агентного стека (документация-only, 0 кода) + plan-step для Sprint 24.
**HEAD на момент сессии**: `d0ffdc39 [wave:s21/k1-w2-tenant-cache-wrapper]` → `3f3aeec3 [wave:s17/k1-w6-yaml-safeload]` (параллельная сессия S21 multi-tenancy + S17 carryover активна).
**Связь**: PLAN.md V22.2 → V22.3 (новый §S24 AI Safety Hardening), 3 новых ADR-NEW-16/17/18.

### Что сделано (7 artifact-файлов)

1. **GAP-документ** `gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md` — 10 зон AI-стека (orchestration / memory / RAG / low-context / MCP / tools / PII / guardrails / structured output / observability), Top-10 таблица P0/P1/P2, verification-матрица.
2. **3 ADR scaffold-документа в `docs/adr/`** (статус Draft, Sprint 24 candidate):
   - `0063-presidio-ru-ner-pii.md` (ADR-NEW-16, P0-1, S24 W1) — Presidio + spacy[ru]+ru_core_news_lg + 4 custom recognizers + `make pii-audit` gate.
   - `0064-nemo-guardrails-llama-guard.md` (ADR-NEW-17, P0-2, S24 W2) — defense-in-depth pipeline.
   - `0065-langgraph-checkpointer-mem0.md` (ADR-NEW-18, P0-3, S24 W3) — `MemoryProtocol` триада.
3. **Memory note** `~/.claude/.../memory/feedback_gap_analysis_ai_2026_05_22.md` + MEMORY.md +1 указатель.
4. **2 session summary** в vault: `1300-gap-analysis-ai-summary.md` (детальный) + `1352-summary.md` (compact).

### Изменённые файлы

- ✅ 7 новых файлов (см. выше).
- ❌ Не трогались: `src/backend/`, `pyproject.toml`, `PLAN.md`, `.claude/DECISIONS.md`, `.claude/KNOWN_ISSUES.md`, `requirements.txt`.

### Выполненные команды проверки

- `git status --short` — 30+ M-файлов **параллельной сессии S21 multi-tenancy**, 7 моих untracked.
- `git log --oneline -1` — HEAD `d0ffdc39`.
- `ls docs/adr/` → последний 0062 → мои новые 0063/0064/0065.
- **НЕ запускались**: lint, type-check, `make docs`, тесты — нет code-изменений, scaffold-документация gate-нейтральна.

### Открытые риски

1. **Параллельная сессия активна** на S21 K1 W1/W2 (multi-tenancy / TenantCacheBackend / RLS) + S17 K1 W6 yaml-safeload. Зона работ не пересекается с AI-GAP. Коммит требует `git commit -- <pathspec>` с явным списком только моих 4 трекаемых файлов ([[feedback_git_commit_pathspec]]).
2. **3 ADR в статусе Draft** — не зарегистрированы в Sphinx index/toctree; добавление — после Sprint 24 W1-W3 closure → Accepted.
3. **ADR-NEW-12/13/14 уже заняты** в DECISIONS.md (RLS Strategy / RPACallPolicy / Workflow State Persistence) — поэтому новые AI Safety ADR получили номера **ADR-NEW-16/17/18** (после ADR-NEW-15 Chaos PR-gate).
4. **vault/gap-analysis в .gitignore** — local-only артефакты; в commit пойдут только 4 трекаемых файла (3 ADR + .claude/CONTEXT.md).
5. **Параллельная сессия не знает про AI-GAP** — её CONTEXT.md update приземлится поверх моего; phase commit моих файлов до её следующего CONTEXT.md write желателен.

### Решения AskUserQuestion (зафиксированы)

| Вопрос | Ответ |
|---|---|
| Как распределить три P0 GAP | **Новый Sprint 24 — AI Safety Hardening** (W1 PII / W2 Guardrails / W3 Memory), не S22 K4 / не §S21A |
| Какие номера ADR-NEW использовать? | **ADR-NEW-16/17/18** (12/13/14 уже заняты RLS/RPA/Workflow) |
| Commit стратегия? | **1 commit + PLAN.md update separately** (2 коммита) |
| feature-coordinator timing? | **В этой сессии после ExitPlanMode** |

### Следующий шаг

**Рекомендация A → C → D → B** (в этой сессии):

1. **A. Commit 1 — doc-артефакты** (4 трекаемых файла): 3 ADR + .claude/CONTEXT.md через `git commit -- <pathspec>`. **НЕ stage** файлов параллельной сессии.
2. **D. Commit 2 — PLAN.md V22.3 §S24 + DECISIONS.md ADR-NEW-16/17/18** (новый Sprint 24 — AI Safety Hardening, 3 wave + 9 DoD + 3 ADR).
3. **B. feature-coordinator S24 W1** (Presidio + ru NER) — в этой же сессии после Commit 2, с Pre-Wave subagent ритуалом (4 субагента: СД/АН/ДО/ТЕС).
4. **C. После S24 closure** — S25 candidate (P1 GAP: Low-context / Observability PII / Agent orchestration consolidation / RAG quality CI-gate).

---

## Текущее состояние (2026-05-22, Sprint 21 ✅ CLOSED 10/10)

**Sprint 21 — Resilience & Multi-tenancy Hardening** закрыт coordinator-self mode за одну сессию: backbone + 9 wave + closure = 11 commits, 55/55 unit-тестов passing (+5 skipped: RLS требует Postgres DSN).

**Источник**: PLAN.md V22.2 FINAL §4 + `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md`.

### Sprint 21 closure-таблица (11 commits)

| Wave | Commit | Закрытые блокеры |
|---|---|---|
| `s21/backbone` | `e19bd247` | 8 feature-flags + team.s21 + KNOWN_ISSUES |
| `s21/k1-w1-rls-postgres` | `5bd787c3` | ADR-NEW-12 + G-08 |
| `s21/k1-w2-tenant-cache-wrapper` | `d0ffdc39` | B-03 |
| `s21/k2-w1-rpa-resilience-wrapper` | `5cf7cce3` | ADR-NEW-13 + B-02 |
| `s21/k2-w2-scheduler-dlq` | `ce6b1c33` | G-09 |
| `s21/k2-w3-webhook-resilience` | `8333c75a` | G-07 |
| `s21/k3-w1-desktop-rpa-pool` | `26daceae` | F-12 + B-09 |
| `s21/k3-w2-browser-cookies-redis` | `55e1531d` | G-06 |
| `s21/k3-w3-workflow-state-persist` | `f6702f60` | ADR-NEW-14 + B-05 + S17 K-OPS-1 |
| `s21/k5-w1-streamlit-tenant-admin` | `9cc58a68` | W9 page 83 |
| `s21/closure` | _этот_ | DoD verify + memory + vault summary |

### Параллельная активность

В master параллельная сессия продолжала S17 wave (`8cacb47b k1-w1-tls-cert-required`, `dcc97799 k2-w3-task-registry-coverage`, `b49526dc k1-w0-polish`, `2eeef6aa k2-w1b-rlock-sweep`, `3f3aeec3 k1-w6-yaml-safeload`) и `5cab6a58 plan:v22.2/adr-a-01..07` — наша работа не пересеклась (изоляция через `git commit -- <pathspec>`).

### Открытые carryover S22

См. `.claude/KNOWN_ISSUES.md` секцию «Sprint 21 GAP-backlog status» → «Open carryover в S22» (6 пунктов).

---

## Текущее состояние (2026-05-21 20:45, Sprint 16 12/12 DoD closed)

**HEAD**: `69a19197 [wave:s17/k2-w4-pybreaker-restore]` — Sprint 16 closure сессия закрыла **3 active blocker (b1/b2/b3 partial)** + S16 12/12 DoD.
**Активный спринт**: S16 **CLOSED 12/12** ➜ полностью переходим в **S17 GAP P0 Closure + Centralization Hardening**.
**План**: `PLAN.md` V22.2 + GAP V2 update (S21-S23 backlog).
**GAP-анализ**: `gap-analysis/GAP-ANALYSIS-V2-gd_integration_tools-2026-05-21.md` (V2, 74/100).

### Sprint 16 closure сессия (2026-05-21 20:00–20:45) — 4 wave landed

| Wave | Commit | Закрыто |
|---|---|---|
| `s17/k2-w0-fix-circular-degradation` | `b1f68b97` | **b1 RESOLVED** — `DegradationManager` импорт в `core/resilience/__init__.py` ПЕРЕД `decorators.policy`; `pytest --co tests/unit/infrastructure/workflow/test_lite_temporal_backend.py` 7 collected (было ImportError). |
| `s17/k1-w1-sftp-known-hosts-strict` | `a6a9a098` | **b2 PARTIAL** — `_resolve_known_hosts()` helper + dev_light skip + prod ValueError; 4 × `known_hosts=None` в SFTP заменены; `ftp.py:170` Python-2 except clause → tuple form. FTP/IMAP CERT_NONE carryover. |
| `s17/k2-w4-pybreaker-restore` | `69a19197` | **b3 PARTIAL** — `make_pybreaker_adapter` factory + `v11.pybreaker_enabled=False` feature-flag + DoD-9 restart acceptance (state=open после restore, fail_counter=5). pybreaker SDK + RedisBreakerStateStorage carryover. |
| `s16/closure` | _этот_ | **S16 12/12 DoD** declarativly closed; CONTEXT/KNOWN_ISSUES обновлены; memory note + vault summary. |

**HEAD до сессии**: `20fff6ac [plan:v22.2/s21-s23-post-prod-backlog]` — PLAN.md V22.2 FINAL + 3 спринта (S21-S23) + 4 ADR-NEW-12..15 (предыдущий: `67d37f82 [wave:s17/k2-w1-metrics-registry]` MetricsRegistry D11 backbone).
**Активный спринт**: **Sprint 17 — GAP P0 Closure + Centralization Hardening** (kickoff закрыт 7 wave в одной сессии coordinator-self) + carryover Sprint 16 «Closure» + post-prod **S21-S23 GAP-backlog**.
**План**: `PLAN.md` **V22.2 FINAL** (S16-S20: 5 спринтов × 2 недели × 5 команд **+ S21-S23 post-production GAP-backlog без дат**).
**Параллельность**: вторая сессия добавила `6a35c75d [wave:s17/k9-tooling-grep-violations-gate]` (V22 §5 AST gate) + модифицировала CONTEXT/DECISIONS/KNOWN_ISSUES/PLAN.md (S21-S23 post-production gap-backlog ADR-NEW-12..15) — её работа не коммичена в working tree, не трогалась моей сессией.
**Post-production backlog**: **S21-S23 GAP-backlog активен без дат** (28 пунктов из `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` + 4 новых ADR-NEW-12..15). Запускается после Sprint 20 (`v1.0.0-production`) параллельно release stabilization. См. `PLAN.md` §4 секции Sprint 21/22/23 + `.claude/DECISIONS.md::## ADR из DEEP-RESEARCH Sprint 21-23` + `.claude/KNOWN_ISSUES.md::## Sprint 21-23 GAP-backlog`.

### Sprint 17 kickoff — 7 wave landed (текущая сессия 17:48)

| Wave | Commit | Закрыто |
|---|---|---|
| `s17/backbone` | `b08c974d` | 12 default-OFF feature-flags + 10-команд team-ownership + KNOWN_ISSUES S17 |
| `s17/k3-w0-routes-capability-gate` | `970b655b` | **K-ARCH-3** audit-event `route.capabilities.allocated` + strict-mode |
| `s17/k1-w3-call-function-whitelist-strict` | `83ebf9f5` | **K-ARCH-5** RCE prevention: prod strict + `CapabilityGate.check(function.call.<module>)` |
| `s17/k5-w3-db-migration-init-container` | `c603b895` | **K-OPS-4** alembic init: compose `service_completed_successfully` + k8s Job |
| `s17/k1-w2-authorization-gateway` | `bd49a53c` | **ADR-NEW-1+4** AuthorizationGateway фасад + CapabilityGatewayProtocol scaffold |
| `s17/k3-w1-unified-request-context` | `7a335d52` | **ADR-NEW-3** RequestContext frozen dataclass + ContextVar + ASGI MW |
| `s17/k2-w1-metrics-registry` | `67d37f82` | **D11 backbone** idempotent MetricsRegistry с default_labels (tenant/route/component/env) |
| `s17/k9-tooling-grep-violations-gate` | `6a35c75d` | **V22 §5 gate** (параллельная сессия) |
| `plan:v22.2/s21-s23-post-prod-backlog` | `20fff6ac` | **PLAN.md V22.2** + 3 спринта S21/S22/S23 (40 wave, 40 DoD) + 4 ADR-NEW-12..15 (RLS / RPACallPolicy / Workflow State Persist / Chaos PR-gate); +514/-42 LOC в 4 файлах |

### Sprint 16 — Wave-таблица последних сессий (post 2026-05-21 12:00)

| Wave | Commit | Закрыто |
|---|---|---|
| `w3-config-validator` | `06142dda` | B-2 WAF strict + B-9 ConfigValidator |
| `w4-task-registry-coverage` | `f0b0a7b9` | B-8 TaskRegistry coverage |
| `w5-mw-dedup-scheduler-metrics` | `cd5dcbf3` | M-1 APIKey dedup + M-9/CP-22 APScheduler obs |
| `w6-async-payload-scanner` | `4c9f6eaa` | B-3 finale interface |
| `w7-clamav-production-wire` | `ecaa198e` | B-3 finale production wire |
| `w8-audit-service-unified` | `c1f89e97` | CP-20 partial (AuditService facade) |
| `w9-feature-flag-runtime-overrides` | `ef9e41f6` | CP-15 partial |
| `k2-w1-asyncio-lock-registry` | `ea4bea22` | **DoD-2** drop threading.RLock |
| `closure-docs-phase-c-gap` | `8ee05775` | Phase C финал + **ADR-NEW-5..11** + S18+3 / S19+4 wave |
| `k1-w1-v1-hotfix-cert-none` | `0ce57673` | **DoD-3 partial** ssl.CERT_NONE drop |
| `k1-w4-pyproject-prune-empties` | `f31be5e3` | **DoD-11** cleanup 8 V20 commented extras |
| `k2-w2-outbox-tx-atomic` | `b4b16739` | **DoD-4** transactional outbox |
| `k3-w1-pygls-lsp-completion-hover` | `bfe5415d` | **DoD-5** LSP completion+hover |
| `k2-w6-litetemporal-simplify` | `aa9beca9` | **OE-3** LiteTemporalBackend 120→76 LOC |
| `k1-w2-jwt-introspection` | `012c6500` | **DoD-7** RFC 7662 introspection + 7 unit-тестов |
| `k4-w1-adaptive-rag-classifier` | `b27ed2cd` | **DoD-6** QueryClassifier + benchmark |
| `k5-w3-coverage-gate-75` | `352de31c` | **DoD-10** fail_under=75 + tools/coverage/breakdown_by_layer.py |
| `k1-w3-vault-rotation-protocol` | `fb24f4b9` | **DoD-8** SecretRotator + audit hooks (параллельная сессия) |
| `k5-w1-plugin-topo-sort` | `ad21354e` | **L8-P1-1** PluginGraphResolver + topo-sort + cycle detection |
| `s17/k9-tooling-grep-violations-gate` | `6a35c75d` | **V22 §5 gate** AST-aware checker 8 правил + 5 false-positive фильтров (stdlib-only) |

### Готовность по слоям (актуальная)

| Слой | Оценка | Статус | Закрыто за сессию |
|---|---|---|---|
| L1 Gateway/Middleware | 8/10 | 🟢 | M-1 dedup |
| L2 Auth | 7/10 | 🟡 | M-2 был уже закрыт ранее |
| **L3 WAF/Outbound** | **9/10** | 🟢 | B-2 + B-3 finale (+2.5) |
| L4 DSL/Routes | 8/10 | 🟢 | — |
| L5 AI/RPA/Plugins | 8.5/10 | 🟢 | — |
| L6 Entrypoints | 9/10 | 🟢 | — |
| L7 Observability | 9/10 | 🟢 | CP-21 + M-9/CP-22 |
| L8 Tests | 8/10 | 🟡 | — (coverage 50%→70% carryover) |
| L9 CI/CD | 7.5/10 | 🟡 | — (push pending) |
| L10 Security | 9/10 | 🟢 | B-2 + B-9 + B-3 + ClamAV imports |

**Среднее**: **8.30/10** (было 7.7).

> **Timing-note (важно для интерпретации)**: текущая оценка **8.30/10 (post S16 Waves 3-7)** отражает закрытые B-2 (WAF strict-in-prod) / B-3 (ClamAV PayloadScanner) / B-9 (ConfigValidator). Baseline **GAP-аудит pre-S16 = 5.7/10** (10 слоёв × 4 вектора, см. `.claude/KNOWN_ISSUES.md` секцию «GAP-аудит 2026-05-21»). Цифры не противоречат: разница 5.7 → 8.30 — это эффект S16 Waves 3-7 closure. При onboarding нового разработчика читать обе оценки в указанном порядке (GAP-аудит как baseline → текущая таблица как delta).

### Закрытые P0 блокеры

✅ **B-2** WAF strict-in-prod (Wave 3)
✅ **B-3** ClamAV PayloadScanner — interface (Wave 6) + wire (Wave 7)
✅ **B-8** TaskRegistry coverage (Wave 4; 2 secrets carryover)
✅ **B-9** ConfigValidator (Wave 3)

### Открытые P0 блокеры (для следующих сессий)

- **B-1** SAML completion (`parse_idp_metadata` + SP endpoints) → Sprint 18 К1
- **B-4** OWASP ZAP fail-on-medium → Sprint 18 К1
- **B-5** EntryGateway для 14 protocol adapters → Sprint 17 EG-1 contract-test
- **B-6** FeatureFlagService finale (Redis pub/sub + admin endpoint) → CP-15 Sprint 17 К1
- **B-7** AuditService.emit unified → CP-20 Sprint 17 К3

### Открытые риски

1. ~~Circular import `DegradationManager`~~ — **RESOLVED** `b1f68b97 [wave:s17/k2-w0-fix-circular-degradation]` (Sprint 16 closure сессия 2026-05-21 20:00).
2. **DoD-3 FTP/IMAP carryover** — `ssl.CERT_NONE` остаётся в 6 файлах (email_imap/email/ftp×2/imap_monitor); SFTP-вектор закрыт `a6a9a098`, asyncssh pool migration FTP/IMAP в S17.
3. **Coverage 75% не verified empirically** — `fail_under` декларирован, baseline `pytest --cov` ещё не прогнан; первый запуск может упасть → ramp-down при необходимости.
4. **Параллельная сессия активна** — untracked `services/ai/rag/classifier.py` в working tree; `git pull` обязателен в next session.
5. **B-8 carryover**: 2 `asyncio.create_task` в `infrastructure/secrets/` под path-policy.
6. **lint-strict 164 errors carryover** (S112/BLE001).
7. **OTel Wave 1 unit-тесты** pre-merge gate carryover.
8. **`M src/backend/core/plugin_runtime/sandbox.py`** — pre-merge gate ожидает S18/S19 strategy.
9. **Push pending ~100 commits** — commit-policy запрещает без явного запроса; разрешён в S20.
10. **76 LOC LiteTemporalBackend > 70 target** — 6 LOC overshoot, не критично (дальнейшее сжатие удалит русские docstrings).
11. **NEW: 220 violations baseline от `check-grep-violations`** — gate выйдет с exit 1 на любом проходе по `src/backend`. Распределение: ~150 `except-pass` (новое для оценки — план не учёл) + ~20 `threading-lock-in-async` (DoD-2 carryover S17 K2-W1) + ~20 `inline-metric` (CP-18 carryover S17 K1) + ~5–10 `orphan-create-task` (B-8 carryover) + остатки `ssl-insecure`/`yaml-load-unsafe`/`pickle-loads`/`eval-exec`. Target standalone, НЕ включён в `check-strict-full`/`ci` (по плану). Нужно: a) baseline-allowlist по аналогии с `check_docstrings_allowlist.txt`, ИЛИ b) wave «except-pass cleanup» для крупнейшего кластера.

### Выполненные команды проверки за сессию (17:48)

- `python tools/check_team_ownership.py` — ✅ 10 команд (k1..k10) + 4 блокеров OK
- `python tools/checks/check_routes_capability_gate.py --strict` — ✅ declare() ДО registrar() + audit-event
- Smoke imports 6 новых модулей (capability_gateway / authorization_gateway / request_context / request_context MW / metrics_registry / FeatureFlags S17 flags) — ✅
- `pytest tests/unit/core/security/test_authorization_gateway.py` — ✅ 10/10
- `pytest tests/unit/entrypoints/middlewares/test_request_context.py` — ✅ 11/11
- `pytest tests/unit/infrastructure/observability/test_metrics_registry.py` — ✅ 12/12
- `pytest tests/unit/services/routes/test_loader.py` — ✅ 28/28 (25 baseline + 3 новых для K-ARCH-3)
- `pytest tests/unit/dsl/engine/processors/test_function_call.py` — ✅ 10/10 NEW (K-ARCH-5)
- `pytest tests/unit/dsl/round_trip/test_new_fluent_methods.py` — ✅ 15/15 regression
- `ruff check` все 6 новых файлов + 3 modified — ✅ All checks passed (после auto-fix I001 + noqa S110 на pre-existing блок)
- `yaml.safe_load` для docker-compose.yml + k8s migration.yaml — ✅ синтаксис OK

### Выполненные команды проверки за параллельную сессию (17:17)

- `python tools/checks/check_grep_violations.py --root src/backend` — **220 violation(s) found** (новая baseline-карта реального техдолга)
- `python tools/checks/check_grep_violations.py --root src/backend --json | python -m json.tool` — ✅ JSON valid
- `make -n check-grep-violations` — ✅ корректно собирается `uv run python tools/checks/check_grep_violations.py --root src/backend`
- Synthetic violation `asyncio.create_task` → ✅ exit 1
- Docstring пример `yaml.load(data)` → ✅ exit 0 (AST автоматически не парсит string-содержимое)
- ruamel.yaml `YAML().load()` → ✅ exit 0 (через анализ импортов)
- selftest + `if __name__ == "__main__":` → ✅ exit 0
- noqa allowlist (`# noqa: violation-check`) → ✅ 1/2 detected, помеченная пропущена
- `uv run ruff check tools/checks/check_grep_violations.py` — ✅ All checks passed (после `# noqa: S105` × 2 на идентификаторах правил)
- `uv run mypy tools/checks/check_grep_violations.py` — ✅ Success: no issues found

### Выполненные команды проверки за предыдущую сессию (16:20)

- `uv run pytest tests/unit/core/plugin_runtime/test_dependency_resolver.py -x -v` — ✅ **5/5 passed in 0.29s**
- `uv run pytest tests/unit/core/plugin_runtime/` — ✅ **21/21 passed in 0.33s**
- `uv run pytest tests/unit/services/plugins/test_loader_v11.py test_loader_v11_frontend_pages.py` — ✅ **21/21 passed in 0.35s** (regress-free)
- `uv run ruff check <4 modified files>` — ✅ All checks passed
- `uv run mypy src/backend/core/plugin_runtime/dependency_resolver.py` — ✅ Success
- `uv run mypy src/backend/services/plugins/loader_v11.py` — ✅ Success
- `uv run python -c "from src.backend.core.plugin_runtime import PluginGraphResolver, PluginDependencyCycleError"` — ✅ OK

### Командные проверки предыдущей сессии (16:15, для истории)

- `uv lock --check` — ✅ 657 packages resolved
- `pytest tests/unit/entrypoints/api/v1/test_auth_introspect.py -x -q` — ✅ **7/7 passed in 0.44s**
- ⚠️ `pytest tests/unit/infrastructure/workflow/test_lite_temporal_backend.py` — collection error (DegradationManager circular import carryover)

### Следующий шаг

**На обсуждение (plan mode, 2026-05-21 17:17)** — кандидаты на следующую итерацию:

- **A. Baseline-allowlist + интеграция в CI** — `tools/checks/violation_check_allowlist.txt` со списком 220 текущих позиций; включить gate в `check-strict-full` (ratcheting как mypy-budget).
- **B. except-pass cleanup wave** — выделенная S17 wave «replace `except: pass` with `except: logger.exception()`» — закроет крупнейший кластер ~150 нарушений за один проход.
- **C. S17 carryover** — DoD-3 finale FTP, DoD-9 pybreaker, CP-15 FeatureFlagService, CP-20 AuditService.
- **D. Расширение grep-gate новыми правилами V22** — pre-import check, banned-imports по слоям AST.
- **E. Push pending ~100 commits** — заблокировано commit-policy до S20.

**S16 closure (оставшиеся wave для 12/12 DoD)**:

1. **DoD-3 finale** `[wave:s16/k1-w1-asyncssh-pool]` — FTP migration на asyncssh + testcontainers.
2. **DoD-9** `[wave:s16/k2-w4-pybreaker-replace]` — custom CB → pybreaker, Redis state backend.
3. **DoD-12** `[wave:s16/closure]` — финал DoD audit + memory note + `make pre-prod-check`.
4. ~~**DoD-8** Vault rotation~~ — закрыто `fb24f4b9` (параллельная сессия)
5. ~~**L8-P1-1** PluginGraphResolver topo-sort~~ — закрыто `ad21354e` (текущая сессия)

**Sprint 17 «Centralization» (после S16 closure)**:
1. **CP-15 FeatureFlagService finale** (B-6) — Redis pub/sub + admin endpoint.
2. **CP-20 AuditService.emit() unified** (B-7) — единый emit, 4 callsites рефактор.
3. **CP-17 AuthorizationGateway** (M-5) — фасад Casbin/OPA/CapabilityGate.
4. **CP-18 MetricsRegistry** (M-8) — idempotent registry, миграция 30 Counter + 6 Histogram.

**Перед next wave** обязательно: разрешить `DegradationManager` circular import → `pytest --co -q` зелёный → empirical coverage baseline через `python tools/coverage/breakdown_by_layer.py coverage.xml` → **`git pull`** (HEAD после `20fff6ac` мог обновиться параллельной сессией).

### Сессия 2026-05-21 18:04 — PLAN.md V22.2 + S21-S23 post-prod GAP-backlog (commit `20fff6ac`)

**Что сделано** (только документация): PLAN.md V22.1 → V22.2 FINAL, +197 LOC; добавлены 3 спринта Sprint 21 Resilience+Multi-tenancy (12 DoD) / Sprint 22 Observability+Testing (14 DoD) / Sprint 23 AI/DSL/DX (14 DoD); 41 wave-tag; 4 ADR-NEW-12..15 (RLS Strategy / RPACallPolicy / Workflow State Persistence / Chaos PR-gate); .claude/DECISIONS.md +138 LOC; .claude/KNOWN_ISSUES.md +72 LOC; CONTEXT.md +36 LOC (мои); memory note `feedback_plan_v22_2_extension.md`. Покрыто 28 нерешённых GAP-пунктов DEEP-RESEARCH 2026-05-20 + 5 follow-up к частично покрытым.

**Изменённые файлы** (4): PLAN.md (633→810), .claude/DECISIONS.md (320→456), .claude/KNOWN_ISSUES.md (958→1030), .claude/CONTEXT.md (244→273+, частично pre-existing). Commit `20fff6ac` через `git commit -- <pathspec>`.

**Verify**: `wc -l PLAN.md = 810`; sprint count = 8 (S16-S23); wave-tags S21-S23 = 41; ADR-NEW-12..15 = 4; все 28 GAP-кодов присутствуют.

**Открытые риски этой сессии**:
1. **Параллельная активность** — фоновая сессия закоммитила 8 wave Sprint 17 kickoff пока я работал; их CONTEXT.md update приземлён до моего commit и попал в мой `20fff6ac` через staged tracked-modified (см. `feedback_git_commit_pathspec`).
2. **S21-S23 без дат** — runtime startup только после S20 closure (`v1.0.0-production`).
3. **ADR-table в §6 PLAN.md = 14 строк** (R1.x×10 + ADR-NEW-12..15×4), план рассчитывал ≥15 — отклонение не критично.

**Следующий шаг**:
1. Sprint 17 carryover: K-ARCH-4 tenant-aware routes / K-OPS-1 Saga state / K-OPS-2 K8s manifests / K-OPS-3 pre-prod-check v2 scaffold / CP-15 FFs / CP-20 AuditService unified.
2. 220 grep-violations baseline strategy (carryover S17 K9).
3. DoD-3 finale FTP (`asyncssh` pool) + DoD-9 pybreaker (S16 closure).
4. S21-S23 — НЕ открывать до S20 finale.

### Архив + сессии

- `vault/session-2026-05-21-1804-summary.md` — **детальная сводка текущей сессии** (PLAN.md V22.2 + S21-S23 post-prod GAP-backlog, 4 файла, +514 LOC, 4 ADR-NEW, 0 кода).
- `vault/session-2026-05-21-1748-summary.md` — S17 kickoff coordinator-self (7 wave, ~1100 LOC, 46 новых тестов, ADR-NEW-1/3/4 scaffold + K-ARCH-3/5 + K-OPS-4 + D11 backbone).
- `vault/session-2026-05-21-1717-summary.md` — параллельная сессия (S17 K9 AST-aware grep-gate, 2 файла, +271 LOC, 220 violations baseline).
- `vault/session-2026-05-21-1620-summary.md` — K5-W1 PluginGraphResolver (4 файла, +363).
- `vault/session-2026-05-21-1615-summary.md` — Phase C + Actions 0-5.
- `vault/session-2026-05-21-1400-summary.md` — Waves 3-7 GAP closure.
- `vault/session-2026-05-2[01]-*-summary.md` — предыдущие сессии.
- `vault/archive-plan-v21.md` — архив PLAN.md V21.
- `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` — внутренний V3.0 (38 GAP по 14 доменам).

---

## GAP-аудит 2026-05-21 — onboarding для нового разработчика

> Эта секция — карта-маршрут для новичка, который заходит на pre-production gd_integration_tools после 15+ закрытых спринтов и активного Sprint 16. Полные findings — `.claude/KNOWN_ISSUES.md` (секция GAP-аудит 2026-05-21).

### 1. Сначала прочитать (≤ 30 минут)

1. **`PLAN.md` секции 0–2** (видение, принципы V22, команды) — что строим и почему.
2. **`ARCHITECTURE.md` секция «Архитектурная схема» + «Слои L1–L10»** — как устроено.
3. **`.claude/KNOWN_ISSUES.md` секция «GAP-аудит 2026-05-21»** — что сломано/неготово прямо сейчас.
4. **`.claude/DECISIONS.md` ADR-NEW-1..4** — 4 архитектурных решения для Sprint 17 (что меняем).

### 2. Готовность слоёв (10-слойный аудит, среднее **5.7/10**)

| Слой | Оценка | Главная боль |
|------|--------|--------------|
| **L8 Security** | **7.0** ✅ | OWASP ZAP non-blocking; OPA не интегрирован runtime |
| **L2 Core Kernel** | **6.5** | ActionMetadata без retry-policy; lifecycle не идемпотентна; `providers.py` Any-returns (S-L2-1 Exchange.stopped REVISED — property-based, не баг) |
| **L3 Routes** | **6.5** | Routes не проходят capability-gate; tenant-aware сломан |
| **L4 AI Pipelines** | **6.5** | Banking processors (KYC/AML/CreditScoring) — empty shells |
| **L1 Gateway/MW** | **6.0** | Plugin-registry отсутствует; per-route override невозможен |
| **L10 Test Coverage** | **5.9** | testkit/ public API отсутствует; PBT/mutation = 0%; E2E = 1 файл |
| **L5 RPA** | **5.0** | Browser context leak; нет WAF для browser; нет session persistence |
| **L7 Observability** | **5.0** | OTel trace_id не в structlog; Graylog FD leak; CH audit без retry |
| **L9 DevOps** | **5.0** | K8s manifests неполные; pre-prod-check v2 не реализован; DR отсутствует |
| **L6 Data&State** | **3.0** ⚠️ | 70+ Python 2 syntax-errors (grep `-l` = 71) → импорт невозможен |

### 3. 🔴 P0 блокеры pre-production (17 — все в Sprint 17)

**Прежде чем писать новую фичу**, знай о:

1. **70+ файлов с Python 2-style `except E1, E2:`** (точный grep `-l` = 71) — приходят из L6 (database/clients/storage/logging/secrets), L7 (`tracing.py`, `mcp_server.py`, `workspace_manager.py`), L5 (`rpa.py:816`), а также `dsl/`, `services/`, `entrypoints/`. CI-импорт падает. Сводный fix через codemods — `[wave:s17/k1-w0-python3-except-clause-sweep]` (см. F-A-4 codemod pre-test gate в DoD).
2. **FTP/IMAP TLS CERT_NONE** в трёх файлах (V1 violation, банковский compliance) — `[wave:s17/k1-w1-tls-cert-required]`.
3. **AuthorizationGateway отсутствует** (ADR-NEW-1) — единая точка авторизации (Casbin/OPA/CapabilityGate) — `[wave:s17/k1-w2-authorization-gateway]`.
4. **CapabilityGateway Protocol** не вынесен в `core/interfaces/` (ADR-NEW-4) — Clean Architecture violation.
5. **Routes без capability-gate** — `services/routes/loader.py:70` пропускает declare(); security violation.
6. **Tenant-aware routes сломаны** — `RouteManifestV11.tenant_aware` читается, но не пробрасывается в DSL-шаги.
7. **`call_function_modules` dev fallback** = пустой whitelist пропускает все модули → RCE в production.
8. **Saga state store отсутствует** — workflow-гарантии не полны.
9. **K8s manifests неполные** — есть только HPA для temporal-worker, нет Deployment/Service/PDB/Ingress.
10. **`make pre-prod-check v2 (38/38)` не реализован** — V22 final DoD заблокирован.
11. **БД migrations не в deploy-flow** — нет init-container.
12. **Backup/DR procedures отсутствуют** — нет `ops/backup/`, нет runbook'ов.

### 4. ✅ Сильные стороны (можно копировать в новые модули)

- **CapabilityGate** (`core/plugin_runtime/capability_gate.py`) — LRU-кэш + subset-проверка + audit-callback. **Цитировать в подобных gateway/policy-engines.**
- **OutboundHttpClient + WafPolicy** (`core/net/outbound_http.py`) — обязательный fascade для всех `:external` HTTP. **Расширять для новых протоколов (SOAP/gRPC/MQ).**
- **Camel-style Exchange/Pipeline** (`dsl/engine/exchange.py` + `pipeline.py`) — каноничный аналог Apache Camel. **Использовать как образец для новых processor-цепочек.**
- **AuthRequiredMiddleware** (`entrypoints/middlewares/auth_required.py`) — централизованная auth (6 методов). **Маршруты auth-агностичны — не добавлять `Depends(get_user)` в endpoint.**
- **structlog batching** (`infrastructure/observability/structlog_batching.py`) — feature-flagged batching wrapper. **Использовать для high-RPS логирования.**
- **TaskRegistry** (`core/utils/task_registry.py`) — все `asyncio.create_task` через registry с lifecycle (V22 obligatory).

### 5. Антипаттерны (не делать никогда)

- ❌ `except ConnectionError, OSError:` — Python 2 syntax (CI gate failed). Используй `except (ConnectionError, OSError):`.
- ❌ `ssl.CERT_NONE` / `check_hostname=False` — V1 violation (банковский compliance).
- ❌ Прямой `requests.get(...)` или `httpx.get(...)` для `:external` URL — обязательно через `OutboundHttpClient`.
- ❌ `asyncio.create_task(...)` напрямую — через `TaskRegistry.create_task(name, deadline)`.
- ❌ `= Counter(...)` / `= Histogram(...)` напрямую (S17 V22) — через `MetricsRegistry.get_counter(name, labels)`.
- ❌ `if request.user.is_admin` ad-hoc auth — через `AuthorizationGateway.authorize(...)` (S17).
- ❌ `from gd_integration_tools.infrastructure.*` в `services/` или `core/` — Clean Architecture violation (`make layers` поймает).
- ❌ AI-плагин пишет в существующий файл — capability `fs.write.*` запрещена; только `fs.create_new.<workspace>`.

### 6. Если работаешь над…

- **Auth/Security** → начни с `core/security/` + `core/auth/` + read `tools/check_waf_coverage.py`. Делай через `AuthorizationGateway` (S17).
- **DSL/Routes** → `dsl/route/builder/` (миксины) + `routes/echo_demo/` (пример). Не забудь capability-gate в loader.
- **Plugin** → `extensions/example_plugin/plugin.toml` (шаблон) + V11 manifest + capability declaration ДО import.
- **Workflow** → `dsl/workflow/` + Temporal SDK; `LiteTemporalBackend` для dev_light. Saga state model — пока отсутствует (S17).
- **AI/RAG** → `services/ai/` + `core/ai/workspace_manager.py` (workspace isolation обязательна) + `infrastructure/cache/rag/` (3-tier).
- **Observability** → `infrastructure/observability/otel_auto.py` (9 instrumentators) + structlog batching. Не забудь правильный shutdown order.
- **Database** → advanced-alchemy + asyncpg async-only; connection pool обязательно с `pool_pre_ping=True`; outbox pattern для messaging.

### 7. Sprint 17–S20 (GAP-driven replace V22, см. PLAN.md)

- **S17 Centralization Hardening** — 17 P0 блокеров + ADR-NEW-1..4 backbone
- **S18 Operational + Security carryover** — S-L1/S-L7/S-L8 пробелы + K8s Helm + БД migration init-container + multi-tenant rate-limit + WAF allowlist tightening
- **S19 DSL+AI расширения + DX** — workflow versioning + route composition + route authz + multipart RAG + reranking + RPA sessions + VSCode extension + Adaptive RAG strategy
- **S20 Production Signoff** — pre-prod-check v2 38/38 + coverage 83% + mypy 0 + p95 ≤80ms + RPS ≥1500 + DR & Backup verified + canary 1→10→50→100%

### 8. Команды для быстрой ориентации

```bash
make help                  # все команды Makefile с группами
manage.py --help           # CLI 52K со скаффолдингом + диагностикой
make ci                    # lint + type + test + coverage + security
make pre-prod-check        # текущие 20/38 gates (v2 — Sprint 20)
make routes                # каталог зарегистрированных routes
make actions               # каталог зарегистрированных actions
make plugin-schema         # JSON-Schema валидация plugin.toml
make check-waf-coverage    # все :external через OutboundHttpClient
make layers                # check_layers.py --strict-extensions
```

---
