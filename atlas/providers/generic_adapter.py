from typing import Any
from .base import AIProviderAdapter

class GenericProviderAdapter(AIProviderAdapter):
    def analyze(self, task: str, payload: dict[str, Any], response_schema: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Implement provider-specific API mapping here.")
