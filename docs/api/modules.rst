.. _api-modules:

API Reference — Key Modules
============================

Корневая точка входа в API reference. Каждая секция ниже — это ``automodule``,
которая автоматически извлекает docstring'и из исходного кода ``src/backend/dsl/``.
При добавлении новых модулей в DSL — добавляйте секцию здесь.

.. contents:: Содержание
   :local:
   :depth: 2

Builder & Routing
-----------------

.. automodule:: src.backend.dsl.builders.base
   :members:
   :show-inheritance:
   :noindex:

.. _api-exchange:

Message Exchange
----------------

.. automodule:: src.backend.dsl.engine.exchange
   :members:
   :show-inheritance:
   :noindex:

.. _api-pipeline:

Pipeline Orchestration
----------------------

.. automodule:: src.backend.dsl.engine.pipeline
   :members:
   :show-inheritance:
   :noindex:

EIP Patterns
------------

.. automodule:: src.backend.dsl.builders.saga_lra
   :members:
   :show-inheritance:
   :noindex:

.. automodule:: src.backend.dsl.processors.claim_check_processor
   :members:
   :show-inheritance:
   :noindex:

Request-Reply
-------------

.. automodule:: src.backend.dsl.builders.request_reply
   :members:
   :show-inheritance:
   :noindex:

.. automodule:: src.backend.dsl.builders.request_reply_mixin
   :members:
   :show-inheritance:
   :noindex:

IDP Pipeline
------------

.. automodule:: src.backend.dsl.processors.idp_pipeline_processor
   :members:
   :show-inheritance:
   :noindex:

Infrastructure DSL
------------------

.. automodule:: src.backend.dsl.builders.infrastructure_dsl
   :members:
   :show-inheritance:
   :noindex:

Format Converters
-----------------

.. automodule:: src.backend.dsl.builders.converters_mixin
   :members:
   :show-inheritance:
   :noindex:

Deferred Execution
------------------

.. automodule:: src.backend.dsl.builders.deferred_execution_mixin
   :members:
   :show-inheritance:
   :noindex:

Module Index
------------

* :ref:`api-exchange` — ``src.backend.dsl.engine.exchange``
* :ref:`api-pipeline` — ``src.backend.dsl.engine.pipeline``
* Builder base — ``src.backend.dsl.builders.base``
* Saga LRA — ``src.backend.dsl.builders.saga_lra``
* Claim Check — ``src.backend.dsl.processors.claim_check_processor``
* Request-Reply — ``src.backend.dsl.builders.request_reply`` (+ mixin)
* IDP Pipeline — ``src.backend.dsl.processors.idp_pipeline_processor``
* Infrastructure DSL — ``src.backend.dsl.builders.infrastructure_dsl``
* Format Converters mixin — ``src.backend.dsl.builders.converters_mixin``
* Deferred Execution mixin — ``src.backend.dsl.builders.deferred_execution_mixin``
