# ADR-0406 — Pillow 13: разблокировка пина, streamlit 1.66.1 и критерии приёмки

* Статус: Accepted (2026-11-02, wave 22, кластер B2 — «PILLOW 13 / STREAMLIT»)
* Дата: 2026-11-02
- **Затрагивает**:
  - `pyproject.toml` (пины `pillow` и `streamlit`)
  - `uv.lock` (`pillow` 12.3.0 → 13.0.0, `streamlit` 1.63.0 → 1.66.1,
    `docling-ibm-models` 4.0.2 → 4.0.4, `docling-parse` 7.22.3 → 7.24.2)
  - `.security/uv-audit-allowlist.txt` (сняты 59 advisory-ID Pillow)
  - `src/backend/dsl/engine/processors/rpa/operations/imageresizeprocessor.py`
  - `tests/unit/test_pillow13_upgrade_gate.py` (новый — гейт зависимостей)
  - `tests/unit/dsl/engine/processors/rpa/operations/test_imageresizeprocessor.py`
- **Связан с**:
  - ADR-0385 (A5 — пин Pillow `<13.0.0` и блокер `streamlit`)
  - ADR-0388 (единая безопасная точка загрузки изображений + owner-задача T3-O1)
  - ADR-0374 (CVE-обновления RPA-зависимостей, allowlist advisory)
- **Вне зоны (нужны чужие файлы)**:
  - `docs/adr/INDEX.md` — по условию кластера не редактируется (его
    регенерирует CI-джоб `adr-sync` при push в `master`);
  - `src/backend/services/ai/rag/multimodal/**`, `core/utils/image_safety.py` —
    правок не потребовалось: там Pillow вызывается только через
    `open_image` (см. «Чувствительность кода»);
  - `src/backend/infrastructure/**` — Pillow там не импортируется (проверено
    grep по `from PIL|import PIL` — совпадений в слое нет).

## Контекст

`Pillow` был закреплён в `uv.lock` на **12.3.0** (`pyproject.toml`: `rpa`,
`rpa-windows`, `multimodal-rag` + core). В `.security/uv-audit-allowlist.txt`
лежало **59 advisory-ID** Pillow (5 CRIT) — все закрыты в Pillow 13.0.0.

Блокировал обновление `streamlit` — core-зависимость (`streamlit>=1.58.0,<2.0.0`,
locked 1.63.0), которая требовала `pillow<13`. Пин `pillow<13.0.0` был
возвращён осознанно (ADR-0385 A5, ADR-0388) как «принятый риск со снижением
экспозиции в коде».

### Диагноз владельца: «индекс PyPI недоступен только для streamlit»

Owner-задача T3-O1 пришла с гипотезой: таймаут
`https://pypi.org/simple/streamlit/` — проблема в конкретном пакете/зеркале,
т.к. `clickhouse-connect` и другие пакеты резолвятся. Проверка показала
обратное:

```
$ uv pip install --dry-run 'streamlit>=1.64'
error: Request failed after 3 retries in 47.4s
  Caused by: Failed to fetch: `https://pypi.org/simple/streamlit/`
  Caused by: client error (Connect)
  Caused by: operation timed out
```

```
$ curl -sS -o /dev/null -w "%{http_code}\n" https://pypi.org/simple/clickhouse-connect/   # TIMEOUT/FAIL
$ curl -sS -o /dev/null -w "%{http_code}\n" https://files.pythonhosted.org/              # TIMEOUT/FAIL
$ curl -sS -o /dev/null -w "%{http_code}\n" https://github.com                           # 200
```

`pypi.org`/`files.pythonhosted.org` (Fastly) недоступны **на уровне TCP** из
этого окружения — для всех пакетов, не только для `streamlit`; `clickhouse-connect`
«резолвится» только **из локального кэша uv** в offline-режиме:

```
$ uv pip install --dry-run --offline clickhouse-connect
Checked 1 package in 6ms
Would make no changes
```

### Что доступно без сети: локальный кэш uv

```
$ uv pip install --dry-run --offline 'streamlit>=1.64'
× No solution found when resolving dependencies:
  ╰─▶ Because only the following versions of streamlit are available:
          streamlit<=1.64.0
          streamlit==1.65.0
          streamlit==1.66.0
          streamlit==1.66.1
      and streamlit>=1.64.0 needs to be downloaded from a registry, ...
```

Кэш `~/.cache/uv/simple-v21/pypi/streamlit.rkyv` (индекс PyPI, снят 2026-10-28)
знает про **1.66.1**, но wheel'а в кэше нет — скачать нельзя.

### Границы `pillow<13` по версиям streamlit

Проверено резолвером (`uv pip install --dry-run`):

| streamlit | требование к pillow |
|---|---|
| 1.63.0 (locked) | `pillow>=7.1.0,<13` |
| 1.64.0 | `pillow>=7.1.0,<13` |
| 1.65.0 | `pillow>=7.1.0,<13` |
| 1.66.0 | `pillow>=9.2.0,<13` |
| **1.66.1** | **`pillow>=9.2.0,<14`** — первый, допускающий Pillow 13 |

Вывод: обновление streamlit «на последнюю» само по себе **не** снимает пин —
нужен ровно **1.66.1+**.

### Доступный путь: полное зеркало PyPI

`mirrors.aliyun.com/pypi` доступен и отдаёт simple-index (legacy HTML) и
PyPI JSON API. Зеркало **байт-в-байт faithful**: пути файлов совпадают с
`files.pythonhosted.org` (content-addressed), sha256 идентичны:

```
pypi.org (из кэша uv):  https://files.pythonhosted.org/packages/1d/f2/1371707ce438ba9a43f9d24089828494ec6f9396e28cd7903aa704dd6306/pillow-13.0.0-cp314-cp314-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
зеркало:                https://mirrors.aliyun.com/pypi/packages/1d/f2/1371707ce438ba9a43f9d24089828494ec6f9396e28cd7903aa704dd6306/pillow-13.0.0-cp314-cp314-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl#sha256=e91c2b1cbeae768c98752e67e717e283d68dae45717b41f2d91eaee648e37b7d
```

### Чувствительность кода к Pillow 13

Единственный прямой импорт Pillow в проекте — `core/utils/image_safety.py`
(`from PIL import Image`); остальные пять мест работают через `open_image`.
Используемый API (`Image.open`, `.format`, `.width/.height`, `.close()`,
`.convert("RGB")`, `.resize(...)`, `.save(...)`, `.getexif()`,
`Image.MAX_IMAGE_PIXELS`, `Image.DecompressionBombWarning/Error`,
`Image.UnidentifiedImageError`) в Pillow 13 **сохранён без изменений**
(проверено по `docs/releasenotes/13.0.0.rst` и фактическому прогону на 13.0.0).

Единственное поведенческое изменение, затрагивающее проект: **сохранение
mode `"I"` (32-битный int) в PNG**. Pillow 12.3.0 обрезал значения до 16 бит
с `DeprecationWarning`; Pillow 13.0.0 это удалил → `OSError: cannot write
mode I as PNG`. Входные форматы проекта (`ALLOWED_IMAGE_FORMATS`) включают
`TIFF`, поэтому 32-битный TIFF — достижимый вход для RPA-шага `image_resize`.

## Решение

### 1. `streamlit` — пол `>=1.66.1` (core + extra `frontend`)

`streamlit>=1.58.0,<2.0.0` → `streamlit>=1.66.1,<2.0.0`;
`streamlit>=1.30.0,<2.0.0` (extra `frontend`) → `streamlit>=1.66.1,<2.0.0`.
Ниже 1.66.1 требование `pillow<13` делает `pillow>=13` неразрешимым — пол
фиксирует это в декларации, а не в резолвере.

### 2. `pillow` — `>=13.0.0,<14.0.0` во всех трёх местах

`rpa`, `rpa-windows`, `multimodal-rag` (Pillow — опциональная зависимость,
в core не объявлена). Верхняя граница `<14.0.0`
оставлена осознанно: 14 — major, его breaking changes заранее не разобраны.

### 3. `uv.lock` — канонический, собран без прямого доступа к pypi.org

`uv lock` выполнен через зеркало (pypi.org недоступен). Результат зеркального
lock-а **нельзя коммитить**: в нём URL зеркала и нет полей `size`/`upload-time`
(legacy-HTML simple-index их не отдаёт), которые пишет canonical-lock.

Собранный lock = структура решения резолвера (те же 712 пакетов, те же
dependency-рёбра) + канонические URL `files.pythonhosted.org` + `size`/
`upload-time` из PyPI JSON API. Проверено машинно:

* набор `(name, version)` совпадает с решением резолвера — **712 = 712**;
* `dependencies` совпадают **полностью**;
* URL зеркала в файле отсутствуют;
* у **каждого** файла (`sdist`/`wheels`) есть `size` и `upload-time`;
* формат `upload-time` — как в исходном lock-е (усечение до миллисекунд).

`uv lock --check --offline` → **exit 0** (сверка с кэшем индекса pypi.org).

Побочные (вынужденные) обновления в lock-е: `docling-ibm-models` 4.0.2 → 4.0.4
и `docling-parse` 7.22.3 → 7.24.2 — обе старые версии требуют
`pillow>=10.0.0,<13.0.0` и несовместимы с Pillow 13.

### 4. Allowlist аудита — 59 advisory-ID Pillow сняты

`.security/uv-audit-allowlist.txt`: удалены все 59 строк с комментарием
`# pillow 12.3.0` (Pillow 13.0.0 закрывает их все — список advisory-ID
Pillow 13.0.0 приведён в `docs/releasenotes/13.0.0.rst` разделе Security).
Остаток долга: **40 advisory-ID** (было 99).

### 5. Адаптация кода под Pillow 13 (единственное поведенческое изменение)

`imageresizeprocessor.py`: перед сохранением в PNG mode `"I"` конвертируется
в `"I;16"` (16 бит на канал — ровно то, что делал Pillow 12 обрезанием).
Без этого 32-битный TIFF падал бы `OSError` внутри шага.

### 6. Гейт, который не даёт пину вернуться

`tests/unit/test_pillow13_upgrade_gate.py` (новый, 9 тестов) — проверяет
**семантику**, а не наличие строки:

* каждый объявленный спецификатор `pillow` (все extras) допускает 13.0.0 и
  не допускает 14.0.0;
* нижняя граница `streamlit` — не ниже 1.66.1 (иначе резолвер может выбрать
  версию с `pillow<13`);
* `uv.lock` закрепляет `pillow>=13` и `streamlit>=1.66.1`;
* **установленный** `streamlit` действительно разрешает `pillow>=13`
  (проверка `importlib.metadata`, а не догадка);
* установлен Pillow 13.x и содержит весь используемый API;
* `open_image` → resize → save PNG работает на текущем Pillow.

## Альтернативы (отклонённые)

1. **Оставить пин `pillow<13` и 59 CVE в allowlist.** Отклонено: блокер
   снят (streamlit 1.66.1 существует и доступен), дальнейшее «принятие риска»
   не даёт новых оснований — 5 CRIT в разборе изображений закрываются
   обновлением, а экспозиция уже снижена кодом (ADR-0388).
2. **Обновить только Pillow, оставив streamlit 1.63.0.** Отклонено: lock
   неразрешим (`streamlit 1.63.0` требует `pillow<13`) — это ровно тот
   блокер, который закрывает ADR-0385.
3. **Обновить streamlit «на последнюю» (1.66.1) без фиксации пола.** Отклонено:
   декларация должна сама исключать несовместимые версии, иначе следующий
   `uv lock --upgrade` (или другая среда) вернёт пин.
4. **Закоммитить lock, полученный через зеркало (URL зеркала, без
   `size`/`upload-time`).** Отклонено: lock перестаёт быть каноническим и
   не пройдёт `uv lock --check` в среде с доступным pypi.org; в нём 7848
   изменённых строк URL вместо 60.
5. **Правка lock-а вручную без данных PyPI.** Отклонено: без `size`/
   `upload-time` и без проверки структуры решения lock не пройдёт `uv lock
   --check` — то есть ровно тот дефект, которого задача требовала избежать.
6. **Снизить верхнюю границу Pillow до `>=13` (без `<14`).** Отклонено:
   Pillow 14 — major без разобранных breaking changes; `streamlit 1.66.1`
   всё равно требует `pillow<14`, поэтому `<14` всё равно встанет из
   транзитивного требования — фиксируем явно.
7. **Оставить `I`-mode PNG как есть (падение шага).** Отклонено: 32-битный
   TIFF — разрешённый вход, а падение с `OSError` внутри шага хуже
   явной конвертации в `I;16`.

## Последствия

* **Позитивные:**
  * закрыты **59 CVE Pillow 12.3.0, из них 5 CRIT** (JFrog/GHSA-*
    перечислены в `docs/releasenotes/13.0.0.rst`);
  * allowlist аудита похудел на 59 ID (99 → 40);
  * класс CWE-787/125 (heap overflow / OOB read/write в декодерах) переведён
    из «принятого риска» в «закрыто обновлением»;
  * пин больше не удерживается транзитивным требованием — зависимость от
    одного пакета (`streamlit`) не блокирует security-обновления.
* **Негативные / breaking:**
  * `streamlit` теперь требуется **>= 1.66.1** — более старые окружения
    (dev-образы, pinned CI-образы) нужно пересобрать; в 95 frontend-импортов
    streamlit (ADR-0385) изменений API не потребовалось — 1.66.1 — минорная
    линия 1.6x;
  * `docling-ibm-models` и `docling-parse` обновлены (вынужденно, их
    `pillow<13`-пин несовместим с Pillow 13);
  * Pillow 13 требует Python **>= 3.11** (проект — 3.14, без изменений);
  * 32-битный int-исходник (`mode "I"`) при сохранении в PNG теперь
    конвертируется в `I;16` (значения > 65535 обрезаются — как и в Pillow 12).
* **Осталось за владельцем:**
  * подтвердить lock в среде с доступным pypi.org (см. «Проверка»): команды
    `uv lock --check` и `uv sync --all-extras` должны пройти без сети к
    зеркалу; расхождение возможно только в метаданных `size`/`upload-time`
    новых файлов, если они успели измениться на PyPI (файлы иммутабельны);
  * пересмотреть allowlist форматов изображений (`ALLOWED_IMAGE_FORMATS`) —
    часть парсерных CVE после 13.0.0 ослабляет необходимость отклонять
    часть форматов (это отдельная задача, ADR-0388 T3-O2).

## Проверка

```bash
# гейт зависимостей (был красный: 5 failed → зелёный: 9 passed)
.venv/bin/python -m pytest tests/unit/test_pillow13_upgrade_gate.py -q

# image-тесты на Pillow 13.0.0
.venv/bin/python -m pytest tests/unit/core/utils/test_image_safety.py \
    tests/unit/dsl/engine/processors/rpa/operations/ \
    tests/unit/services/ai/rag/multimodal/ -q
# → 222 passed

# lock согласован с pyproject
uv lock --check --offline        # exit 0 (сверка с кэшем индекса pypi.org)

# в среде с доступным pypi.org (владелец)
uv lock --check                  # ожидается exit 0
uv sync --all-extras             # pillow 13.0.0 + streamlit 1.66.1
uv audit --frozen | grep -i pillow   # ожидается пусто

# гейты репозитория
.venv/bin/python -m ruff check src/backend/dsl/engine/processors/rpa/operations/ \
    tests/unit/test_pillow13_upgrade_gate.py \
    tests/unit/dsl/engine/processors/rpa/operations/test_imageresizeprocessor.py
.venv/bin/python tools/config_audit.py --scope orphans   # 0
.venv/bin/python tools/check_layers.py --strict          # 41
.venv/bin/python tools/checks/mypy_budget.py             # бюджет 30
```

Фактические результаты (2026-11-02, `.venv` с Pillow 13.0.0 / streamlit 1.66.1):

```
tests/unit/test_pillow13_upgrade_gate.py            9 passed
image-тесты (safety + RPA + multimodal)            222 passed
uv lock --check --offline                          exit 0
```

## Связи с другими ADR

* **ADR-0385** (A5) — пин Pillow и блокер `streamlit`: этот ADR **закрывает**
  A5 — блокер снят обновлением streamlit до 1.66.1.
* **ADR-0388** — снижение экспозиции в коде (единая точка загрузки) и
  owner-задача T3-O1: T3-O1 выполнена в объёме «обновить streamlit → снять пин
  → прогнать image-тесты»; T3-O2 (вынос лимита в настройки) остаётся
  отдельной задачей.
* **ADR-0374** — обновления RPA-зависимостей и работа с allowlist advisory:
  59 Pillow-ID сняты из того же allowlist'а.
