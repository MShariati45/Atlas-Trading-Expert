from datetime import datetime, timedelta, timezone

UtcMicros = int
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
UTC_MICROS_MIN = -62_135_596_800_000_000
UTC_MICROS_MAX = 253_402_300_799_999_999


def validate_utc_micros(value: UtcMicros) -> UtcMicros:
    if type(value) is not int:
        raise TypeError("UtcMicros must be int")
    if not UTC_MICROS_MIN <= value <= UTC_MICROS_MAX:
        raise ValueError("UtcMicros outside supported UTC datetime range")
    return value


def datetime_to_utc_micros(value: datetime) -> UtcMicros:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware datetime is required")
    try:
        utc = value.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ValueError("datetime maps outside supported UTC range") from exc
    delta = utc - _EPOCH
    micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    return validate_utc_micros(micros)


def utc_micros_to_datetime(value: UtcMicros) -> datetime:
    validate_utc_micros(value)
    return _EPOCH + timedelta(microseconds=value)


def format_utc_micros(value: UtcMicros) -> str:
    return utc_micros_to_datetime(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
