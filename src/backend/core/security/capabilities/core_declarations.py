"""Baseline capability-декларации ядра (Cycle 172, Wave 5; ADR-0416).

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

Изменения ADR-0416 (волна 24, мультироевой аудит)
-------------------------------------------------
Раньше baseline объявлял **77** capability со scope ``"**"`` сразу для
namespace'ов ``core`` / ``system`` / ``ai-agent``. Wildcard-scope означал:
``fs.read``, ``net.outbound``, ``storage.*``, ``rpa.shell.exec`` выдавались
**на любой** запрошенный scope — scope-проверка была фактически отключена.
Проблема видна на живом примере: ``StorageFacade`` в production работает с
plugin ``"system"`` и проверяет ``storage.read`` по ключу объекта; с
``scope="**"`` проверка проходила для **любого** ключа (в т.ч. чужого
тенанта), а ``net.outbound`` — для любого хоста.

Теперь:

* baseline объявляет **явные** scope (:data:`CORE_CAPABILITY_SCOPES`) —
  blanket ``"**"`` в декларациях ядра больше нет;
* resource-scoped capability (scope задаёт вызывающий: путь, хост, ключ,
  алиас БД, namespace кэша, URI секрета) **исключены** из baseline
  (:data:`RESOURCE_SCOPED_CAPABILITIES`) — их объявляет владелец (роут или
  плагин) с конкретным scope, как требуют ADR-0078 / ADR-044;
* «core-baseline» как *fallback-namespace* переехал в runtime-резолвер
  (:mod:`src.backend.core.security.capabilities.runtime_resolver`): он
  открывается **явным** флагом ``dsl_capability_core_baseline_enabled``
  (ADR-0366 §2) и больше не зависит от того, что кто-то объявил
  capability в namespace ``core``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from src.backend.core.security.capabilities.models import CapabilityRef

__all__ = (
    "CORE_CAPABILITIES",
    "CORE_CAPABILITY_SCOPES",
    "RESOURCE_SCOPED_CAPABILITIES",
    "core_capability_refs",
)


# Capability, которые используют core-процессоры DSL.
# Полный набор выведен из ``required_capability: ClassVar[str | None]``
# по всему ``src/backend/dsl/engine/processors`` (Wave 5, аудит
# S3_CACHE_DB_FS_LOGGING_AUDIT_2026-10-22, HIGH-16).
#
# Список **не** изменился по ADR-0416: он отвечает на вопрос «какие
# capability вообще принадлежат ядру» и используется runtime-резолвером
# для выбора fallback-namespace'а ``core``.
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
    # поэтому scope объявления — host-glob.
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


CORE_CAPABILITY_SCOPES: Final[Mapping[str, str]] = {
    # ── Логические capability: scope = идентификатор операции ───────────────
    # Односегментный glob ``"*"`` — соглашение проекта для «любой
    # идентификатор операции» (ср. routes/osint_agent/route.toml:
    # ``ai.invoke`` scope="*"). Многосегментные идентификаторы
    # (skill_id вида ``credit.score.calculate``) требуют явной
    # декларации владельцем — baseline их не выдаёт.
    "agent.run": "*",
    "ai.invoke": "*",
    "ai.memory.read": "*",
    "ai.memory.write": "*",
    "ai.tool.dispatch": "*",
    "mcp.call": "*",
    "skill.invoke": "*",
    "pii.tokenize.reversible": "*",
    "pii.tokenize.reversible.agent_actions": "*",
    "pii.tokenize.reversible.agent_tools": "*",
    # ── Web-search: scope = идентификатор провайдера ───────────────────────
    "web_search.perplexity.invoke": "*",
    "web_search.tavily.invoke": "*",
    # ── Интеграционные операции: scope = идентификатор операции/формата ───
    "data.export": "*",
    "event.publish": "*",
    "llm.stream": "*",
    "security.waf.check": "*",
    "workflow.convert.format": "*",
    "workflow.subprocess.invoke": "*",
    # ── AI-workspace: scope = "workspace.<session_id>" ─────────────────────
    # (core/ai/fs_facade.py:213 — запись артефакта в workspace;
    #  infrastructure/ai/e2b_sandbox.py:86 — запуск кода в sandbox).
    "code.execute": "workspace.*",
    "fs.write": "workspace.*",
}
"""Явные scope baseline-деклараций ядра (ADR-0416).

Все scope — **не** blanket ``"**"``: capability выдаётся либо на
конкретный односегментный идентификатор операции (``"*"``), либо на
конкретное пространство имён (``"workspace.*"``).

Capability, чей scope задаёт **вызывающий** (путь, хост, ключ объекта,
алиас БД, namespace кэша, URI секрета), в baseline отсутствуют — см.
:data:`RESOURCE_SCOPED_CAPABILITIES`.
"""


RESOURCE_SCOPED_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        # Файловая система: scope = путь к файлу/каталогу.
        # (``fs.read`` объявлен отдельно — с явным scope корня репозитория,
        #  см. :func:`_fs_read_scope`.)
        "fs.watch",
        # Объектное хранилище: scope = ключ (или префикс) объекта.
        "storage.read",
        "storage.write",
        "storage.presign",
        # Сеть: scope = host (outbound) / endpoint (inbound).
        "net.inbound",
        "net.outbound",
        # БД: scope = алиас ресурса (ExactAliasMatcher — точное совпадение).
        "db.read",
        "db.write",
        "db.execute_procedure",
        # Кэш: scope = namespace (cache_glob, разделитель «:»).
        "cache.read",
        "cache.write",
        # Секреты: scope = URI/имя секрета (URISchemeMatcher).
        "secret.read",
        # Claim-check / workflow: scope = идентификатор сообщения/workflow.
        "message.claim_check.store",
        "workflow.claim_check.store",
        "workflow.continue_as_new.request",
        # RPA: scope = путь/цель операции (файл, URL, селектор, команда).
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
        "rpa.terminal3270.invoke",
        "rpa.word.read",
        "rpa.word.write",
    }
)
"""Capability, **исключённые** из baseline-деклараций ядра (ADR-0416).

Их scope задаёт вызывающий в момент вызова (путь, host, ключ объекта,
алиас БД, namespace кэша, URI секрета, путь/цель RPA-операции). Статически
выразить такой scope нельзя — раньше для этого использовался blanket
``"**"``, из-за чего scope-проверка была отключена (ADR-0416, дефект 3).

Декларировать их должен **владелец ресурса** — роут
(``[[route.capabilities]] name/scope``) или плагин
(``[[capabilities]] name/scope``), как требуют ADR-0078 / ADR-044.

Исключение — ``fs.read``: AI-слой читает файлы **проекта**, и этот корень
заранее известен, поэтому capability объявлена с явным scope корня
репозитория (см. :func:`_fs_read_scope`).
"""


def _fs_read_scope() -> str:
    """Scope baseline-декларации ``fs.read`` — корень репозитория.

    AI-слой читает файлы **проекта** (V15 R-V15-4): тот же корень
    передаётся в :class:`core.ai.fs_facade.AIFsFacade` как
    ``allowed_read_roots``. Декларация повторяет эту политику на уровне
    capability-гейта: читать проект — можно, читать систему (``/etc``) —
    нельзя.

    Returns:
        Glob пути внутри корня репозитория (например ``/srv/app/**``).

    """
    from src.backend.core.config.config_loader import repo_root

    return f"{repo_root().as_posix()}/**"


def core_capability_refs() -> tuple[CapabilityRef, ...]:
    """CapabilityRef для baseline-декларации ядра.

    Scope **явный** (ADR-0416): blanket ``"**"`` в декларациях ядра
    больше нет — capability с ресурсным scope (путь/хост/ключ/алиас)
    объявляет владелец ресурса, а ядро выдаёт только capability с
    идентификатором операции.

    Returns:
        Набор деклараций для ``gate.declare("core", ...)`` (и для
        остальных namespace'ов платформы — ``system`` / ``ai-agent``).

    """
    refs: list[CapabilityRef] = [
        CapabilityRef(name=name, scope=scope)
        for name, scope in CORE_CAPABILITY_SCOPES.items()
    ]
    refs.append(CapabilityRef(name="fs.read", scope=_fs_read_scope()))
    return tuple(refs)
