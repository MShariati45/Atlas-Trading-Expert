from abc import ABC, abstractmethod
from atlas.core.events import Event
from atlas.core.contracts import ReportEnvelope

class BaseAgent(ABC):
    agent_id: str

    @abstractmethod
    def handle(self, event: Event) -> ReportEnvelope | None:
        raise NotImplementedError
