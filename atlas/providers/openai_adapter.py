from typing import Any
from .base import AIProviderAdapter

class OpenAIAdapter(AIProviderAdapter):
    def analyze(self, task: str, payload: dict[str, Any], response_schema: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Provider integration intentionally isolated from core Atlas logic.")
