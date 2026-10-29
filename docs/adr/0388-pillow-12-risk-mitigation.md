# ADR-0388 — Pillow 12.x: снижение риска без обновления (Pillow <13 из-за streamlit)

* Статус: Accepted (2026-10-29, wave 17, кластер T3 — «PILLOW 12.x: СНИЖЕНИЕ РИСКА БЕЗ ОБНОВЛЕНИЯ»)
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/core/utils/image_safety.py` (новый — единая безопасная точка загрузки)
  - `src/backend/core/utils/__init__.py` (ре-экспорт хелпера)
  - `src/backend/dsl/engine/processors/rpa/operations/imageresizeprocessor.py`
  - `src/backend/dsl/engine/processors/rpa/operations/imageocrprocessor.py`
  - `src/backend/services/ai/rag/multimodal/image_ingester.py`
  - `src/backend/services/ai/rag/multimodal/embedders.py`
  - `src/backend/services/ai/rag/multimodal/blip2_captioner.py`
  - `tests/unit/core/utils/test_image_safety.py` (новый)
  - `tests/unit/dsl/engine/processors/rpa/operations/test_imageresizeprocessor.py`
  - `tests/unit/dsl/engine/processors/rpa/operations/test_imageocrprocessor.py`
  - `tests/unit/services/ai/rag/multimodal/test_embedders.py`
  - `tests/unit/services/ai/rag/multimodal/test_image_ingester.py`
- **Связан с**:
  - ADR-0385 (A5 — пин Pillow возвращён с обоснованием: `streamlit` требует `pillow<13`)
  - ADR-0374 (CVE-обновления RPA-зависимостей, allowlist advisory)
  - ADR-0290 (`pip-audit` allowlist — временная мера)
  - ADR-0367 (hardening RPA-процессоров: файловый доступ и инъекции)
- **Вне зоны (нужны чужие файлы)**:
  - `pyproject.toml`, `uv.lock` — снятие пина невозможно до обновления `streamlit`
    (см. owner-задачу T3-O1 ниже);
  - `docs/adr/INDEX.md` — по условию кластера не редактируется;
  - `src/backend/infrastructure/**` — Pillow там не импортируется (проверено grep по
    `from PIL|import PIL|Image.open` — совпадений в слое нет), правок не потребовалось;
  - `.security/uv-audit-allowlist.txt` — 59 advisory-ID Pillow остаются до
    обновления Pillow; чистка — часть owner-задачи T3-O1.

## Контекст

`Pillow` зафиксирован в `uv.lock` на **12.3.0** (`rpa`, `rpa-windows`,
`multimodal-rag`). В allowlist `.security/uv-audit-allowlist.txt` — **59
advisory-ID** (41 GHSA + 18 PYSEC), из них **5 CRIT**; все они закрыты в
Pillow 13.0.0.

Обновиться нельзя: `streamlit` — **core-зависимость** (`streamlit>=1.58.0,<2.0.0`,
locked 1.63.0) требует `pillow>=7.1.0,<13`. Резолвер `uv lock` на снятом пине
даёт прямой отказ (ADR-0385):

```
streamlit>=1.59.0,<=1.59.2 depend on pillow>=7.1.0,<13
streamlit>=1.64.0,<=1.66.0 depend on pillow>=7.1.0,<13
→ your project's requirements are unsatisfiable
```

Пин `pillow<13.0.0` возвращён с обоснованием — это осознанно принятый риск.
Большинство CVE Pillow 12.x лежат **в разборе изображений**, поэтому кластер
T3 закрывает не «бумажный» риск, а **экспозицию в коде**: сейчас все пять
мест, где читаются пользовательские изображения, вызывают `Image.open` без
каких-либо ограничений:

| Место | Что читается | Экспозиция до правки |
|---|---|---|
| `rpa/operations/imageresizeprocessor.py` | body пользователя | oversize → декодирование в RAM; битый файл → трассировка PIL внутри шага |
| `rpa/operations/imageocrprocessor.py` | body пользователя | то же + tesseract на «мусорных» кадрах |
| `services/ai/rag/multimodal/image_ingester.py` | файл/bytes из RAG-источника | то же, но ошибка глушилась в `warnings` |
| `services/ai/rag/multimodal/embedders.py` | bytes в CLIP-embedder | то же, ошибка доходила как `ValueError` с текстом PIL |
| `services/ai/rag/multimodal/blip2_captioner.py` | bytes в VLM-captioner | то же |

Остаточные **CVE-классы** (категории, покрываемые и не покрываемые нашими
мерами):

1. **CWE-400 (DoS / resource exhaustion)** — decompression bomb, исчерпание
   памяти/CPU. **Снижается**: лимит числа пикселей + отказ до декодирования.
2. **CWE-787 / CWE-125 (out-of-bounds write/read, heap overflow)** в
   декодерах форматов. **Остаётся** (лечится только Pillow 13): экспозиция
   снижена allowlist'ом форматов и лимитом размера.
3. **CWE-190 (целочисленное переполнение)** в расчёте размеров буферов.
   **Частично**: лимит пикселей ограничивает размер выделяемых буферов.
4. **CWE-416 / CWE-476 (use-after-free, NULL-deref)** в редких ветках
   декодеров. **Остаётся**: это дефекты самого Pillow.
5. **CWE-20 (невалидный ввод: обрезанные/битые файлы)**. **Частично**:
   fail-closed с понятной доменной ошибкой вместо необработанного исключения
   из середины декодера.

## Решение

### 1. Единая безопасная точка загрузки — `core/utils/image_safety.py`

Новый модуль в слое `core` (доступен `dsl`/`services`/`infrastructure` без
новых межслойных нарушений):

* `MAX_IMAGE_PIXELS = 50_000_000` — лимит числа пикселей одного изображения
  (≈7000×7000). Хелпер синхронизирует `PIL.Image.MAX_IMAGE_PIXELS` с этим
  значением, поэтому встроенная защита Pillow срабатывает на нашем пороге, а
  не на дефолтном (89 478 485).
* `ALLOWED_IMAGE_FORMATS` — allowlist растровых форматов
  (`PNG`, `JPEG`, `GIF`, `BMP`, `WEBP`, `TIFF`). SVG и прочие «обёртки»
  (`PDF`, `ICO`, `PSD`, `PPM`, …) отклоняются: векторные форматы и
  контейнеры не нужны для resize/OCR/RAG и расширяют поверхность атаки
  разбора.
* `open_image(data)` — context manager: `Image.open` → перехват
  `DecompressionBombError` **и** `DecompressionBombWarning` (warning
  превращается в ошибку через `warnings.simplefilter("error", ...)`) →
  проверка формата → проверка `width * height` → выдача изображения.
* `UnsafeImageError(ValueError)` — доменная ошибка с понятным текстом
  («image rejected: image too large (…; limit 50000000 pixels)»,
  «image rejected: unsupported image format 'PPM' (allowed: …)»,
  «image rejected: unsupported or corrupted image file»). Наследование от
  `ValueError` сохраняет совместимость с кодом, который ловил `ValueError`.
* Ресурсы: файл и изображение закрываются гарантированно (`finally` в
  context manager'е) — раньше это обеспечивал `with Image.open(...)` в каждом
  из пяти мест (Sprint 83 W3, fix FD-leak).
* Pillow — опциональная зависимость (extras `rpa` / `multimodal-rag`), импорт
  ленивый: `ImportError` пробрасывается как раньше, «Pillow not installed»
  остаётся отдельным сообщением шага.

### 2. Все места загрузки переведены на хелпер

| Файл | Изменение |
|---|---|
| `imageresizeprocessor.py` | `Image.open` → `open_image`; `UnsafeImageError` → `exchange.fail(str(exc))` (понятная ошибка шага); `ImportError` → `exchange.fail("Pillow not installed: …")` |
| `imageocrprocessor.py` | то же; `import pytesseract` вынесен в отдельный `try` (сообщение «pytesseract not installed»); `TesseractNotFoundError` обрабатывается раньше `ImportError` |
| `image_ingester.py` | `Image.open` → `open_image`; `UnsafeImageError` → warning `image_rejected: …` в `metadata["warnings"]`, ingestion **не падает** (остальные `ChunkDoc` доходят до потребителя) |
| `embedders.py` | `Image.open` → `open_image`; `UnsafeImageError` пробрасывается как есть (наследник `ValueError`), `ImportError` → `LazyImportError` (прежний контракт) |
| `blip2_captioner.py` | `Image.open` → `open_image`; `ImportError` → прежний `RuntimeError` («BLIP2 requires Pillow — install [multimodal-rag] extra») |

### 3. Тесты: oversize → понятная ошибка, а не «хира-трассировка»

* `tests/unit/core/utils/test_image_safety.py` (новый, 11 тестов): валидный PNG;
  oversize (100M и 400M пикселей) → `UnsafeImageError` с «too large» и лимитом;
  SVG → отказ; PPM (формат вне allowlist'а) → отказ; мусорные байты → отказ;
  синхронизация `PIL.Image.MAX_IMAGE_PIXELS`; закрытие изображения (в т.ч. при
  исключении в теле `with`).
* `test_imageresizeprocessor.py` / `test_imageocrprocessor.py`: oversize, SVG и
  формат вне allowlist'а → `exchange.fail(...)` с текстом ошибки, `set_out` не
  вызывается.
* `test_embedders.py`: mock `PIL` переведён на **верный контракт** (формат,
  размеры, классы `DecompressionBomb*`) — иначе безопасная проверка формата
  отвергала бы мок; добавлен тест на oversize → `UnsafeImageError`.
* `test_image_ingester.py`: oversize → warning `image_rejected` в metadata,
  `ChunkDoc` создан.

Oversize-изображения в тестах — это PNG **только с заголовком** (IHDR/IDAT/
IEND, пиксели не декодируются): Pillow читает размер на этапе `Image.open`,
поэтому тесты не создают гигабайтные буферы.

### 4. Owner-задача (открытая)

* **T3-O1 — обновить `streamlit`, разрешающий `pillow>=13`, затем снять пин.**
  Владелец: команда frontend/platform (в ADR-0385 зафиксировано 95
  frontend-импортов `streamlit` — миграция вне зоны кластера T3).
  Порядок: (1) обновить `streamlit` до версии с `pillow<14`/без верхней
  границы; (2) снять `pillow<13.0.0` в трёх местах `pyproject.toml`
  (`rpa`, `rpa-windows`, `multimodal-rag`) и поднять до `>=13.0.0`; (3)
  `uv lock`; (4) удалить 59 advisory-ID Pillow из
  `.security/uv-audit-allowlist.txt`; (5) пересмотреть allowlist форматов
  (после 13.0.0 часть парсерных CVE закрыта — ограничение можно ослабить).
  Критерий приёмки: `uv lock` без `pillow<13`; `uv audit --frozen` не содержит
  pillow; `tools/config_audit.py --scope orphans` → 0;
  `tools/check_layers.py --strict` → 41; `tools/check_docstrings.py src
  --max-allowed 0` → exit 0.
* **T3-O2 (опционально)** — если обновление `streamlit` невозможно в
  разумный срок: вынести `MAX_IMAGE_PIXELS` и allowlist форматов в
  настройки профиля (модель в `core/config`) — только вместе с T3-O1, иначе
  появится второй источник правды.

## Альтернативы (отклонённые)

1. **Обновить Pillow до 13.0.0.** Отклонено: `streamlit` (core) требует
   `pillow<13` — lock-файл неразрешим (ADR-0385, проверено `uv lock`).
2. **Только задокументировать риск** (ADR без правок кода). Отклонено: задача
   кластера — снизить экспозицию в коде; документирование без ограничений не
   снижает риск DoS.
3. **Лимит по размеру файла (`len(data)`).** Отклонено: не ограничивает
   «картинку-бомбу» (сжатый PNG в десятки КБ → сотни МБ пикселей) — нужен
   лимит по числу пикселей.
4. **Только глобальный `Image.MAX_IMAGE_PIXELS`, без allowlist форматов.**
   Отклонено: SVG/«обёртки» остались бы доступны (Pillow их и не читает, но
   другие форматы — PPM/ICO/TIFF-контейнеры — дают лишние векторы парсинга).
5. **Свой `Image.open`-обёрткой в каждом из пяти мест.** Отклонено: политика
   разъехалась бы по коду; единый хелпер в `core` — единственная точка правды.
6. **Вынести лимит в конфиг (`settings.*`).** Отклонено: лимит — политика
   безопасности, а не эксплуатируемая настройка; новый config-ключ обязан
   жить в модели `Settings` (правило «ключи только из моделей»), что потянуло
   бы миграцию профилей без выигрыша в безопасности.
7. **Внешняя зависимость-обёртка (`pillow-safe` и т.п.).** Отклонено: новые
   зависимости запрещены, а лимит пикселей/allowlist — это ~40 строк кода.
8. **Проверка размера после декодирования (`img.load()`).** Отклонено: к этому
   моменту буфер уже выделен — DoS не предотвращён. Проверка выполняется по
   заголовку, до декодирования.

## Последствия

* **Позитивные:**
  * единая точка загрузки изображений — новая функция не может обойти
    лимиты «случайно» (все 5 мест переведены);
  * oversize-изображение отклоняется **до** декодирования (экономит RAM/CPU
    и закрывает CWE-400-класс);
  * ошибка шага — односрочная понятная строка (`exchange.fail(...)`), а не
    traceback Pillow с внутренностями `_decompression_bomb_check`;
  * SVG и неподдерживаемые форматы отклоняются явно (allowlist);
  * RAG-ингест не теряет документы: отклонённое изображение даёт warning в
    metadata вместо падения пайплайна.
* **Негативные / breaking:**
  * изображения вне allowlist'а (PPM, ICO, XBM, WMF, …) теперь отклоняются —
    если такой формат использовался в RPA-маршрутах, шаг завершится
    `exchange.fail`; список поддерживаемых форматов: PNG, JPEG, GIF, BMP,
    WEBP, TIFF;
  * `PIL.Image.MAX_IMAGE_PIXELS` теперь равен 50M во всём процессе после
    первого вызова хелпера — код, полагавшийся на дефолт Pillow (89M),
    получит более ранний отказ;
  * сообщение об отсутствии `pytesseract` разделено на два («pytesseract not
    installed» / «Pillow not installed») — текст ошибки изменился;
  * `CLIPEmbedder` для невалидного изображения бросает `UnsafeImageError`
    (подкласс `ValueError`) вместо прежнего `ValueError` с текстом PIL.
* **Не выполнено (вне зоны):**
  * T3-O1 — снятие пина Pillow (блокер `streamlit`, чужой пин и lock-файл);
  * T3-O2 — вынос лимита в настройки профиля (следует за T3-O1);
  * `PIL.Image.MAX_IMAGE_PIXELS` — глобальная настройка процесса: при
    потоковой загрузке изображений `warnings.catch_warnings` меняет глобальное
    состояние warnings на время `Image.open` (потолок: конкурентный поток
    может сбросить фильтр). Основная проверка (счёт пикселей) от этого не
    зависит — она выполняется всегда.

## Проверка

```bash
.venv/bin/python -m pytest \
    tests/unit/core/utils/test_image_safety.py \
    tests/unit/dsl/engine/processors/rpa/operations/test_imageresizeprocessor.py \
    tests/unit/dsl/engine/processors/rpa/operations/test_imageocrprocessor.py \
    tests/unit/services/ai/rag/multimodal/ -q
.venv/bin/python -m ruff check src/backend/core/utils/image_safety.py \
    src/backend/dsl/engine/processors/rpa/operations/ \
    src/backend/services/ai/rag/multimodal/ tests/unit/core/utils/test_image_safety.py
.venv/bin/python tools/config_audit.py --scope orphans      # 0
.venv/bin/python tools/check_layers.py --strict             # 41 (без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
```

## Связи с другими ADR

* **ADR-0385** (A5) — пин Pillow и блокер `streamlit`: этот ADR не отменяет
  пин, а снижает экспозицию до обновления; owner-задача T3-O1 — прямое
  продолжение A5.
* **ADR-0374** — обновления RPA-зависимостей и allowlist advisory: 59
  advisory-ID Pillow живут в том же allowlist'е.
* **ADR-0290** — `pip-audit` allowlist как временная мера: допустимая
  стратегия «принять с риском + снизить экспозицию», а не «закрыть пин».
* **ADR-0367** — hardening RPA-процессоров: fail-closed на понятной ошибке
  вместо трассировки — тот же приём для изображений.
