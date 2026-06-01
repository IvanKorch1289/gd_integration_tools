"""HTTP-клиенты внешних провайдеров credit_pipeline (scaffold).

TODO Team T3 (Sprint 8+):
* skb.py — SKB-Техно API клиент;
* nbki.py — НБКИ API клиент;
* cbr.py — ЦБ-РФ клиент.

Все клиенты — наследники ``BaseExternalAPIClient`` с per-service timeouts
(R-V15-13) и trafик идёт через ``OutboundHttpClient`` (WAF, R-V15-5).
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
