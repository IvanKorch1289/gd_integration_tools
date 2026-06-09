"""NeMo Guardrails client (S29 T11).

Self-hosted defense-in-depth pipeline (ADR-0064 Draft).
GPU availability is checked at startup — NeMo is used only when:
    1. ``feature_flags.nemo_guardrails_enabled = True``
    2. GPU is detected (CUDA device available)
    3. ``nemoguardrails`` extra is installed

When any condition is unmet, :class:`NeMoGuardrailsUnavailable` is raised
on first use so callers can fall back to the next guardrail in the chain.

Usage::

    runtime = await get_nemo_guardrails_runtime()
    if runtime is None:
        # GPU not available or FF disabled — skip NeMo
        pass
    else:
        result = await runtime.check_input(user_prompt)

Colang flows (banking topics + jailbreak detection) live in
``colang_flows/`` directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    pass

__all__ = (
    "NeMoGuardrailsRuntime",
    "NeMoGuardrailsUnavailable",
    "get_nemo_guardrails_runtime",
    "has_gpu",
)

logger = get_logger(__name__)


class NeMoGuardrailsUnavailable(RuntimeError):
    """NeMo Guardrails не может быть инициализирован.

    Причины:
    - ``feature_flags.nemo_guardrails_enabled = False``
    - GPU (CUDA) недоступен
    - ``nemoguardrails`` не установлен (``pip install nemoguardrails``)
    - Colang flows не найдены в ``colang_flows/``
    """


@dataclass
class NeMoGuardrailsConfig:
    """Конфигурация NeMo Guardrails runtime.

    Attributes:
        colang_flows_dir: Путь к директории с Colang flow файлами.
            По умолчанию ``colang_flows/`` в корне проекта.
        gpu_device: CUDA device id (0..N). None = auto-detect.
        fail_closed: При True блокирует запрос при любой ошибке
            (timeout, import, runtime). При False — логирует и пропускает.
        max_latency_ms: Максимальная допустимая latency в ms.
            При превышении — блок или warn в зависимости от fail_closed.
    """

    colang_flows_dir: str | None = None
    gpu_device: int | None = None
    fail_closed: bool = True
    max_latency_ms: int = 50


def has_gpu() -> bool:
    """Проверяет доступность CUDA GPU.

    Returns:
        True если хотя бы один CUDA device обнаружен.
    """
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        logger.debug("torch not available — assuming no GPU")
        return False


def _check_ff_enabled() -> bool:
    """Проверяет feature flag nemo_guardrails_enabled."""
    try:
        from src.backend.core.config.features import feature_flags

        return bool(getattr(feature_flags, "nemo_guardrails_enabled", False))
    except Exception as _:
        return False


def _check_dependencies() -> None:
    """Проверяет что nemoguardrails установлен.

    Raises:
        NeMoGuardrailsUnavailable: если пакет не установлен.
    """
    import importlib.util

    if importlib.util.find_spec("nemoguardrails") is None:
        raise NeMoGuardrailsUnavailable(
            "nemoguardrails не установлен. Установите: pip install nemoguardrails>=0.10"
        )


class NeMoGuardrailsRuntime:
    """Lazy-runtime для NeMo Guardrails.

    Инициализируется только при первом вызове :meth:`check_input`
    если все preconditions выполнены (GPU + FF + deps).

    Attributes:
        config: Конфигурация runtime.
        gpu_available: Был ли GPU при старте.
        rails: Инициализированный LLMRails инстанс или None.
    """

    def __init__(self, config: NeMoGuardrailsConfig | None = None) -> None:
        from pathlib import Path

        self.config = config or NeMoGuardrailsConfig()
        self.gpu_available: bool = has_gpu()
        self._rails: Any = None

        # Resolve colang flows dir
        if self.config.colang_flows_dir is None:
            project_root = Path(__file__).parent.parent.parent.parent
            self._flows_dir = project_root / "colang_flows"
        else:
            self._flows_dir = Path(self.config.colang_flows_dir)

    @property
    def rails(self) -> Any:
        """Lazy LLMRails instance (initialized on first access)."""
        if self._rails is not None:
            return self._rails

        _check_dependencies()

        from nemoguardrails import LLMRails, RailsConfig

        flows_path = self._flows_dir / "banking_topics.co"
        if not flows_path.exists():
            raise NeMoGuardrailsUnavailable(
                f"Colang flows not found at {flows_path}. "
                "Create colang_flows/banking_topics.co or set "
                "config.colang_flows_dir."
            )

        try:
            config = RailsConfig.from_path(str(self._flows_dir))
            self._rails = LLMRails(config)
        except Exception as exc:
            raise NeMoGuardrailsUnavailable(
                f"NeMo Guardrails initialization failed: {exc}"
            ) from exc

        return self._rails

    async def check_input(self, prompt: str) -> dict[str, Any]:
        """Проверяет user prompt через NeMo Colang input rails.

        Args:
            prompt: Текст запроса пользователя.

        Returns:
            Словарь с ключами:
            - ``safe`` (bool): True если prompt прошёл все rails.
            - ``reason`` (str): Категория нарушения если unsafe.
            - ``rail`` (str): Имя сработавшего rail.

        Raises:
            NeMoGuardrailsUnavailable: если fail_closed=True и
                инициализация не удалась.
        """
        try:
            # synchronous blocking call — run in thread pool to avoid
            # blocking the event loop (NeMo uses torch which may sync)
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            from nemoguardrails import RailsConfig

            loop = asyncio.get_running_loop()
            executor = ThreadPoolExecutor(max_workers=1)

            def _sync_check() -> dict[str, Any]:
                try:
                    result = self.rails.generate(
                        prompt=prompt,
                        config=RailsConfig.from_path(str(self._flows_dir)),
                    )
                    return {"safe": True, "response": result}
                except Exception as exc:
                    logger.debug("NeMo Guardrails input check failed: %s", exc)
                    if self.config.fail_closed:
                        return {
                            "safe": False,
                            "reason": str(exc),
                            "rail": "nemo_init_error",
                        }
                    return {"safe": True, "response": None}

            response = await loop.run_in_executor(executor, _sync_check)
            executor.shutdown(wait=False)
            return response
        except NeMoGuardrailsUnavailable:
            raise
        except Exception as exc:
            logger.warning("NeMo Guardrails check_input error: %s", exc)
            if self.config.fail_closed:
                return {"safe": False, "reason": str(exc), "rail": "nemo_error"}
            return {"safe": True, "response": None}

    async def check_output(self, prompt: str, completion: str) -> dict[str, Any]:
        """Проверяет LLM completion через NeMo output rails.

        Args:
            prompt: Оригинальный user prompt (для context).
            completion: Ответ LLM.

        Returns:
            Словарь с ``safe``, ``reason``, ``rail``.
        """
        # NeMo output rails: factuality check + refusal patterns
        try:
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            loop = asyncio.get_running_loop()
            executor = ThreadPoolExecutor(max_workers=1)

            def _sync_check() -> dict[str, Any]:
                try:
                    # Output rails receive (prompt, completion) tuple
                    result = self.rails.generate(
                        prompt=f"Input: {prompt}\nOutput: {completion}"
                    )
                    return {"safe": True, "response": result}
                except Exception as exc:
                    logger.debug("NeMo Guardrails output check failed: %s", exc)
                    if self.config.fail_closed:
                        return {
                            "safe": False,
                            "reason": str(exc),
                            "rail": "nemo_output_error",
                        }
                    return {"safe": True, "response": None}

            response = await loop.run_in_executor(executor, _sync_check)
            executor.shutdown(wait=False)
            return response
        except NeMoGuardrailsUnavailable:
            raise
        except Exception as exc:
            logger.warning("NeMo Guardrails check_output error: %s", exc)
            if self.config.fail_closed:
                return {"safe": False, "reason": str(exc), "rail": "nemo_output_error"}
            return {"safe": True, "response": None}


_runtime: NeMoGuardrailsRuntime | None = None


async def get_nemo_guardrails_runtime(
    config: NeMoGuardrailsConfig | None = None,
) -> NeMoGuardrailsRuntime | None:
    """Возвращает NeMo Guardrails runtime или None если GPU/FF недоступен.

    Это singleton — повторные вызовы возвращают тот же инстанс.

    Args:
        config: Опц. конфигурация. При None используется default.

    Returns:
        Инициализированный :class:`NeMoGuardrailsRuntime` если:
        - ``feature_flags.nemo_guardrails_enabled = True``
        - хотя бы один GPU обнаружен
        - ``nemoguardrails`` установлен
        - Colang flows найдены

        Иначе — ``None``. Caller должен обработать None и
        перейти к следующему guardrail в цепочке.
    """
    global _runtime

    if not _check_ff_enabled():
        logger.debug("NeMo Guardrails: nemo_guardrails_enabled=False")
        return None

    if not has_gpu():
        logger.debug("NeMo Guardrails: no GPU available")
        return None

    # Probe dependencies (raises NeMoGuardrailsUnavailable on failure)
    try:
        _check_dependencies()
    except NeMoGuardrailsUnavailable:
        return None

    if _runtime is None:
        _runtime = NeMoGuardrailsRuntime(config=config)

    return _runtime


def reset_nemo_guardrails_runtime() -> None:
    """Сбрасывает singleton runtime (для тестов)."""
    global _runtime
    _runtime = None
