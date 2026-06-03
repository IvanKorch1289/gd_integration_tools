"""Backward-compat re-export facade for split providers package.

Импортирует все функции из ``_impl.py`` (pre-split monolithic module) для
обеспечения 100% backward compat: 61 import site продолжает работать
без изменений ``from src.backend.core.di.providers import get_X_provider``.

Wave 6.2 (pre-split): один файл providers.py с 114 функциями.
S38 P1.2b: providers.py → providers/_impl.py + providers/__init__.py (re-exports).
S38 P1.2c (next): _impl.py будет разбит на 6 domain файлов (cache/db/http/ai/auth/workflow).
"""

from src.backend.core.di.providers._impl import *  # noqa: F401,F403
from src.backend.core.di.providers._impl import __all__  # noqa: F401 — preserve __all__

# FIX (P1.2b review): __all__ в _impl.py пропустил 4 функции
# (get/set_jwks_cache + get/set_jwt_backend). Явный re-export
# для backward compat с 61 import site.
from src.backend.core.di.providers._impl import (  # noqa: F401
    get_jwks_cache_provider,
    set_jwks_cache_provider,
    get_jwt_backend_provider,
    set_jwt_backend_provider,
)
