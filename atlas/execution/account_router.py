from .models import AccountConfig, ApprovedSignal

class AccountRouter:
    def route(self, signal: ApprovedSignal, accounts: list[AccountConfig]) -> list[tuple[AccountConfig, ApprovedSignal]]:
        return [(a, signal) for a in accounts if a.enabled]
