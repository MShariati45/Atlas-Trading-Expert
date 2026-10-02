"""Non-destructive backup retention policy model for P0-9."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BackupRetentionPolicy:
    daily: int = 30
    monthly: int = 12
    keep_pinned: bool = True

    def validate(self) -> None:
        if type(self.daily) is not int or self.daily < 1:
            raise ValueError("daily retention must be positive")
        if type(self.monthly) is not int or self.monthly < 1:
            raise ValueError("monthly retention must be positive")
        if type(self.keep_pinned) is not bool:
            raise TypeError("keep_pinned must be bool")


DEFAULT_BACKUP_RETENTION = BackupRetentionPolicy()
