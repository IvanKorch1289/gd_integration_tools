# Reference

Technical reference (Diátaxis reference quadrant) — точные контракты,
схемы и каталоги, без пошаговых инструкций.

```{toctree}
:maxdepth: 1

capabilities
schemas/index
```

## Страницы

- [Capability catalog](capabilities.md) — каталог capability (V11 / ADR-044),
  сгенерирован из vocabulary ядра.
- [Schemas](schemas/index.md) — JSON-Schema для `plugin.toml` и
  `route.toml`, а также каталог JSON-Schema DSL-процессоров.

## Схемы процессоров (ADR-0399)

Каталог JSON-Schema всех зарегистрированных DSL-процессоров публикуется
в `docs/reference/schemas/processors/` — по одному `*.schema.json` на
процессор плюс агрегированный `index.json` (перечень `fqn` / `name` /
`namespace` / `file` / `$ref`).

Публикация воспроизводима:

```bash
make schemas   # → tools/dsl_export_schemas.py --output docs/reference/schemas/processors
```

* каталог создаётся экспортёром (`mkdir(parents=True)`) — его presence в
  репозитории не обязателен;
* в CI шаг **мягкий** (`continue-on-error`): публикуемые файлы — артефакт
  публикации, а не блокирующий гейт;
* шаги, переименованные относительно реестра `@processor`
  (`print_pdf` → `rpa_pdf`, `wait_for_selector` → `rpa_wait_for`),
  получают **реестровую** схему, а не сигнатурный каркас — сопоставление
  идёт по классу процессора (ADR-0399);
* LSP-completion строится из того же каталога
  (`src/backend/dsl/builders/step_catalog.py`) — 438 шагов, поэтому
  подсказки редактора и опубликованные схемы не расходятся;
* процессоры реестра `@processor`, не представленные публичным методом
  `RouteBuilder` (5 штук), перечисляются отдельно — линтер сообщает о
  них кодом `PROCESSOR_NOT_YAML_ADDRESSABLE`, если такое имя встретилось
  в YAML.

## Связанные разделы

- [Capability runtime](../explanation/capability_runtime.md) — как
  работает capability-гейт (ADR-044 / ADR-0366 / ADR-0393 / ADR-0400).
- [Workflows](../workflows/index.md) — контракт workflow-подсистемы и
  схема состояний.
- [Owner-задачи и известные ограничения](../roadmap/OWNER_TASKS.md) —
  сводка позиций, требующих владельца.
