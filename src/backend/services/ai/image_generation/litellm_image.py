"""LiteLLMImageGenerationService — wrapper над ``litellm.image_generation()``.

Назначение:
    Async-обёртка над синхронным ``litellm.image_generation()`` через
    :func:`asyncio.to_thread`. Поддерживает DALL·E, Stable Diffusion,
    Gemini Imagen и любые модели, экспортируемые LiteLLM.

Интеграция:
    * При наличии :class:`LiteLLMGateway` (S5 K4) переиспользует его
      lazy-import-механику и cost-callbacks через ``_ensure_litellm()``.
    * Cost tracking — best-effort через :class:`AgentMetricsService`
      (``record_cost``) и LiteLLM ``cost_calculator.completion_cost``.

Capability (V11.1): ``image.generate.<provider>``.

Активация: ``feature_flags.voice_image_gen_enabled`` (default-OFF).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

__all__ = ("ImageGenerationUnavailable", "ImageResult", "LiteLLMImageGenerationService")

logger = logging.getLogger(__name__)


class ImageGenerationUnavailable(RuntimeError):
    """LiteLLM не установлен, feature-flag выключен или провайдер недоступен."""


@dataclass(slots=True)
class ImageResult:
    """Результат :meth:`LiteLLMImageGenerationService.generate`.

    Attributes:
        urls: Список URL/data-URI сгенерированных изображений.
        b64_json: Список base64-кодированных PNG (если провайдер
            возвращает inline base64). Параллелен ``urls`` (по индексу).
        revised_prompts: Промпты после автоматической ревизии (DALL·E 3).
        model: Идентификатор использованной модели.
        provider: Имя провайдера (``"openai"``, ``"stability"``, ...).
        size: Размер изображения (например ``"1024x1024"``).
        n: Сколько изображений запрашивалось.
        cost_usd: Оценочная стоимость вызова (из LiteLLM, если доступна).
    """

    urls: list[str] = field(default_factory=list)
    b64_json: list[str] = field(default_factory=list)
    revised_prompts: list[str] = field(default_factory=list)
    model: str = ""
    provider: str = "openai"
    size: str = "1024x1024"
    n: int = 1
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "urls": list(self.urls),
            "b64_json": list(self.b64_json),
            "revised_prompts": list(self.revised_prompts),
            "model": self.model,
            "provider": self.provider,
            "size": self.size,
            "n": self.n,
            "cost_usd": round(self.cost_usd, 6),
        }


class LiteLLMImageGenerationService:
    """Async-wrapper над ``litellm.image_generation()`` (K4 S7).

    Args:
        default_model: Default-модель (``"dall-e-3"``, ``"dall-e-2"``,
            ``"stability/stable-diffusion-3"`` и т.п.). default=``"dall-e-3"``.
        provider: Имя провайдера для capability/metrics (``"openai"``).
        request_timeout: Общий timeout (секунды). default=120.
        cost_tracking: Регистрировать стоимость через AgentMetricsService.
        capability_audit: Опциональный callable
            ``(capability_name, model)`` — вызывается перед каждым
            :meth:`generate` (V11.1 audit-trail).
        enabled: Override feature-flag (для тестов). При None — читается
            из ``feature_flags.voice_image_gen_enabled``.

    Examples:
        >>> svc = LiteLLMImageGenerationService()
        >>> if svc.is_available():
        ...     result = await svc.generate("кот в шапке", size="1024x1024")
        ...     print(result.urls)
    """

    def __init__(
        self,
        *,
        default_model: str = "dall-e-3",
        provider: str = "openai",
        request_timeout: float = 120.0,
        cost_tracking: bool = True,
        capability_audit: Any = None,
        enabled: bool | None = None,
    ) -> None:
        self._default_model = default_model
        self._provider = provider
        self._timeout = request_timeout
        self._cost_tracking = cost_tracking
        self._capability_audit = capability_audit
        self._enabled_override = enabled
        self._litellm: Any = None
        self._metrics: Any = None

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def capability(self) -> str:
        """Capability-имя для V11.1 capability-gate (``image.generate.<provider>``)."""
        return f"image.generate.{self._provider}"

    @property
    def enabled(self) -> bool:
        """True если feature-flag ``voice_image_gen_enabled`` активен."""
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        try:
            from src.backend.core.config.features import feature_flags

            return bool(getattr(feature_flags, "voice_image_gen_enabled", False))
        except Exception as _:  # noqa: BLE001
            return False

    def is_available(self) -> bool:
        """True если установлен ``litellm`` и feature-flag включён."""
        if not self.enabled:
            return False
        try:
            import litellm  # type: ignore[import-not-found]  # noqa: F401

            return True
        except ImportError:
            return False

    def _ensure_litellm(self) -> Any:
        """Lazy-import litellm. При возможности — через :class:`LiteLLMGateway`.

        Lazy-import S5 K4 артефакта (LiteLLMGateway) сохраняет совместимость
        с его cost-callback регистрацией — мы переиспользуем тот же
        ``litellm``-модуль (success_callback регистрируется одной точкой).
        """
        if self._litellm is not None:
            return self._litellm
        if not self.enabled:
            raise ImageGenerationUnavailable(
                "LiteLLMImageGenerationService отключён "
                "(voice_image_gen_enabled=false)."
            )

        # Попытка пройти через LiteLLMGateway для общей cost-callback регистрации.
        try:
            from src.backend.services.ai.gateway import get_litellm_gateway

            gateway = get_litellm_gateway()
            if hasattr(gateway, "_ensure_litellm"):
                self._litellm = gateway._ensure_litellm()
                return self._litellm
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "LiteLLMGateway недоступен, fallback на прямой import: %s", exc
            )

        try:
            import litellm
        except ImportError as exc:
            raise ImageGenerationUnavailable(
                "Пакет 'litellm' не установлен — добавьте extra '[ai-2026]'."
            ) from exc
        self._litellm = litellm
        return litellm

    def _ensure_metrics(self) -> Any:
        """Lazy-load AgentMetricsService (best-effort, не ломает вызов)."""
        if self._metrics is not None:
            return self._metrics if self._metrics is not False else None
        if not self._cost_tracking:
            self._metrics = False
            return None
        try:
            from src.backend.services.ai.metrics import get_agent_metrics_service

            self._metrics = get_agent_metrics_service()
        except Exception as exc:  # noqa: BLE001
            logger.debug("AgentMetricsService недоступен: %s", exc)
            self._metrics = False
        return self._metrics if self._metrics is not False else None

    async def generate(
        self,
        prompt: str,
        *,
        size: str = "1024x1024",
        model: str | None = None,
        n: int = 1,
        response_format: str = "url",
        **kwargs: Any,
    ) -> ImageResult:
        """Генерирует изображение(я) через ``litellm.image_generation()``.

        Args:
            prompt: Текстовый промпт (UTF-8).
            size: Размер (``"256x256"``, ``"512x512"``, ``"1024x1024"``,
                ``"1792x1024"``, ``"1024x1792"`` для DALL·E 3).
            model: Override default-модели. При None — ``self._default_model``.
            n: Количество изображений (1..10; DALL·E 3 — только n=1).
            response_format: ``"url"`` (default) или ``"b64_json"``.
            **kwargs: Дополнительные параметры (``quality``, ``style``,
                ``user``, ...) — передаются в litellm как есть.

        Returns:
            :class:`ImageResult` с urls/b64_json и метаданными.

        Raises:
            ImageGenerationUnavailable: litellm не установлен / flag выключен.
            ValueError: пустой prompt.
        """
        if not prompt or not prompt.strip():
            raise ValueError("LiteLLMImageGenerationService.generate: пустой prompt")

        chosen_model = model or self._default_model

        # Capability-audit hook (V11.1) — best-effort.
        if self._capability_audit is not None:
            try:
                self._capability_audit(self.capability, chosen_model)
            except Exception as exc:  # noqa: BLE001
                logger.debug("capability_audit hook failed: %s", exc)

        litellm = self._ensure_litellm()

        params: dict[str, Any] = {
            "model": chosen_model,
            "prompt": prompt,
            "size": size,
            "n": n,
            "response_format": response_format,
            "timeout": self._timeout,
            **kwargs,
        }

        try:
            response: Any = await asyncio.to_thread(litellm.image_generation, **params)
        except Exception as exc:  # noqa: BLE001
            raise ImageGenerationUnavailable(
                f"litellm.image_generation failed: {exc}"
            ) from exc

        result = self._build_result(response, model=chosen_model, size=size, n=n)
        self._track_cost(result, litellm=litellm)
        return result

    def _build_result(
        self, response: Any, *, model: str, size: str, n: int
    ) -> ImageResult:
        """Нормализует ответ litellm в :class:`ImageResult`."""
        payload: dict[str, Any] = (
            response if isinstance(response, dict) else self._asdict(response)
        )
        data = payload.get("data") or []
        urls: list[str] = []
        b64: list[str] = []
        revised: list[str] = []
        for item in data:
            item_dict = item if isinstance(item, dict) else self._asdict(item)
            if url := item_dict.get("url"):
                urls.append(str(url))
            if b := item_dict.get("b64_json"):
                b64.append(str(b))
            if rp := item_dict.get("revised_prompt"):
                revised.append(str(rp))

        cost_usd = float(payload.get("response_cost") or 0.0)

        return ImageResult(
            urls=urls,
            b64_json=b64,
            revised_prompts=revised,
            model=model,
            provider=self._provider,
            size=size,
            n=n,
            cost_usd=cost_usd,
        )

    @staticmethod
    def _asdict(obj: Any) -> dict[str, Any]:
        """Best-effort превращает litellm pydantic-объект в dict."""
        if hasattr(obj, "model_dump"):
            try:
                return dict(obj.model_dump())
            except Exception as exc:  # noqa: BLE001
                logger.debug("model_dump failed, fallback to __dict__: %s", exc)
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return {}

    def _track_cost(self, result: ImageResult, *, litellm: Any) -> None:
        """Регистрирует стоимость через AgentMetricsService (best-effort)."""
        if not self._cost_tracking:
            return

        cost_usd = result.cost_usd
        if cost_usd <= 0:
            # Попытка оценить через cost_calculator (если доступен).
            try:
                completion_cost = getattr(
                    getattr(litellm, "cost_calculator", None), "completion_cost", None
                )
                if completion_cost is not None:
                    cost_usd = float(
                        completion_cost(
                            model=result.model, prompt_tokens=0, completion_tokens=0
                        )
                    )
                    result.cost_usd = cost_usd
            except Exception as exc:  # noqa: BLE001
                logger.debug("image cost estimate failed: %s", exc)

        if cost_usd <= 0:
            return

        metrics = self._ensure_metrics()
        if metrics is None:
            return
        try:
            metrics.record_cost(
                provider=self._provider, model=result.model, cost_usd=cost_usd
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("record_cost failed: %s", exc)
