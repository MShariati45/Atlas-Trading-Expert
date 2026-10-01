import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from atlas2.core.canonical import ace1_encode, domain_digest
from atlas2.core.errors import CanonicalEncodingError
from atlas2.core.ids import make_id, validate_id
from atlas2.core.taint import Taint, combine_taint
from atlas2.core.time import datetime_to_utc_micros, format_utc_micros, utc_micros_to_datetime
from atlas2.core.units import price_to_int, ratio_to_ppm


class CanonicalTests(unittest.TestCase):
    def test_hand_written_vectors(self):
        vectors = [
            (None, b"null"),
            (True, b"true"),
            (False, b"false"),
            (0, b"0"),
            (-7, b"-7"),
            ("x", b'"x"'),
            ({"b": 2, "a": 1}, b'{"a":1,"b":2}'),
            ([1, "x", None], b'[1,"x",null]'),
            ({"q": 'a"b', "s": "a\\b"}, b'{"q":"a\\"b","s":"a\\\\b"}'),
        ]
        for value, expected in vectors:
            with self.subTest(value=value):
                self.assertEqual(ace1_encode(value), expected)

    def test_nfc_normalization(self):
        self.assertEqual(ace1_encode("e\u0301"), ace1_encode("\u00e9"))

    def test_forbidden_values(self):
        for value in (1.0, "a\n", "\ud800"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(CanonicalEncodingError):
                    ace1_encode(value)

    def test_domain_separation(self):
        self.assertNotEqual(domain_digest("a.v1", {"x": 1}), domain_digest("b.v1", {"x": 1}))


class IdentityTests(unittest.TestCase):
    def test_full_sha256_id(self):
        value = make_id("cand", "candidate.v1", {"x": 1})
        self.assertEqual(len(value.split("_", 1)[1]), 64)
        self.assertEqual(validate_id(value), value)


class TimeTests(unittest.TestCase):
    def test_round_trip(self):
        original = datetime(2026, 10, 1, 17, 2, 3, 456789, tzinfo=timezone(timedelta(hours=-7)))
        micros = datetime_to_utc_micros(original)
        self.assertEqual(utc_micros_to_datetime(micros), original.astimezone(timezone.utc))
        self.assertTrue(format_utc_micros(micros).endswith("Z"))

    def test_naive_rejected(self):
        with self.assertRaises(ValueError):
            datetime_to_utc_micros(datetime(2026, 1, 1))


class UnitTests(unittest.TestCase):
    def test_price_round_half_even(self):
        self.assertEqual(price_to_int("1.234565", 5), 123456)
        self.assertEqual(price_to_int("1.234575", 5), 123458)

    def test_ratio_ppm(self):
        self.assertEqual(ratio_to_ppm(Decimal("0.382")), 382000)


class TaintTests(unittest.TestCase):
    def test_union(self):
        result = combine_taint(Taint.RETRO_LABEL, Taint.NON_PIT_MACRO)
        self.assertTrue(result & Taint.RETRO_LABEL)
        self.assertTrue(result & Taint.NON_PIT_MACRO)


if __name__ == "__main__":
    unittest.main()
