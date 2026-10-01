from enum import IntFlag, StrEnum

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

class DataQualityFlag(IntFlag):
    NONE = 0
    GAP = 1
    SHORT_SESSION = 2
    SPREAD_MISSING = 4
    SPIKE_SUSPECT = 8
    MULTIPLICITY_UNKNOWABLE = 16
    CLOCK_SKEW_SUSPECT = 32
    LATE_ARRIVAL = 64
