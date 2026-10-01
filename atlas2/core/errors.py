class Atlas2Error(Exception):
    """Base error for Atlas v2."""

class CanonicalEncodingError(Atlas2Error):
    pass

class IdentityConflict(Atlas2Error):
    pass

class IdempotencyViolation(Atlas2Error):
    pass

class CausalityViolation(Atlas2Error):
    pass

class HoldoutLocked(Atlas2Error):
    pass

class SealViolation(Atlas2Error):
    pass
