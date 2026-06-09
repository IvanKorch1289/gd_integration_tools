# Итерация 4: DSL роуты, Workflow, AI, RPA

## 4.1 DSL для роутов — 8/10
**Плюсы:** Fluent API 300+ методов, per-step модификаторы (timeout, retry, auth), YAML/TOML dual format, hot-reload (watchfiles, snapshot/rollback), cycle detection, Python builder parity.
**Минусы:** Registry не потокобезопасен (dict без блокировок). Два независимых hot-reload'ера (DSLYamlWatcher + RouteHotReloader) — race. Тихая перезапись route_id. YAML-ошибки без line numbers. Манифест-метаданные (SLO, capabilities) теряются после загрузки.

## 4.2 Workflow engine — 7/10
**Плюсы:** Temporal integration production-ready (client factory, worker pool, activity adapter, data converter). LiteTemporalBackend для dev_light. SagaLRAProcessor (in-memory + persistent). HITL реализован end-to-end (SignalWait, HitlService, REST API, Streamlit UI). WorkflowStateRepository + event-sourcing.
**Минусы:** Компилятор не поддерживает checkpoint, guardrail, escalate, reflect, gateway_* (runtime упадёт с TypeError). Два несовместимых YAML-формата workflow (spec vs BPMN-like). `DSLStepExecutor._exec_sequential` — stub с TODO. Дублирование имени `SagaLRAProcessor`. Нет DLQ для workflow. Deadlock detection только ручная. AgentInvokeDeclaration durable mode — TODO.

## 4.3 AI и агенты — 6.5/10
**Плюсы:** Multi-provider chat, fallback chain, policy gate, three-tier RAG cache, HybridRAG (BM25+dense+rerank), LLM Guard + LlamaGuard, semantic cache, UnifiedMemoryGateway, AIWorkspaceManager, RAGAS evals.
**Минусы:** 3 параллельных кодопути LLM (ai_agent.py, ai_graph.py, agents_pydantic). AIGateway в pass-through (`ai_gateway_enforce=False` default). In-memory хранилища в production (`MultimodalRAGService`, `L3RetrievalGraphCache`, `AIWorkspaceManager._usage`). BLIP2/Llama Guard/Whisper default CPU. `search_web` — blocking BeautifulSoup. NeMo Colang отключён. Rebuff/Lakera — deprecated в коде. LLMJudge — хрупкий prompt-based JSON.

## 4.4 RPA — 6/10
**Плюсы:** Browser pool (Playwright/patchright), cookie persistence (Redis), Desktop sidecar (Windows worker), session pool с affinity, RPACallPolicy (retry, breaker, DLQ), OCR (Tesseract), AI-driven RPA (GPT-4o), shell whitelist.
**Минусы:** RPACallPolicy не проведена в процессоры (только декларируется). Desktop RPA только 3 action (click/type/screenshot). Banking RPA — заглушки (citrix, terminal_3270, appium). Нет Vault-интеграции для RPA credentials. Нет structured audit trail для RPA. Cloud OCR отсутствует. AI RPA без guardrails.

## 4.5 Интеграция роут-workflow-агент — 5/10
**Плюсы:** Единые реестры, декларативная модель, TracingMiddleware, StepAuditMiddleware, baggage.
**Минусы (критичные):** Нет propagation tenant_id/correlation_id в workflow. Workflow→Agent — пустой ctx ("unknown"/"n"). Agent→Tool — нет propagation контекста. `compile_agent_invoke_step` делает прямой await AIGateway в workflow — нарушение Temporal sandbox (nondeterminism при replay). Нет защиты от циклов (call depth, invocation chain). Разрыв между DSL spans и Temporal spans.

## Библиотеки из web search
- Temporal saga patterns — first-class compensation support
- `rpaframework` — Robot Framework + Python RPA библиотеки
- Playwright vs Robot Framework — Playwright быстрее, RF зрелее для enterprise RPA
