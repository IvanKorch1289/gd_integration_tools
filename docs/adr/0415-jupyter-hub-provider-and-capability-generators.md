# ADR-0415 — Провайдер capability `jupyter.hub` и миграция генераторов capability

* Статус: Accepted (2026-11-02)
* Автор: wave-23, кластер C5
* Затрагивает: `extensions/jupyter_hub/**`, `routes/jupyter_hub_run/**`,
  `src/backend/core/di/providers/jupyter.py`,
  `tools/scaffold_route.py`, `tools/wizards/route_templates.py`,
  `tools/wizards/route_wizard.py`,
  `tests/unit/services/routes/**`, `tests/unit/tools/**`

## Контекст

Owner-задача §12 (`docs/roadmap/OWNER_TASKS.md`) — «`jupyter.hub` — capability
без plugin-провайдера»: capability объявлена в vocabulary
(`core/security/capabilities/vocabulary/defaults/base.py:95`), но **владельца**
в проекте нет. Из-за этого subset-инвариант ADR-044
(`route.capabilities ⊆ union(requires_plugins) ∪ public`) отклонял
`routes/jupyter_hub_run` с `capability_superset` — роут оставался
единственным неработающим из семи (ADR-0405 зафиксировал это как
осознанное least-privilege решение: публичность `jupyter.hub` отдала бы
удалённое выполнение произвольного кода любому роуту без провайдера).

Вторая часть задачи — owner-задача §1 («Осталось владельцу»): генераторы
`tools/scaffold_route.py` и `tools/wizards/route_templates.py` продолжали
выдавать legacy-форму `capabilities = [...]`, объявленную deprecated в
ADR-0405. Проверка показала, что legacy-форма не только расходилась с
каноничной, но и **ломала загрузку**:

* capability без `scope` → `CapabilityRef(scope=None)` → `ValueError` при
  `CapabilityGate.declare` (роут `failed`);
* имена `"ai.llm"` и `"retry.enabled"` **отсутствуют в vocabulary** →
  `CapabilityNotFoundError`;
* в манифесте не было `pipelines` (обязательное поле `RouteManifest`) →
  `RouteManifestError: pipelines Field required` — то есть сгенерированный
  роут **вообще не загружался**;
* `tools/scaffold_route.py` писал `requires_core = ">=15.0,<16"` при версии
  ядра `0.20.0` — роут отбрасывался как несовместимый.

## Решение

1. **Провайдер `jupyter.hub` — расширение `extensions/jupyter_hub/`**
   (ADR-0078: `[[capabilities]]` с отдельными `name`/`scope`):

   ```toml
   [[capabilities]]
   name = "jupyter.hub"
   scope = "run"
   ```

   Capability остаётся **непубличной** — публичность по-прежнему отдала бы
   привилегированную операцию любому роуту (ADR-0405 §Альтернативы, C).
   Владелец один: `extensions/jupyter_hub/plugin.py` — `JupyterHubPlugin`
   с action `jupyter.hub.run`.

2. **Роут запрашивает capability у провайдера** явной связкой:

   ```toml
   [route.requires_plugins]
   jupyter_hub = ">=0.1,<1.0"
   ```

   Инвариант ADR-044 выполняется: `jupyter.hub` покрыта capability плагина,
   `net.outbound`/`audit.write` — публичные.

3. **Runtime-контроль в провайдере.** `run_notebook()` проверяет capability
   через process-wide `CapabilityGate` **до** обращения к Hub (fail-closed):
   без декларации — `CapabilityDeniedError`. Провайдер — единственная
   разрешённая точка входа к операции `jupyter.hub:run`; роуты вызывают его
   DSL-шагом `call_function`
   (`ref: extensions.jupyter_hub.plugin:run_notebook`), а модуль провайдера
   объявлен в его `call_function_modules` (whitelist strict-режима).

4. **Мост core→services.** Расширения по правилам слоёв не могут импортировать
   `services/*`, поэтому оркестратор запуска ноутбуков отдаётся через
   sanctioned composition root — `core/di/providers/jupyter.py`
   (`get_hub_run_provider()`), по образцу уже существующего
   `get_notebook_execution_service_provider()`.

5. **Генераторы переведены на каноничную форму** `[[route.capabilities]]`
   (ADR-0078) в конверте `[route]`, единым генератором
   `tools/wizards/route_templates.py::build_route_toml`; `tools/scaffold_route.py`
   и `tools/wizards/route_wizard.py` делегируют ему (legacy-форма не может
   вернуться в одном из CLI). Capability выбираются **по фактическому
   использованию** сгенерированного DSL (каталог «шаг → capability» —
   `src/backend/dsl/cli/explanation.py::PROCESSOR_SIDE_EFFECTS`):

   | Шаг | Capability | Scope |
   |---|---|---|
   | `audit:` | `audit.write` | `audit:*` (семейство audit-sink'ов) |
   | `http_call` | `net.outbound` | host внешнего сервиса (`api.test`) |
   | `crud_create` | `db.write` | алиас ресурса БД (matcher — `ExactAliasMatcher`) |
   | `llm_call` | `ai.invoke` | не публичная → комментарий-подсказка |

   Scope непубличных capability (`ai.invoke`, `mq.publish`, `fs.write`) в
   манифест **не попадают**: объявить их может только плагин-владелец,
   иначе роут не прошёл бы subset-инвариант ADR-044. Вместо этого в
   манифест пишется комментарий с указанием, что и как добавить.

## Альтернативы

| Вариант | Вердикт | Почему |
|---|---|---|
| **A.** Сделать `jupyter.hub` публичной capability | отклонён | Запуск ноутбука = удалённое выполнение произвольного кода с сервисной учёткой; публичность отдала бы операцию любому роуту (ADR-0405 §Альтернативы C) |
| **B.** Убрать `jupyter.hub` из манифеста роута | отклонён | Роут продолжал бы вызывать Jupyter-адаптер **без** объявленной capability — под-декларация привилегированного доступа (fail-open по направлению «разрешить»). Провайдер честнее: право заявлено и проверяется |
| **C.** Провайдер в `core/security/capabilities/**` (registry capability) | отклонён | ADR-044 не знает понятия «core-провайдер»: subset-инвариант опирается на `requires_plugins` и public-набор. Регистр в core потребовал бы изменения самого инварианта — риск и объём не сопоставимы с задачей |
| **D.** Оставить legacy-форму в генераторах | отклонён | Сгенерированный роут не грузится (`pipelines` отсутствует, имена вне vocabulary) — то есть scaffold/wizard сейчас дают нерабочий артефакт |

## Последствия

### Позитивные

* `routes/jupyter_hub_run` проходит capability-гейт: **7 из 7** роутов
  загружаются (`enabled`), `EXPECTED_UNCOVERED_ROUTES` в гейте ADR-0405
  пуст.
* Capability `jupyter.hub` непубличная, но у неё есть владелец → least
  privilege сохранён, доступ выдаётся только роутам с явным
  `requires_plugins`.
* Привилегированный путь роута идёт через провайдера: capability проверяется
  в рантайме (fail-closed), а payload разбирается корректно (`payload-dict` →
  `notebook_name`/`parameters`), что снимает расхождение calling-convention,
  зафиксированное в docstring `services/jupyter/hub_run_adapter.py`.
* Генераторы дают **рабочий** артефакт: манифест читается
  `load_route_manifest` без legacy-warning, capability проходят гейт,
  `RouteLoader` включает роут.

### Отрицательные / ограничения

* Появился новый плагин в `extensions/` — его нужно публиковать вместе с
  приложением (`v11.plugin_loader_enabled` должен быть включён, иначе
  `requires_plugins` не разрешится и роут будет `skipped` с
  `missing_plugins`).
* `ai.invoke`, `mq.publish`, `fs.write` в сгенерированных манифестах остаются
  комментариями: автор роута обязан завести плагин-владелец. Это осознанный
  компромисс «проходит гейт» против «заявляет честно».
* `db.write` требует точного алиаса ресурса (`ExactAliasMatcher`), поэтому в
  сгенерированном манифесте стоит placeholder `CHANGEME` — его нужно заменить
  вместе с `entity` в DSL.
* Функциональный запуск ноутбуков по-прежнему требует
  `feature_flags.jupyter_hub_enabled = True` (default OFF) и живого Hub.

## Проверка

```bash
# Провайдер + загрузка роутов (11 + 167 тестов)
uv run pytest tests/unit/services/routes/ -q

# Гейт генераторов (51 тест) + регрессии scaffold/wizard
uv run pytest tests/unit/tools/test_route_generators_capabilities.py \
    tests/unit/tools/test_scaffold_route.py \
    tests/unit/tools/test_plugin_and_route_scaffolds.py -q

# Прочие гейты репозитория
uv run ruff check extensions/jupyter_hub tools/scaffold_route.py \
    tools/wizards/route_templates.py tools/wizards/route_wizard.py \
    src/backend/core/di/providers/jupyter.py tests/unit
uv run ruff format --check <те же файлы>
uv run python tools/check_docstrings.py               # 0 missing
uv run python tools/config_audit.py --scope orphans  # 0
uv run python tools/check_layers.py --strict          # 41 (baseline, новых нет)
uv run python tools/checks/mypy_budget.py             # OK (8 при бюджете 30)
uv run python tools/checks/check_plugin_semver.py     # 12 манифестов, 0 невалидных
```

Фактическое состояние на момент принятия ADR: 7 из 7 роутов загружаются
(`enabled`), capability `jupyter.hub` заявлена и проверяется провайдером.

## Связи

* **ADR-0078** — синтаксис `[[capabilities]]` (`name` + `scope`).
* **ADR-0405** — миграция `routes/*/route.toml` на namespace capability
  (этот ADR закрывает её открытую часть — генераторы).
* **ADR-044** — vocabulary, `CapabilityGate`, инвариант
  `route.capabilities ⊆ union(plugins) ∪ public`.
* **ADR-0393** — capability-гейт и least privilege в prod/staging.
* **ADR-0366** — runtime-резолвер namespace (`route_id` роута).
* **ADR-0284 §1.1** — governance: изменение семантики объявления capability
  оформляется отдельным ADR.
* **Owner-задачи** — `docs/roadmap/OWNER_TASKS.md`, п. 1 и п. 12.
