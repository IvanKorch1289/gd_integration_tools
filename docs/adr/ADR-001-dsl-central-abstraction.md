# ADR-001: DSL `RouteBuilder` как центральная абстракция

* Статус: accepted
* Дата: 2026-04-21
* Фазы: B1 (decompose) и далее все C/D/E/F

## Контекст

`gd_integration_tools` — интеграционная платформа, близкая по духу к
Apache Camel. Исходная реализация `src/dsl/builder.py` содержала
~170 методов в одном классе (1313 LOC). Это:

- затрудняло ревью (god-object);
- мешало IDE/автокомплиту (методы всех доменов вперемешку);
- усложняло генерацию категорийной документации;
- создавало риск «case of missing method» при добавлении новых EIP.

## Решение

1. `RouteBuilder` — остаётся **единственной** точкой сборки route (fluent
   API). Параллельных билдеров не вводится.
2. На первом этапе (B1 phase-1) декомпозиция выполняется через
   миксин-маркеры в `app.dsl.builders`:
   - 11 классов (`CoreMixin`, `EIPMixin`, `TransportMixin`,
     `StreamingMixin`, `AIMixin`, `RPAMixin`, `BankingMixin`,
     `BankingAIMixin`, `StorageMixin`, `SecurityMixin`,
     `ObservabilityMixin`) — все наследуют `RouteBuilder`.
   - Это даёт навигацию по категориям в IDE и документации без риска
     регрессии.
3. B1 phase-2 (follow-up в рамках той же ветки) — физическое разнесение
   реализаций на 11 файлов ≤300 LOC, с `class RouteBuilder(CoreMixin,
   EIPMixin, ...)`. Это требует аккуратной миграции `__init__` и
   общего состояния; выполняется после B2 (split files > 500 LOC).
4. Все новые фичи (C1 Camel EIP, C2 Spring Integration, D1 AI agents,
   E1 utils) добавляются в соответствующий миксин-модуль — никогда не в
   «God object».
5. YAML-loader (`src/dsl/yaml_loader.py`) + линтер (`gdi dsl lint`, E2)
   используют тот же публичный API; никаких отдельных intermediate
   representations.

## Альтернативы

- **Оставить god-object**: отвергнуто.
- **Функциональный DSL без fluent API**: отвергнуто — текущий код уже
  fluent, миграция сломает все DSL-yaml.
- **Composition-based builders (декораторы @provides_http / @provides_eip)**:
  будущая опция; сейчас излишне.

## Последствия

- Все новые миксины/методы добавляются только в `builders/`.
- B1 phase-2 — обязательная follow-up задача (tracked в ROADMAP).
- H1 автоген документации использует mixin-категории как заголовки.
