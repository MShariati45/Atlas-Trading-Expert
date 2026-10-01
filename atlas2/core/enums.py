from enum import StrEnum

class AvailabilityBasis(StrEnum):
    SOURCE_STAMPED = "SOURCE_STAMPED"
    BAR_CLOSE_RULE = "BAR_CLOSE_RULE"
    OBSERVED_BY_ATLAS = "OBSERVED_BY_ATLAS"
    DERIVED = "DERIVED"
    UNKNOWN = "UNKNOWN"

class ViewClass(StrEnum):
    PIT = "PIT"
    NON_PIT = "NON_PIT"

class RunMode(StrEnum):
    REPLAY = "REPLAY"
    FORWARD = "FORWARD"

class ReceiptVerdict(StrEnum):
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"
