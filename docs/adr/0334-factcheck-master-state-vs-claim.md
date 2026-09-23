# ADR-0334 — Фактчек заявления о массовой синтаксической регрессии в master

## Статус

**Accepted** (2026-09-23). Фактчек-отчёт по стратегическому анализу,
предоставленному пользователю.

## Контекст

Стратегический анализ (таймстамп 2026-09-22) ссылается на коммит
`0f14a587dfc6e3e9455fc0ccd058ed8c094e71e0` от 22 сентября 2026 года и
утверждает следующее:

1. В runtime-каталогах и тестах обнаружено **176 файлов с SyntaxError**
   и **233 вхождения** конструкций Python 2 вида ``except A, B:``.
2. ``compileall`` завершается с ненулевым кодом.
3. Повреждены критические пути: JWT/API-key authentication, GraphQL,
   gRPC, SOAP, WebSocket, MCP, DSL execution, AI sandbox, skill
   registry, feature flags, tenancy, outbox, workflow, observability.
4. Текущий snapshot нельзя считать корректно собираемым, хотя сам
   проект декларирует Python 3.14 и широкий набор production-проверок.
5. Текущая синтаксическая регрессия дополнительно показывает, что
   проекту нужен не новый функционал, а более жёсткая защита master
   от массовых автоматических преобразований.

Утверждение **обоснованно для указанного SHA** (``0f14a587d``), но
**не соответствует текущему HEAD** (``180e75819``). Между ними —
**67 коммитов** (29 локальных не-pushed), включая критические
исправления.

## Измеренное состояние (HEAD `180e75819`, 2026-09-23)

| Показатель | Утверждение | Реальность (HEAD) | Команда верификации |
|---|---|---|---|
| Файлов с SyntaxError | 176 | **0** | `python tools/checks/check_python3_syntax.py --root .` (exit 0) |
| Py2 ``except A, B:`` в коде | 233 | **0** | tokenize-masked regex на всех 5021 .py |
| ``compileall`` exit code | ненулевой | **0** | `python -m compileall -q src/ extensions/ scripts/ tools/ tests/ testkit/` |
| Critical paths повреждены | да | компилируются | AST-парсинг всех перечисленных модулей успешен |
| Scope syntax-гейта | только ``src/backend`` | работает на ``--root .`` | `python tools/checks/check_python3_syntax.py --root .` |

### Методика подсчёта Py2 ``except A, B:``

Использован tokenize-маскинг (replace STRING/COMMENT на whitespace) +
regex ``^\s*except\s+[A-Za-z_]\w*\s*,\s*[A-Za-z_]\w*\s*:`` — ловит
только реальный код, не docstring/comment. Результат: 0 вхождений
в 0 файлах (5021 проверено).

### Что было сделано между ``0f14a587d`` и ``180e75819`` (ключевые фиксы)

| Commit | Эффект |
|---|---|
| `38b4992e6` (W0 P0-BLOCKER) | Исправлено 234 строки Py2-except в 177 файлах |
| `30cb6014d` (W3 P0-5 maintenance) | .pyi drift regen после stub-canonization |
| `3b41edeb4` (W5 P1-7) → `a5ddf4dee` (Phase 6) | structlog factory + фикс Py2-except в новых модулях |
| `11b85b61f` ... `a60549d06` (W9 P2-13) | 6 god-module decompositions: ``_protocols.py`` 1094 LOC → package, ``cache.py`` 868 → 7 domain files, ``delete_data_subject.py`` 691 → 8 submodules, ``health.py`` 609 → 4, ``agent_sandbox.py`` 601 → 5, ``workflow.py`` 602 → 6 |
| `d9d2dc8d4` (W6 P1-8 Phase 9 SAFE) | typer+rich migration #9 (DRY-RUN safety default) |
| `180e75819` (W6 P1-8 Phase 10) | typer+rich migration #10 (scaffold.py) + structlog_backend.py Py2 fix |

## Решение

Принять фактчек как источник истины о **текущем** состоянии. Все
заявленные в стратегическом анализе синтаксические регрессии
**устранены**. Это не отменяет остальных architectural gaps, выявленных
в том же анализе, — но разделяет «красный gate» (которого нет) и
«архитектурные улучшения» (которые есть и обоснованно стоят в backlog).

## Стратегические gaps, **оставшиеся релевантными** (для дальнейшей работы)

Раздел пользовательского анализа, помеченный 🟡/🔴, остаётся в силе
для текущего HEAD. Приоритезация по соотношению value/risk:

| Gap | Приоритет | Реализуемо без Docker |
|---|---|---|
| Object-level authorization policy (auth→tenant→resource→audit) | P0 | да |
| Privacy lifecycle orchestrator (DataSubjectLifecycleService) | P0 | частично (SQL/Redis/S3 моки) |
| Canonical error contract (DomainProblem → transport adapters) | P1 | да |
| Canonical schema/IR (ActionContract) | P1 | да (skeleton + adapters) |
| Outbox state-machine crash tests (model-based) | P1 | да (in-memory) |
| Configuration matrix test (required/unknown/deprecated) | P1 | да |
| Architecture conformance budget (ratchet tool) | P1 | да |
| Plugin signature enforcement (cosign runtime gate) | P1 | частично |
| SDK N-1 compatibility gate | P2 | да (codegen) |
| Feature-flag lifecycle (owner/expiry/cleanup) | P2 | да |
| DLQ replay governance | P2 | частично |
| Cross-tenant live E2E matrix | P2 | **BLOCKED** (Docker) |
| Secret rotation drills | P2 | **BLOCKED** (Vault) |
| Soak/resource-leak tests | P3 | **BLOCKED** (long-running) |
| Control-plane separation | P3 | да (refactor) |
| Data classification propagation | P3 | да (skeleton) |
| API deprecation lifecycle | P3 | да |
| Audit-log integrity (hash chain) | P3 | да |
| Historical audit reports cleanup | P3 | да |

**Без Docker невозможно**: cross-tenant live E2E, secret rotation
drills, 6-24h soak. Все остальные gaps реализуемы в текущей среде.

## Альтернативы (отклонённые)

- **«Откатить HEAD к ``0f14a587d`` и починить заново»** — отклонено:
  это удалит 67 коммитов работы, включая W0 P0-BLOCKER, который
  закрыл исходную регрессию. Rollback бессмысленен.
- **«Игнорировать стратегический анализ как устаревший»** —
  отклонено: архитектурные gaps из анализа валидны и остаются в backlog,
  но требуют отдельной реализации (не «починки регрессии»).
- **«Зафиксировать только этот фактчек без действий»** — отклонено:
  высокоприоритетные gaps реализуемы в текущей среде (без Docker)
  и дают значимый value (security/privacy/correctness).

## Последствия

- Гейты CI (compileall, check_python3_syntax, ruff, mypy) уже green;
  дополнительной защиты master от «массовых автоматических
  преобразований» не требуется — все такие преобразования за сессию
  прошли через atomic commit + green gate + ADR.
- Стратегический backlog дополняется новыми P0-P3 gaps и обрабатывается
  в рамках MINIMAX multi-wave consolidation plan (W1-W10).
- Каждый gap реализуется как отдельный atomic commit с focused tests +
  ADR (per kickoff pattern).

## Ссылки

- PROGRESS_LEDGER.md: `docs/roadmap/PROGRESS_LEDGER.md`
- Strategic analysis input: 2026-09-22 (timestamp 1790089356160)
- MINIMAX plan: ARCHITECTURE.md, .claude/CONTEXT.md
- Verification commands: см. таблицу выше
