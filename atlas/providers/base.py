from abc import ABC, abstractmethod
from typing import Any

class AIProviderAdapter(ABC):
    @abstractmethod
    def analyze(self, task: str, payload: dict[str, Any], response_schema: dict[str, Any]) -> dict[str, Any]:
        """Return validated structured data only."""
        raise NotImplementedError
