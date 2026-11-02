# ADR-0424 — Каталог шаблонов workflow для быстрой разработки (волна 25, кластер P5)

* Статус: Accepted (2026-11-02, волна 25, кластер P5 — «шаблоны workflow для быстрой разработки»)
* Cycle: 185 (волна 25)
* Связан с:
  - ADR-0395 (модель workflow-деклараций; идиома `call_function('module:fn')`,
    build-time резолв `collect_activities(validate=True)`),
  - ADR-0398 (activity-имена = зарегистрированные actions ядра),
  - ADR-0403 (SLA/DLQ-политика workflow; `sla:` в декларации),
  - ADR-0414 (workflow step audit — расширяемость набора шагов),
  - ADR-0100 (прецедент: мёртвый/вводящий в заблуждение код либо удаляется,
    либо чинится),
  - ADR-0284 (матрица межслойных импортов — новых нарушений не добавляем)
* Затрагивает:
  - `src/backend/dsl/workflow/templates/*.workflow.yaml` (10 → 18 шаблонов),
  - `src/backend/dsl/cli/generate.py` (`_build_workflow_template`, команда `workflow`),
  - `src/backend/dsl/workflow/compiler/activity_bridge.py` (внутренние activity —
    резолв build-time),
  - `tests/unit/dsl/workflow/test_workflow_templates_catalog.py` (новый),
  - `tests/unit/dsl/cli/test_generate.py`, `tests/unit/services/workflows/test_template_registry.py`
    (следственные правки вне зоны кластера)

---

## Контекст

Ревью вехи «воркфлоу/DSL» (волна 25) нашло, что каталог шаблонов workflow
(`src/backend/dsl/workflow/templates/`) покрывает только «классические»
сценарии и плохо пригоден как стартовая точка разработки:

1. **Теги — только конвенция в description.** Все 10 шаблонов несли теги
   в строке `Template tags: ...`, а машинночитаемого поля `tags:` не было.
   Фильтры/подписки каталога (Admin UI, MCP-описание tool'а, semantic
   search) работают по `WorkflowDeclaration.tags` — из YAML-файла эти теги
   не доходили.
2. **Идиома `call_function` (ADR-0395) не покрыта ни одним шаблоном.**
   `type: call_function` + `ref: module.path:fn` + `output_key` — основной
   способ адресовать Python-функцию из workflow-DSL; каталог молчал.
3. **Нет шаблонов под расширенные шаги спеки:** `saga.compensate_map` +
   `strict_compensate`, `wait_signal.on_timeout`, `guardrail` +
   `escalate` + `reflect`, `agent_invoke` + `memory_scope`, `sensor`
   (с обязательным `timeout_s`), top-level `sla:`/`default_timeout_s`/
   `default_retry_policy`, `checkpoint` + `continue_as_new`.
4. **CLI-заготовка вводила в заблуждение.** `dsl generate workflow` отдавал
   `{"workflow": {...}}` с route-DSL шагами (`processor`/`params`) и
   `error_handling` — такой файл **не загружается** `WorkflowDeclaration`
   (`extra="forbid"` + обязательный `type` у шага), то есть заготовка
   была нерабочей.
5. **Build-time резолв ломался на внутренних activity.** `agent_invoke`-
   шаг разворачивается мостом во внутреннюю activity `_agent_invoke`,
   которой нет в action-реестре; `collect_activities(validate=True)`
   (ADR-0395/0398) отвечал `UnknownActivityError` — то есть ни один
   workflow с AI-шагом не проходил build-time валидацию.

## Решение

### 1. Каталог шаблонов: теги как поле

Все 10 существующих шаблонов получили top-level поле `tags:` (ADR-0424).
Поле `tags:` — канонический источник (его читает `WorkflowDeclaration`
и descriptor-регистрация, т.е. фильтры каталога). Конвенция
`Template tags: ...` в description оставлена — её читает
`WorkflowTemplateRegistry`; расхождение между двумя источниками
запрещено тестом (`test_template_tags_match_description_convention`),
поэтому дрейф ловится CI, а не пользователем.

### 2. Восемь новых шаблонов

| Шаблон | Закрытый контракт |
|---|---|
| `call_function_ingest` | `type: call_function` + `ref: module.path:fn` + `output_key` |
| `saga_compensation_map` | `compensate_map:` + `strict_compensate: true` |
| `hitl_approval_chain` | `wait_signal` с `on_timeout: raise` и `on_timeout: continue` + `output_key` |
| `guardrail_cost_budget` | `type: guardrail` (`on_exceed: fail` и `warn`) + `escalate` + `reflect` |
| `agent_pipeline` | `type: agent_invoke` + `memory_scope` + `escalate` |
| `sensor_polling` | `type: sensor` с `module:fn`-предикатом и **обязательным** `timeout_s` (D-A8-10) |
| `sla_retry_policy` | полный top-level контракт: `sla:` + `default_timeout_s` + `default_retry_policy` + `tags:` |
| `checkpoint_continue_as_new` | `type: checkpoint` + `type: continue_as_new` |

Имена activity в шаблонах — **зарегистрированные actions ядра**
(ADR-0398), иначе build-time резолв не проходит. Имена-функции
(`module:fn`) — реальные module-level callable репозитория:
`src.backend.core.utils.json_utils:dumps_str` (call_function),
`src.backend.dsl.helpers.banking:validate_inn` (предикат sensor'а).

### 3. Спека валидируется, а не «примерно»

Каждый шаблон проходит `WorkflowDeclaration.model_validate` и
`ActivityBridge.collect_activities(validate=True)` (ADR-0395). Новый
тест `tests/unit/dsl/workflow/test_workflow_templates_catalog.py`
фиксирует три инварианта каталога: валидность по спеке, резолв
activity и наличие тегов. Отдельный тест закрывает требование
«каждый тип шага из шаблонов покрыт сценарием»: для каждого типа шага,
встречающегося в каталоге, в тесте есть сценарий (минимальная валидная
декларация с таким шагом); новый тип шага без сценария роняет тест.

### 4. Внутренние activity резолвятся на build-time

`ActivityBridge.resolve_activity_target()` получил третью цель —
`"internal"` (`INTERNAL_ACTIVITY_NAMES`: `_agent_invoke`,
`_langgraph_checkpoint_get`, `_langgraph_checkpoint_put`). Эти activity
регистрирует сам мост, а не action-реестр, поэтому build-time валидация
должна их принимать. Без этого любой workflow с `agent_invoke`-шагом
(в т.ч. новый шаблон `agent_pipeline`) не проходил бы валидацию.

### 5. CLI-заготовка валидна по спеке

`_build_workflow_template()` теперь возвращает декларацию верхнего уровня
(`name`/`version`/`description`/`tags`/`default_timeout_s`/`steps`) с
шагами `type: call_function` и placeholder-ссылкой `your.module:step_N`:
такой шаг резолвится на build-time (формат `module:fn`) и не требует
зарегистрированного action'а. Команда `workflow` валидирует результат
через `WorkflowDeclaration.model_validate` **до** записи на диск и
печатает подсказку, что placeholder надо заменить. `--steps 0` →
`typer.BadParameter` (в спеке `steps: min_length=1`).

## Альтернативы (отвергнуто)

* **Удалить команду `dsl generate workflow`.** Отвергнуто: заготовка
  полезна, дефект был в её форме, а не в самой команде; форма теперь
  совпадает со спекой и проверяется тестом.
* **Перенести теги из description в `tags:` без конвенции.** Отвергнуто:
  `WorkflowTemplateRegistry` (вне зоны кластера) парсит description;
  молчаливая смена источника сломала бы фильтры каталога. Конвенция
  оставлена, расхождение запрещено тестом.
* **Внутренние activity объявить в action-реестре.** Отвергнуто: это
  расширило бы публичную поверхность actions ради внутренних
  обёрток моста; вместо этого резолв знает о них явно.
* **Шаблоны как Python-конструкторы (`WorkflowBuilder`).** Отвергнуто:
  каталог — YAML (80% декларативно), шаблоны должны оставаться
  файлами, которые пользователь копирует и правит.

## Последствия

### Positive

* Каталог вырос с 10 до 18 шаблонов и покрывает все типы шагов спеки —
  стартовая точка для разработки не требует чтения исходников спеки.
* Теги доступны машинно (фильтры каталога), а не только человеку.
* Build-time резолв работает для AI-workflow (`agent_invoke`).
* CLI-заготовка пригодна к использованию без ручной правки формы.

### Negative

* Дублирование тегов (поле `tags:` + конвенция в description) — защищено
  тестом; при изменении реестра (`WorkflowTemplateRegistry`) конвенцию
  можно будет удалить отдельной задачей (вне зоны кластера).
* `sensor` получает от компилятора пустой payload (`{}`), поэтому
  предикат-заглушка `validate_inn` всегда возвращает `False` — шаблон
  демонстрирует форму, а не готовую проверку готовности.
* Изменены два файла вне зоны кластера
  (`activity_bridge.py` — обязателен для п. 4; `tests/unit/dsl/cli/` и
  `tests/unit/services/workflows/` — тесты, следующие за изменением
  формы заготовки и размера каталога).

## Проверка

* `pytest tests/unit/dsl/workflow -q -p no:randomly` → 310 passed,
  6 skipped (до правок: 284 passed, 6 skipped; новый файл — 26 тестов).
* `pytest tests/unit/dsl tests/unit/dsl/cli tests/unit/services/workflows
  tests/unit/infrastructure/workflow tests/unit/extensions/credit_pipeline
  tests/unit/docs -q -p no:randomly` → 6081 passed, 7 errors (errors —
  пред-существующее order-dependent загрязнение: `sys.modules["temporalio"]`
  в `tests/unit/dsl/workflow/handlers/test_continue_as_new_cycle37.py`
  ломает последующий импорт `temporalio.testing`; воспроизводится и без
  правок кластера).
* Гейты: `ruff check` по изменённым файлам — чисто;
  `tools/config_audit.py --scope orphans` → 0;
  `tools/check_layers.py --strict` → 41 (baseline не изменился);
  `tools/checks/mypy_budget.py` → OK;
  `tools/check_docstrings.py` → 0 missing.

## Связи

* ADR-0395 — модель workflow-деклараций и `call_function`-идиома.
* ADR-0398 — activity-имена = зарегистрированные actions ядра.
* ADR-0403 — SLA/DLQ-политика workflow (`sla:` в декларации).
* `src/backend/dsl/workflow/spec/` — схемы шагов (`WorkflowDeclaration`).
* `src/backend/dsl/workflow/compiler/activity_bridge.py` — build-time резолв
  activity и внутренние activity моста.
* `src/backend/services/workflows/template_registry.py` — реестр шаблонов
  (каталог + semantic search; вне зоны кластера).
