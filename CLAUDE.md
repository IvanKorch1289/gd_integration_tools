# CLAUDE.md — gd_integration_tools

## Проект

Проект — интеграционная шина на Python 3.14+ с упором на:
- DSL
- workflow / orchestration
- коннекторы
- трансформации
- developer portal
- безопасные и обратимые изменения

## Что читать сначала

Перед анализом архитектуры, кода, зависимостей и документации:
1. Прочитай `graphify-out/GRAPH_REPORT.md`
2. Если существует `graphify-out/wiki/index.md` — используй его как основной индекс
3. Прочитай `ARCHITECTURE.md`, если он существует
4. Затем читай только точечные документы и исходники по задаче
5. Для связей между сущностями используй `graphify query`, `graphify path`, `graphify explain`

Не читать весь репозиторий целиком без необходимости.

## Приоритет источников

При конфликте источников доверять в таком порядке:
1. исходный код;
2. Graphify (`graphify-out/...`);
3. `ARCHITECTURE.md`;
4. `.claude/rules/...`;
5. `.claude/DECISIONS.md`;
6. `.claude/KNOWN_ISSUES.md`;
7. `.claude/CONTEXT.md`.

## Служебная память Claude

Файлы в `.claude/` используются как служебный слой памяти и управления поведением Claude.
Они не являются пользовательской документацией проекта и не должны храниться в `docs/`.

Если существуют:
- `.claude/CONTEXT.md` — использовать как краткую оперативную сводку;
- `.claude/DECISIONS.md` — использовать как журнал устойчивых решений;
- `.claude/KNOWN_ISSUES.md` — учитывать как список известных ограничений.

## Graphify как основной контекст

Graphify — основной источник структурного знания о проекте.
Используй его:
- для поиска связей между модулями;
- для оценки последствий изменений;
- для поиска импортёров и зависимостей;
- перед любым многофайловым изменением;
- перед ревью и рефакторингом.

После commit граф должен автоматически обновляться.

## Архитектура

```text
entrypoints/ -> services/ -> infrastructure/
     |              |             |
  schemas/      core/di      core/protocols
               core/dsl      core/interfaces
```

## Ограничения слоёв

- `entrypoints` импортирует только `services`, `schemas`
- `services` импортирует только `core`, `schemas`
- `infrastructure` реализует контракты из `core`
- `core` не импортирует код из `src/`

## Обязательный режим работы

Любое изменение файлов выполняется только после точного плана.

Порядок:
1. Определить цель задачи
2. Определить потенциально затронутые модули, импортёры и зависимости
3. Составить точный план
4. Выполнять шаги строго по плану
5. После каждого шага выполнять самопроверку
6. При необходимости отклониться от плана — остановиться и согласовать изменение плана
7. После крупной завершённой задачи выполнить `/compact`

Даже если меняется один файл, учитывать, какие модули его импортируют и что может сломаться.

## Согласование с пользователем

Для новых фич, DSL-расширений, workflow-изменений, новых коннекторов и любых многофайловых задач:
- сначала согласование через AskUserQuestion;
- затем только план;
- затем реализация после подтверждения пользователя.

## Безопасность

Без подтверждения запрещено:
- менять публичные API и сигнатуры;
- удалять или переименовывать файлы, классы, модули;
- добавлять зависимости;
- делать push или release;
- читать `.env`, `secrets/`, `*.pem`, `*.key`, файлы с `secret` или `token` в имени.

Commit разрешён только если пользователь явно попросил сделать commit.

## Внешнее исследование

Сначала использовать внутренний контекст проекта:
- Graphify
- `ARCHITECTURE.md`
- `.claude/DECISIONS.md`
- релевантные исходники

Только если задача требует актуальных внешних данных, использовать web search / web fetch:
- документация библиотек;
- новые паттерны разработки;
- changelog и breaking changes;
- свежие практики интеграции;
- актуальные версии и рекомендации.

Предпочитать:
- официальную документацию;
- GitHub releases / changelog;
- engineering-блоги вендоров.

## Верификация

В проекте не навязывать тесты и не предлагать их по умолчанию.

Использовать минимально достаточный набор проверок из Makefile:
- `make format`
- `make lint`
- `make lint-strict`
- `make type-check`
- `make type-check-strict`
- `make deps-check`
- `make deps-check-strict`
- `make secrets-check`
- `make routes`
- `make actions`
- `make docs`
- `make readiness-check`

Не запускать всё подряд без необходимости.

## Память сессий

После крупной завершённой задачи:
- обновлять `.claude/CONTEXT.md`;
- при необходимости сохранять подробную сводку в `vault/session-YYYY-MM-DD-HHMM-summary.md`.

`vault/` — это архив истории работы.
`.claude/` — это служебная память Claude.

## Подход к токенам и скорости

- Не читать весь репозиторий
- Начинать с Graphify и `ARCHITECTURE.md`
- Использовать узкие запросы с конкретными путями
- Делегировать узкие исследования subagents
- Хранить повторяемые процедуры в skills и rules
- После завершения крупного этапа выполнять `/compact`

## Оркестрация

Главный координатор:
- согласует;
- планирует;
- делегирует side-task’и subagents;
- собирает результаты;
- запускает самопроверку;
- обновляет оперативный контекст после крупных завершённых задач.

## Основные агенты

- `feature-coordinator`
- `code-reviewer`
- `dsl-analyst`
- `runtime-debugger`
- `docs-navigator`
- `verification-runner`
- `integration-contract-reviewer`
- `dead-code-hunter`

## Основные команды

- `/plan <задача>`
- `/map <область>`
- `/trace <симптом>`
- `/verify`
- `/review`
- `/contract-review <цель>`
- `/dead-code`
- `/docs-scan <тема>`
- `/research <тема>`
- `/upgrade-check <библиотека>`
- `/commit-work <описание>`
- `/compact`

## Основные skills

- `plan-execute`
- `codebase-map`
- `verify-change`
- `commit-work`
- `compact-session`
- `feature-development`
- `connector-building`
- `refactoring`
- `research-current-tech`
- `workflow-engineering`

@include .claude/rules/refactoring.md
@include .claude/rules/runtime-debug.md
@include .claude/rules/operating-mode.md
@include .claude/rules/verification-policy.md
@include .claude/rules/commit-policy.md
@include .claude/rules/skill-policy.md
@include .claude/rules/subagent-policy.md
@include .claude/rules/online-research.md
@include .claude/rules/dependency-decision.md
@include .claude/rules/path-policy.md