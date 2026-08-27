from collections import defaultdict
from collections.abc import Callable
from .events import Event

class EventOrchestrator:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: Event) -> None:
        for handler in self._handlers.get(event.type, []):
            handler(event)
