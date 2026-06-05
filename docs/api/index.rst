.. GD Integration Tools API Reference documentation root file.

GD Integration Tools API Reference
==================================

.. attention::
   Это **авто-сгенерированный** API reference. Не редактируйте его вручную —
   правьте docstring'и в ``src/backend/`` и пересоберите через
   ``./scripts/gen_api_docs.sh`` (или ``make -C docs/api html``).

Назначение
----------

Полный справочник публичного API модулей ``src.backend.dsl.*`` (DSL-интеграция:
route builders, EIP-patterns, оркестрация, процессоры, IDP). Генерируется
Sphinx'ом из docstring'ов в исходном коде при помощи ``sphinx.ext.autodoc``.

Quick start
-----------

1. :doc:`modules` — оглавление всех задокументированных модулей.
2. ``docs/tutorials/`` — практические руководства.
3. ``docs/how-to/`` — рецепты под конкретные задачи.
4. ``docs/explanation/`` — архитектурные решения.
5. ``docs/reference/`` — справочные материалы.

Соглашения
----------

* Стиль docstring'ов — **Google** (``napoleon_google_docstring = True``).
* Python type hints — в описании (``autodoc_typehints = "description"``).
* Имена типов — unqualified (``python_use_unqualified_type_names = True``).
* Недокументированные атрибуты **не включаются** (``undoc-members: False``).

Build layout
------------

::

   docs/api/
   ├── conf.py          ← этот конфиг Sphinx
   ├── index.rst        ← эта страница
   ├── modules.rst      ← корневой toctree с automodule-секциями
   ├── _static/, _templates/ ← пользовательские ассеты
   ├── _apidoc/         ← RST-файлы от sphinx-apidoc (не коммитятся)
   └── _build/          ← HTML-артефакты (не коммитятся)

.. toctree::
   :maxdepth: 2
   :caption: API Reference
   :hidden:

   modules
   autoapi/index

Indices
-------

* :ref:`genindex` — алфавитный указатель.
* :ref:`modindex` — указатель модулей.
* :ref:`search` — полнотекстовый поиск.

AutoAPI (v19)
-------------

Полный **авто-сгенерированный** API reference всех модулей проекта
(``src/backend/dsl/``, ``core``, ``ai``, ``services``, ``infrastructure``,
``entrypoints``, ``testkit``) — в разделе :doc:`autoapi/index`.

Генерация: ``sphinx-autoapi 3.8.0`` (автоматически при
``make -C docs/api html``).
