from enum import IntFlag

class Taint(IntFlag):
    NONE = 0
    RETRO_LABEL = 1
    NON_PIT_MACRO = 2
    PROXY_OUTCOME = 4
    UNVERIFIED_REPORT_AVAILABILITY = 8
    SYNTHETIC_DATA = 16
    HOLDOUT_EXPOSED = 32
    INFERRED_RECONSTRUCTION = 64

_KNOWN_MASK = sum(int(flag) for flag in Taint)

def combine_taint(*values: int | Taint) -> Taint:
    result = Taint.NONE
    for value in values:
        if type(value) not in (int, Taint) or value < 0 or int(value) & ~_KNOWN_MASK:
            raise ValueError("taint must contain only defined nonnegative flags")
        result |= Taint(value)
    return result
