from tools.owner_dev_policy.schema import OwnerPolicyError, SchemaError

# One schema-validation concept shared with the owner layer: TaskContract, handoff, packet, config,
# checkpoint, event, projection and control-request validation all raise this error.
ContractError = SchemaError


class DevWorkflowError(OwnerPolicyError):
    """Base error for the Atlas development workflow runtime."""


class IllegalTransition(DevWorkflowError):
    pass


class StaleLease(DevWorkflowError):
    """A worker attempted to commit with a lease/fencing token that is no longer current."""


class PolicyViolation(DevWorkflowError):
    """An owner-policy or Atlas overlay rule (execution boundary, holdout, legacy, approval) was violated."""


class GitSafetyError(DevWorkflowError):
    """A Git/worktree action was refused because it is unsafe."""


class ProviderError(DevWorkflowError):
    """Transient executor/provider failure; eligible for bounded retry on the same executor."""


class ProviderExhausted(ProviderError):
    """Usage, auth or rate-limit exhaustion: no same-executor retry; checkpoint and fail over."""


class StateStoreError(DevWorkflowError):
    pass
