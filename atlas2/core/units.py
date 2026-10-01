from decimal import Decimal, InvalidOperation
import re

from .canonical import INT64_MIN, INT64_MAX

_DECIMAL_TEXT_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")

def validate_int64(value: int) -> int:
    if type(value) is not int or not (INT64_MIN <= value <= INT64_MAX):
        raise ValueError("value must be an int64")
    return value


def _scaled(value: str | Decimal, digits: int) -> int:
    if type(value) is str:
        if not value.isascii() or not _DECIMAL_TEXT_RE.fullmatch(value):
            raise ValueError("decimal text must use plain ASCII decimal notation")
    elif not isinstance(value, Decimal):
        raise TypeError("scaled values require text or Decimal; legacy floats need a versioned policy")
    try:
        dec = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal value") from exc
    if not dec.is_finite():
        raise ValueError("scaled values must be finite")
    if dec.is_zero() or dec.adjusted() + digits < -1:
        return 0
    if dec.adjusted() + digits > 18:
        raise ValueError("value must be an int64")
    # Exact integer arithmetic avoids ambient Decimal precision and rounding.
    numerator, denominator = dec.as_integer_ratio()
    quotient, remainder = divmod(abs(numerator) * 10**digits, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and quotient % 2):
        quotient += 1
    return validate_int64(-quotient if numerator < 0 else quotient)

def price_to_int(value: str | Decimal, digits: int) -> int:
    if type(digits) is not int or not 0 <= digits <= 8:
        raise ValueError("digits must be an integer from 0 to 8")
    return _scaled(value, digits)

def ratio_to_ppm(value: str | Decimal) -> int:
    return _scaled(value, 6)

def r_to_micro(value: str | Decimal) -> int:
    return ratio_to_ppm(value)


def canonical_decimal_text(value: str | Decimal) -> str:
    """Return an exact, non-exponent, no-trailing-fraction-zero decimal string."""
    if type(value) is str:
        if not value.isascii():
            raise ValueError("decimal text must be ASCII")
        try:
            dec = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid decimal value") from exc
    elif isinstance(value, Decimal):
        dec = value
    else:
        raise TypeError("decimal value must be text or Decimal")
    if not dec.is_finite():
        raise ValueError("decimal value must be finite")
    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"-0", ""}:
        text = "0"
    if text.startswith("+"):
        text = text[1:]
    return text
