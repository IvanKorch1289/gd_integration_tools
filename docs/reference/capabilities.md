# Capability catalog (V11 / ADR-044)

Сгенерировано `tools/export_v11_artefacts.py capability-catalog`. Не редактировать вручную.

| Capability | scope_required | matcher | public | Описание |
|---|---|---|---|---|
| `agent.run` | ✅ | `GlobScopeMatcher` | ➖ | Запуск AI-агента (langgraph_agent). |
| `ai.feedback.train` | ✅ | `ExactAliasMatcher` | ➖ | Запуск DSPy training-loop по labeled feedback + публикация prompt-version (S11 K4 W5). |
| `ai.guardrail.evaluate` | ✅ | `GlobScopeMatcher` | ➖ | Вызов defense-in-depth guardrails pipeline (NeMo Colang input rails + Llama Guard 3 output classifier); scope = tenant-id или '*' (S24 W2, ADR-NEW-17). |
| `ai.guardrail.policy_read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение per-tenant guardrail policy (NeMo/LlamaGuard/Lakera enable map) из tenant_config.py; scope = tenant-id или '*' (S24 W2, ADR-NEW-17, S172: Rebuff заменён на NeMo, F4.2). |
| `ai.guardrails.lakera` | ✅ | `GlobScopeMatcher` | ➖ | Вызов Lakera Guard prompt-injection / PII detector. scope = '*' или конкретный provider-id (S11 K1 W2). |
| `ai.guardrails.nemo` | ✅ | `GlobScopeMatcher` | ➖ | Вызов NeMo Colang self-check guard (S172, replaces Rebuff). scope = '*' или provider-id. research/agent-framework/REPORT.md F4.2. |
| `ai.guardrails.rebuff` | ✅ | `GlobScopeMatcher` | ➖ | [DEPRECATED S172] Вызов Rebuff prompt-injection detector — upstream archived 2026; capability сохранён для backward-compat grants in existing roles. Migrate to ai.guardrails.nemo. research/agent-framework/REPORT.md F4.2. |
| `ai.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Вызов LLM через единую точку входа AIGateway (ADR-NEW-19). Проверяется на каждый AIGateway.invoke(request.workflow_id); scope = workflow_id pattern или '*' (S25 W1). |
| `ai.memory.delete` | ✅ | `GlobScopeMatcher` | ➖ | Удаление user-memory из MemoryProtocol (GDPR / 152-ФЗ user-erasure); scope = tenant-id или '*' (S24 W3, ADR-NEW-18). |
| `ai.memory.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение из MemoryProtocol (LangGraph Checkpointer / Mem0 / AgentMemory); namespace = '<tenant_id>:<scope>'; scope = tenant-id или '*' (S24 W3, ADR-NEW-18). |
| `ai.memory.write` | ✅ | `GlobScopeMatcher` | ➖ | Запись в MemoryProtocol; namespace = '<tenant_id>:<scope>'; scope = tenant-id или '*' (S24 W3, ADR-NEW-18). |
| `ai.model_registry.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение из AI Model Registry (MLflow + HF Hub composite); scope = backend-id или '*' (S11 K4 W6). |
| `ai.model_registry.write` | ✅ | `GlobScopeMatcher` | ➖ | Запись/promote в AI Model Registry. scope = backend-id или '*' (S11 K4 W6). |
| `ai.policy.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение AIPolicySpec из ai_policies/*.policy.yaml через PolicyResolver (ADR-NEW-20); scope = policy-name pattern или '*' (S25 W2). |
| `ai.rag.pii_redaction` | ✅ | `ExactAliasMatcher` | ➖ | Применение PII-маскера к augment_result.documents[*].content в RAG retrieval pipeline (S11 K1 W1). |
| `ai.route.optimize` | ✅ | `GlobScopeMatcher` | ➖ | AI-анализ route-метрик + генерация PR markdown (S11 K4 W7); scope = route-name или '*'. |
| `ai.stream` | ✅ | `SegmentedGlobMatcher` | ➖ | Token-level streaming LLM (SSE/WS) через LLMStreamingService (scope = 'model:<prefix>', optional). |
| `ai.tool.dispatch` | ✅ | `GlobScopeMatcher` | ➖ | Диспетчеризация вызова AI-инструмента. |
| `audit.write` | ✅ | `GlobScopeMatcher` | ✅ | Запись audit-event в audit-sink (infrastructure/audit, admin_audit, correlation-логи). Добавлена 2026-10-06: capability реально используется роутами с шагом `audit:`, но в vocabulary отсутствовала, из-за чего они не могли объявить её ни публично, ни через плагин. scope = tenant-id, audit-sink или '*'. |
| `cache.read` | ✅ | `SegmentedGlobMatcher` | ➖ | Чтение кэша через CacheFacade (namespace по ':'). |
| `cache.write` | ✅ | `SegmentedGlobMatcher` | ➖ | Запись в кэш через CacheFacade (namespace по ':'). |
| `code.execute` | ✅ | `ExactAliasMatcher` | ➖ | Запуск пользовательского кода в sandbox (e2b/pyodide) через CodeSandbox; прямой subprocess запрещён (V15 R-V15-4). |
| `data.export` | ✅ | `GlobScopeMatcher` | ➖ | Выгрузка данных во внешний формат (export-процессор). |
| `db.execute_procedure` | ✅ | `GlobScopeMatcher` | ➖ | Вызов stored procedure во внешней БД через ExternalDatabaseFacade. |
| `db.read` | ✅ | `ExactAliasMatcher` | ➖ | Чтение из БД через DatabaseFacade (read-only-сессия). |
| `db.write` | ✅ | `ExactAliasMatcher` | ➖ | Запись в БД через DatabaseFacade (rw-сессия). |
| `event.publish` | ✅ | `GlobScopeMatcher` | ➖ | Публикация события в шину (integration-процессор). |
| `fs.read` | ✅ | `SegmentedGlobMatcher` | ➖ | Чтение файлов через FSFacade (path-glob по '/'). |
| `fs.watch` | ✅ | `SegmentedGlobMatcher` | ➖ | Наблюдение за файловой системой (watchdog) через FSFacade / FileWatchProcessor; scope = glob по пути наблюдаемого каталога (Cycle 172, Wave 5). |
| `fs.write` | ✅ | `SegmentedGlobMatcher` | ➖ | Унифицированная запись файлов. fs.create_new — deprecated alias (post-S20 removal). Scope: fs.write.workspace.<session_id> для AI-workspaces; fs.write.tenant.<tenant_id> / fs.write.repo.<area> для системных. |
| `jupyter.hub` | ✅ | `GlobScopeMatcher` | ➖ | Выполнение ноутбуков на Jupyter Hub через NotebookFacade. Добавлена 2026-10-06: capability отсутствовала в vocabulary, из-за чего routes/jupyter_hub_run/ не мог объявить её. Имя двухсегментное (<resource>.<verb>), поэтому scope обязателен: роут объявляет 'jupyter.hub:run'. |
| `langmem.admin` | ✅ | `ExactAliasMatcher` | ➖ | Администрирование LangMem: consolidate(), stats(), RLM reset (D.6). |
| `llm.invoke` | ✅ | `SegmentedGlobMatcher` | ➖ | Вызов LLM-провайдера через LLMFacade (provider/model по '/'). |
| `llm.stream` | ✅ | `GlobScopeMatcher` | ➖ | Streaming-вызов LLM (streaming_llm-процессор). |
| `mcp.call` | ✅ | `GlobScopeMatcher` | ➖ | Вызов MCP-инструмента (mcp_tool-процессор). |
| `mcp.gateway.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Вызов tool через MCPGateway namespace (credit/analytics/system) с auth + WAF (ADR-NEW-23); scope = namespace-name или '*' (S27 W4). |
| `mcp.gateway.invoke.analytics` | ✅ | `GlobScopeMatcher` | ➖ | Вызов tool в namespace 'analytics' через MCPGateway (ADR-0070, S27 W4); scope = tool-name или '*'. |
| `mcp.gateway.invoke.credit` | ✅ | `GlobScopeMatcher` | ➖ | Вызов tool в namespace 'credit' через MCPGateway (ADR-0070, S27 W4); scope = tool-name или '*'. |
| `mcp.gateway.invoke.system` | ✅ | `GlobScopeMatcher` | ➖ | Вызов tool в namespace 'system' через MCPGateway (ADR-0070, S27 W4); scope = tool-name или '*'. |
| `mcp.tool.call` | ✅ | `GlobScopeMatcher` | ➖ | Вызов MCP-инструмента (FastMCP HTTP transport); scope = action-name pattern. |
| `message.claim_check.retrieve` | ✅ | `ExactAliasMatcher` | ➖ | Восстановление payload по claim token через EIP ClaimCheckProcessor retrieve-режим. |
| `message.claim_check.store` | ✅ | `ExactAliasMatcher` | ➖ | Сохранение claim token в Redis/S3 через EIP ClaimCheckProcessor store-режим (message-level payload offload). |
| `mq.consume` | ✅ | `GlobScopeMatcher` | ➖ | Подписка на сообщения через MQFacade (topic-glob). |
| `mq.publish` | ✅ | `GlobScopeMatcher` | ➖ | Публикация сообщений через MQFacade (topic-glob). |
| `net.inbound` | ✅ | `GlobScopeMatcher` | ✅ | Регистрация webhook/SSE-эндпоинтов через WebhookFacade. |
| `net.outbound` | ✅ | `GlobScopeMatcher` | ✅ | Исходящие HTTP/gRPC через {HTTP,GRPC}Facade. |
| `pii.audit` | ✅ | `GlobScopeMatcher` | ➖ | Запись audit-event pii.{detected,anonymized,blocked} с tenant_id + entity_type + redacted_hash в immutable Postgres audit-sink; scope = tenant-id или '*' (S24 W1, ADR-NEW-16). |
| `pii.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение текста через PII-detector pipeline (Presidio + ru NER) перед маскированием/anonymize; scope = tenant-id или '*' (S24 W1, ADR-NEW-16). |
| `pii.tokenize.reversible` | ✅ | `GlobScopeMatcher` | ➖ | Reversible PII-токенизация через PIITokenizer (Presidio + AES-GCM TokenRegistry); обязательна для unmask round-trip (ADR-NEW-21). scope = domain-id (banking, hr, medical) или '*' (S25 W4). |
| `pii.tokenize.reversible.agent_actions` | ✅ | `GlobScopeMatcher` | ➖ | PII-токенизация параметров tool/action-вызовов агента (AgentDictPIIMaskProcessor в режиме agent_actions); scope = domain-id (banking, hr, medical) или '*' (Cycle 172, Wave 5). |
| `pii.tokenize.reversible.agent_tools` | ✅ | `GlobScopeMatcher` | ➖ | PII-токенизация аргументов tool-вызовов агента (AgentDictPIIMaskProcessor в режиме agent_tools); scope = domain-id (banking, hr, medical) или '*' (Cycle 172, Wave 5). |
| `pii.write` | ✅ | `GlobScopeMatcher` | ➖ | Запись маскированных payload-ов в outbound LLM / RAG / DLQ / Langfuse traces; scope = tenant-id или '*' (S24 W1, ADR-NEW-16). |
| `rpa.ai.decide` | ✅ | `GlobScopeMatcher` | ➖ | AI-принятие решения внутри RPA-сценария. |
| `rpa.appium.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Вызов Appium-драйвера (мобильная автоматизация). |
| `rpa.archive.execute` | ✅ | `GlobScopeMatcher` | ➖ | Создание/распаковка архива (tar/zip) RPA-процессором. |
| `rpa.browser.click` | ✅ | `GlobScopeMatcher` | ➖ | Клик по элементу страницы (rpa_browser). |
| `rpa.browser.extract` | ✅ | `GlobScopeMatcher` | ➖ | Извлечение данных со страницы (rpa_browser). |
| `rpa.browser.fill` | ✅ | `GlobScopeMatcher` | ➖ | Заполнение полей формы (rpa_browser). |
| `rpa.browser.launch` | ✅ | `GlobScopeMatcher` | ➖ | Запуск браузера (rpa_browser). |
| `rpa.browser.navigate` | ✅ | `GlobScopeMatcher` | ➖ | Навигация по URL (rpa_browser). |
| `rpa.browser.pdf` | ✅ | `GlobScopeMatcher` | ➖ | Сохранение страницы в PDF (rpa_browser). |
| `rpa.browser.screenshot` | ✅ | `GlobScopeMatcher` | ➖ | Скриншот страницы (rpa_browser). |
| `rpa.browser.wait` | ✅ | `GlobScopeMatcher` | ➖ | Ожидание элемента на странице (rpa_browser). |
| `rpa.citrix.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Вызов Citrix-клиента RPA-процессором. |
| `rpa.crypto.decrypt` | ✅ | `GlobScopeMatcher` | ➖ | Расшифровка данных RPA-процессором. |
| `rpa.crypto.encrypt` | ✅ | `GlobScopeMatcher` | ➖ | Шифрование данных RPA-процессором. |
| `rpa.desktop.automate` | ✅ | `GlobScopeMatcher` | ➖ | Автоматизация desktop-приложений (pyautogui). |
| `rpa.desktop.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Вызов desktop-приложения RPA-процессором. |
| `rpa.directory.scan` | ✅ | `SegmentedGlobMatcher` | ➖ | Сканирование директории с фильтром (DirectoryScan/FilteredDirectoryScan). |
| `rpa.email.extract` | ✅ | `GlobScopeMatcher` | ➖ | Извлечение вложений из письма RPA-процессором. |
| `rpa.email.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение письма по IMAP RPA-процессором. |
| `rpa.email.send` | ✅ | `GlobScopeMatcher` | ➖ | Отправка письма по SMTP RPA-процессором. |
| `rpa.excel.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение XLSX-документа RPA-процессором. |
| `rpa.file.csv.read` | ✅ | `SegmentedGlobMatcher` | ➖ | Чтение CSV-файла RPA-процессором. |
| `rpa.file.csv.write` | ✅ | `SegmentedGlobMatcher` | ➖ | Запись CSV-файла RPA-процессором. |
| `rpa.file.delete` | ✅ | `SegmentedGlobMatcher` | ➖ | Удаление файла RPA-процессором. |
| `rpa.file.list` | ✅ | `SegmentedGlobMatcher` | ➖ | Листинг файлов в директории RPA-процессором. |
| `rpa.file.move` | ✅ | `SegmentedGlobMatcher` | ➖ | Перемещение/переименование файла RPA-процессором. |
| `rpa.file.watch` | ✅ | `SegmentedGlobMatcher` | ➖ | Наблюдение за файловой системой через watchdog RPA-процессором. |
| `rpa.ftp.upload` | ✅ | `GlobScopeMatcher` | ➖ | Выгрузка файла по FTP/SFTP RPA-процессором. |
| `rpa.hash.compute` | ✅ | `GlobScopeMatcher` | ➖ | Вычисление хеша файла/данных RPA-процессором. |
| `rpa.http.request` | ✅ | `GlobScopeMatcher` | ➖ | HTTP-запрос из RPA-процессора. |
| `rpa.image.ocr` | ✅ | `GlobScopeMatcher` | ➖ | Распознавание текста на изображении (OCR). |
| `rpa.image.resize` | ✅ | `GlobScopeMatcher` | ➖ | Изменение размера изображения RPA-процессором. |
| `rpa.keystroke.replay` | ✅ | `GlobScopeMatcher` | ➖ | Воспроизведение клавиатурной последовательности. |
| `rpa.pdf.merge` | ✅ | `GlobScopeMatcher` | ➖ | Объединение PDF-документов RPA-процессором. |
| `rpa.pdf.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение PDF-документа RPA-процессором. |
| `rpa.regex.execute` | ✅ | `GlobScopeMatcher` | ➖ | Применение regex к тексту RPA-процессором. |
| `rpa.shell.exec` | ✅ | `GlobScopeMatcher` | ➖ | Выполнение shell-команды RPA-процессором. |
| `rpa.template.render` | ✅ | `GlobScopeMatcher` | ➖ | Рендеринг шаблона RPA-процессором. |
| `rpa.terminal3270.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Вызов 3270-терминала RPA-процессором. |
| `rpa.word.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение DOCX-документа RPA-процессором. |
| `rpa.word.write` | ✅ | `GlobScopeMatcher` | ➖ | Запись DOCX-документа RPA-процессором. |
| `secret.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение секрета из Vault (vault_secret-процессор). |
| `secrets.read` | ✅ | `URISchemeMatcher` | ➖ | Чтение секрета через SecretsFacade (vault:// / env:// / kms://). |
| `security.waf.check` | ✅ | `GlobScopeMatcher` | ➖ | Проверка запроса WAF-движком. |
| `skill.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Вызов AI skill через SkillRegistry (ADR-NEW-22, S26 W5); scope = skill-id pattern (``credit.score.calculate``, ``credit.*``) или '*' (S27 W3 DSL .skill_invoke()). |
| `storage.presign` | ✅ | `SegmentedGlobMatcher` | ✅ | Выдача presigned-ссылки на объектное хранилище через StorageFacade (key). Ссылка даёт клиенту прямой доступ к бакету, поэтому выдаётся по отдельной capability, а не по storage.read. |
| `storage.read` | ✅ | `SegmentedGlobMatcher` | ✅ | Чтение из объектного хранилища через StorageFacade (key/prefix). |
| `storage.write` | ✅ | `SegmentedGlobMatcher` | ✅ | Запись/удаление в объектное хранилище через StorageFacade (key). |
| `web_search.perplexity.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Веб-поиск через Perplexity. |
| `web_search.tavily.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Веб-поиск через Tavily. |
| `workflow.claim_check.store` | ✅ | `ExactAliasMatcher` | ➖ | Сохранение Temporal workflow payload через WorkflowClaimCheckProcessor (Temporal best practice для больших event-history). |
| `workflow.continue_as_new.request` | ✅ | `ExactAliasMatcher` | ➖ | Запрос Continue-As-New в Temporal workflow (Temporal best practice для долгоживущих executions). |
| `workflow.convert.format` | ✅ | `GlobScopeMatcher` | ➖ | Конвертация формата в workflow-процессоре. |
| `workflow.signal` | ✅ | `GlobScopeMatcher` | ➖ | Сигнал workflow через WorkflowFacade. |
| `workflow.start` | ✅ | `GlobScopeMatcher` | ➖ | Запуск workflow через WorkflowFacade (workflow_id-glob). |
| `workflow.subprocess.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Запуск subprocess в workflow-процессоре. |
