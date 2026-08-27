from abc import ABC, abstractmethod
from .models import AccountConfig, ApprovedSignal

class MetaTraderBridge(ABC):
    @abstractmethod
    def connect(self, account: AccountConfig) -> None: ...

    @abstractmethod
    def place_order(self, account: AccountConfig, signal: ApprovedSignal, volume: float) -> str: ...

    @abstractmethod
    def modify_stop(self, account: AccountConfig, ticket: str, stop: float) -> None: ...

    @abstractmethod
    def close_position(self, account: AccountConfig, ticket: str) -> None: ...
