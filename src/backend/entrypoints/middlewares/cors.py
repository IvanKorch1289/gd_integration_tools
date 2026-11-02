"""CORS-middleware с preflight-ответом 204 (ADR-0422).

Зачем
----
Starlette отвечает на CORS-preflight статусом ``200`` и телом ``"OK"``.
Браузеру это не мешает, но:

* ``200`` с телом конфликтует с ожиданием «preflight без тела» (204) —
  часть прокси и CDN кэширует такой ответ как успешный *обычный* ответ;
* тело ``"OK"`` в ответе на preflight — лишние байты в каждом
  cross-origin запросе.

Модуль добавляет тонкий subclass :class:`fastapi.middleware.cors.CORSMiddleware`,
который превращает preflight-ответ в ``204 No Content``, сохраняя все
``Access-Control-*`` заголовки.

Позиция в цепочке
-----------------
CORS обязан быть **вне** auth-слоя: preflight не несёт credentials, и
браузер отправляет его без заголовка ``X-API-Key``. Если CORS стоит внутри
auth-слоя (order 30 при LIFO — самый внутренний), preflight гасится
``APIKeyMiddleware``/``AuthRequiredMiddleware`` с 401 ещё до того, как
браузер получит ``Access-Control-Allow-*``. ADR-0422 поднимает CORS на
верх цепочки (order 950) — см. ``setup_middlewares.build_default_registry``.
"""

from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.responses import Response

__all__ = ("PreflightCORSMiddleware",)

#: Заголовки, которые нельзя переносить из body-ответа в 204-ответ.
_DROPPED_HEADERS = frozenset({"content-length", "content-type"})


class PreflightCORSMiddleware(CORSMiddleware):
    """``CORSMiddleware``, отвечающий на preflight статусом ``204``.

    Поведение наследуется от Starlette без изменений, кроме финального
    ответа на preflight: ``204 No Content`` без тела, но с полным набором
    ``Access-Control-*`` заголовков.
    """

    def preflight_response(self, request_headers: Headers) -> Response:
        """Собрать ответ на preflight-запрос (204 + CORS-заголовки).

        Args:
            request_headers: Заголовки preflight-запроса (``Origin``,
                ``Access-Control-Request-Method``).

        Returns:
            ``204 No Content`` с заголовками, разрешёнными Starlette.
            Для запрещённого origin/method/headers — ``400`` (как у
            Starlette): это информативный ответ, а не отказ авторизации.

        """
        response = super().preflight_response(request_headers)
        if response.status_code != 200:
            # Disallowed CORS origin/method → 400 с пояснением (Starlette).
            return response
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in _DROPPED_HEADERS
        }
        return Response(status_code=204, headers=headers)
