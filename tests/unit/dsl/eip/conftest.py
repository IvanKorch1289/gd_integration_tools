"""Bootstrap для unit-тестов DSL EIP (Wave 18.U3).

Общий env-bootstrap (ROOT_DIR / LOG_HOST) вынесен в ``tests/unit/conftest.py``.

Ранее здесь жил runtime-патчер Python-2 ``except A, B:`` syntax для
``src/dsl/engine/processors/ai.py``, ``.../eip/windowed_dedup.py`` и
``src/dsl/builder.py``. Синтаксис исправлен в коммите ``b809569``, и
патчер удалён — он создавал второй экземпляр ``src.dsl.builder`` в
``sys.modules`` и ломал тесты процессоров, которые шли в одной сессии
после EIP-тестов (express/entity и пр.).
"""

from __future__ import annotations
