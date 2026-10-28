"""Baseline capability-декларации ядра (Cycle 172, Wave 5).

Зачем этот модуль
-----------------
Capability-гейт в проекте был **разорван на несколько экземпляров**:

* ``plugin_loader`` создавал свой ``CapabilityGate()`` и декларировал
  в него capability роутов;
* ``CapabilityFacade.gate`` создавал **другой** ``CapabilityGate()``;
* ``providers/ai.py`` — **третий**;
* ``agent_dsl`` импортировал ``get_capability_gate()``, которого
  **не существовало** → ``ImportError`` → ``gate=None`` → проверка
  capability **молча пропускалась** (fail-open).

Итог: декларации роутов не были видны runtime-проверкам, а
``BaseProcessor.auth_check`` (41 процессор) и ``@require_capability``
(16 коннекторов) падали с ``TypeError`` внутри
``AuthorizationFacade.check()`` → blanket-deny.

Здесь собрана **одна** baseline-декларация ядра: capability, которые
используют core-процессоры DSL. Она живёт в process-wide singleton
``get_capability_gate()``, поэтому одинаково видна:

* runtime-проверке ``BaseProcessor.auth_check`` (plugin ``"core"``);
* ``agent_dsl``-процессорам (plugin ``"core"``);
* ``CapabilityFacade.check`` — через общий гейт;
* loader'ам роутов — они добавляют свои декларации в тот же гейт.

Политика доступа к capability остаётся fail-closed: capability,
которую никто не задекларировал, по-прежнему отклоняется.
"""

from __future__ import annotations

from src.backend.core.security.capabilities.models import CapabilityRef

__all__ = ("CORE_CAPABILITIES", "core_capability_refs")


# Capability, которые используют core-процессоры DSL.
# Полный набор выведен из ``required_capability: ClassVar[str | None]``
# по всему ``src/backend/dsl/engine/processors`` (Wave 5, аудит
# S3_CACHE_DB_FS_LOGGING_AUDIT_2026-10-22, HIGH-16).
CORE_CAPABILITIES: tuple[str, ...] = (
    # agent_dsl (BaseAIProcessor)
    "agent.run",
    "ai.invoke",
    "ai.memory.read",
    "ai.memory.write",
    "ai.tool.dispatch",
    "mcp.call",
    "pii.tokenize.reversible",
    # Per-instance capability AgentDictPIIMaskProcessor (tool/action режимы)
    "pii.tokenize.reversible.agent_actions",
    "pii.tokenize.reversible.agent_tools",
    "skill.invoke",
    # S3 / объектное хранилище (Cycle 172, Wave 7a).
    #
    # StorageFacade в production работает с plugin="system", а DSL-шаги
    # S3 — с plugin=route_id. Пока capability не объявлены ни для
    # "core", ни для "system", включение реального capability-gate
    # (регистрация CapabilityGate в svcs_registry) превратило бы
    # работающий S3 в blanket-deny.
    "storage.read",
    "storage.write",
    # Presigned-ссылка (Wave 13, Q6) — отдельная capability: ссылка даёт
    # клиенту прямой доступ к бакету, поэтому выдаётся не по storage.read.
    "storage.presign",
    # Кэш и внешняя БД — сервисные фасады, которые в production
    # получают capability_check (service_setup._register_cache_facade /
    # _register_external_database_facade, plugin="system").
    "cache.read",
    "cache.write",
    "db.read",
    "db.write",
    "db.execute_procedure",
    # net.* — outbound HTTP через OutboundHttpClient, который в
    # production подключается с plugin="core"
    # (plugins/composition/waf_setup.py:114). Проверка идёт по host,
    # поэтому scope объявления — "**".
    "net.inbound",
    "net.outbound",
    # Базовые capability ядра (fs/sandbox), которые проверяет
    # AI-слой (core/ai/fs_facade.py:112 — "fs.read";
    # infrastructure/ai/e2b_sandbox.py — code.execute).
    # ``skill.invoke`` уже в agent_dsl-сегменте выше — дубликат запрещён
    # (``declare`` бросает ValueError на повтор).
    "fs.read",
    "fs.write",
    "code.execute",
    # BaseProcessor
    "data.export",
    "event.publish",
    "llm.stream",
    "message.claim_check.store",
    "security.waf.check",
    "secret.read",
    "web_search.perplexity.invoke",
    "web_search.tavily.invoke",
    "workflow.claim_check.store",
    "workflow.continue_as_new.request",
    "workflow.convert.format",
    "workflow.subprocess.invoke",
    # RPA
    "rpa.terminal3270.invoke",
    "rpa.ai.decide",
    "rpa.appium.invoke",
    "rpa.archive.execute",
    "rpa.browser.click",
    "rpa.browser.extract",
    "rpa.browser.fill",
    "rpa.browser.launch",
    "rpa.browser.navigate",
    "rpa.browser.pdf",
    "rpa.browser.screenshot",
    "rpa.browser.wait",
    "rpa.citrix.invoke",
    "rpa.crypto.decrypt",
    "rpa.crypto.encrypt",
    "rpa.desktop.automate",
    "rpa.desktop.invoke",
    "rpa.directory.scan",
    "rpa.email.extract",
    "rpa.email.read",
    "rpa.email.send",
    "rpa.excel.read",
    "rpa.file.csv.read",
    "rpa.file.csv.write",
    "rpa.file.delete",
    "rpa.file.list",
    "rpa.file.move",
    "rpa.file.watch",
    "rpa.ftp.upload",
    "rpa.hash.compute",
    "rpa.http.request",
    "rpa.image.ocr",
    "rpa.image.resize",
    "rpa.keystroke.replay",
    "rpa.pdf.merge",
    "rpa.pdf.read",
    "rpa.regex.execute",
    "rpa.shell.exec",
    "rpa.template.render",
    "rpa.word.read",
    "rpa.word.write",
    # Файловая система (core-процессор FileWatchProcessor)
    "fs.watch",
)


def core_capability_refs() -> tuple[CapabilityRef, ...]:
    """CapabilityRef для baseline-декларации ядра.

    Scope ``"**"`` — «любой scope»: конкретный scope вычисляет
    процессор (``_capability_scope``), а для capability с
    ``scope_required=False`` scope не проверяется вовсе.

    Returns:
        Набор деклараций для ``gate.declare("core", ...)``.
    """
    return tuple(CapabilityRef(name=name, scope="**") for name in CORE_CAPABILITIES)
