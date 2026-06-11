from __future__ import annotations
"""AI providers package (S68 W4 decomp from ai_providers.py 443 LOC).

4 provider classes + 1 func -> 5 files (per-provider split):
- ``claude.py``: ClaudeProvider (Anthropic)
- ``gemini.py``: GeminiProvider (Google)
- ``ollama.py``: OllamaProvider (local)
- ``openai.py``: OpenAIProvider
- ``helpers.py``: register_extended_providers

Backward-compat: ``from src.backend.services.ai.ai_providers import ClaudeProvider`` works.
"""


from src.backend.services.ai.ai_providers.claude import ClaudeProvider  # S68 W4: re-export
from src.backend.services.ai.ai_providers.gemini import GeminiProvider  # S68 W4: re-export
from src.backend.services.ai.ai_providers.ollama import OllamaProvider  # S68 W4: re-export
from src.backend.services.ai.ai_providers.openai import OpenAIProvider  # S68 W4: re-export
from src.backend.services.ai.ai_providers.helpers import register_extended_providers  # S68 W4: helper re-export

__all__ = (
    "ClaudeProvider",
    "GeminiProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "register_extended_providers",
)
