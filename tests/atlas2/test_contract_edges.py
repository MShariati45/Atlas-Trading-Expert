"""Hand-written contract vectors and adversarial validation cases."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext, Inexact, ROUND_UP

from atlas2.core.canonical import ace1_encode, domain_digest, INT64_MIN, INT64_MAX
from atlas2.core.errors import CanonicalEncodingError
from atlas2.core.ids import make_id, validate_id
from atlas2.core.time import (
    UTC_MICROS_MIN, UTC_MICROS_MAX, datetime_to_utc_micros,
    utc_micros_to_datetime, format_utc_micros,
)
from atlas2.core.units import price_to_int, ratio_to_ppm, r_to_micro
from atlas2.core.taint import Taint, combine_taint
from atlas2.core.enums import AvailabilityBasis
from atlas2.model.data import RawBlob, SourceObservation, BarFact, QuoteFact, FactLink, DatasetMembership

def _id(prefix: str, char: str) -> str:
    return prefix + '_' + char * 64

OBS_ID = _id('obs', 'a')
COMP_ID = _id('comp', 'b')
FBAR_ID = _id('fbar', 'c')
FQT_ID = _id('fqt', 'd')
DS_ID = _id('ds', 'e')
DIGEST = 'f' * 64


class CanonicalEdges(unittest.TestCase):
    def test_golden_digest_and_id(self):
        digest = '84b4ec5ef1b6fd4491c6bf683f2c8431aeccddcb950f04c4a28d1d0e02fb1f56'
        self.assertEqual(domain_digest('candidate.v1', {'x': 1}), digest)
        self.assertEqual(make_id('cand', 'candidate.v1', {'x': 1}), 'cand_' + digest)
        self.assertEqual(ace1_encode([INT64_MIN, INT64_MAX, 'e\u0301']), b'[-9223372036854775808,9223372036854775807,"\xc3\xa9"]')
        self.assertEqual(domain_digest('a', {'b': 1, 'a': 2}), domain_digest('a', {'a': 2, 'b': 1}))

    def test_invalid_values(self):
        cycle = []
        cycle.append(cycle)
        mapping = {}
        mapping['self'] = mapping
        for value in (cycle, mapping, (1, 2), INT64_MIN - 1, INT64_MAX + 1, float('nan'), float('inf'), Decimal('1'), b'x', {1: 'x'}, {'é': 1}, {1, 2}, '\x00', '\udfff'):
            with self.subTest(value=repr(value)), self.assertRaises(CanonicalEncodingError):
                ace1_encode(value)
        shared = [1]
        self.assertEqual(ace1_encode([shared, shared]), b'[[1],[1]]')

    def test_limits(self):
        self.assertEqual(len(ace1_encode('x' * 65534)), 65536)
        for value in ('x' * 65535, 'é' * 32768):
            with self.assertRaises(CanonicalEncodingError):
                ace1_encode(value)
        value = 0
        for _ in range(16):
            value = [value]
        ace1_encode(value)
        with self.assertRaises(CanonicalEncodingError):
            ace1_encode([value])
        empty = []
        for _ in range(15):
            empty = [empty]
        ace1_encode(empty)
        with self.assertRaises(CanonicalEncodingError):
            ace1_encode([empty])

    def test_invalid_domains_and_ids(self):
        for domain in ('', 'é', 'a\x00b', 'a\n', 1, None):
            with self.subTest(domain=domain), self.assertRaises(CanonicalEncodingError):
                domain_digest(domain, {})
        for prefix in ('', 'A', '1x', '_x', 'é', 'a-b', None):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                make_id(prefix, 'a', {})
        for value in (None, 1, 'fact_' + 'a' * 63, FBAR_ID + '\n', FBAR_ID.upper(), 'fact_' + 'g' * 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_id(value)
        self.assertEqual(validate_id(OBS_ID, 'obs'), OBS_ID)
        with self.assertRaises(ValueError):
            validate_id(OBS_ID, 'fbar')
        with self.assertRaises(ValueError):
            validate_id(FBAR_ID, ('fqt', 'fcs'))


class TimeEdges(unittest.TestCase):
    def test_golden_vectors(self):
        for micros, stamp in ((-1000001, '1969-12-31T23:59:58.999999Z'), (-1, '1969-12-31T23:59:59.999999Z'), (0, '1970-01-01T00:00:00.000000Z'), (1, '1970-01-01T00:00:00.000001Z'), (-62135596800000000, '0001-01-01T00:00:00.000000Z'), (253402300799999999, '9999-12-31T23:59:59.999999Z')):
            with self.subTest(micros=micros):
                self.assertEqual(format_utc_micros(micros), stamp)
                dt = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                self.assertEqual(datetime_to_utc_micros(dt), micros)
                self.assertEqual(utc_micros_to_datetime(micros), dt)

    def test_invalid_instants(self):
        for value in (True, 1.0, '1', None):
            with self.assertRaises(TypeError):
                utc_micros_to_datetime(value)
        for value in (INT64_MIN - 1, INT64_MAX + 1):
            with self.assertRaises(ValueError):
                utc_micros_to_datetime(value)
        for value in (UTC_MICROS_MIN - 1, UTC_MICROS_MAX + 1, INT64_MIN, INT64_MAX):
            with self.assertRaises(ValueError):
                utc_micros_to_datetime(value)
        with self.assertRaises(ValueError):
            datetime_to_utc_micros(datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))))


class UnitEdges(unittest.TestCase):
    def test_exact_rounding_and_context_independence(self):
        with localcontext() as ctx:
            ctx.prec = 2
            ctx.rounding = ROUND_UP
            ctx.traps[Inexact] = True
            for value, expected in (('2.5', 2), ('3.5', 4), ('-2.5', -2), ('-3.5', -4), ('2.500000000000000000000000000000000000001', 3), ('3.499999999999999999999999999999999999999', 3), (str(INT64_MAX), INT64_MAX), (str(INT64_MIN), INT64_MIN), ('-0', 0)):
                self.assertEqual(price_to_int(value, 0), expected)
            self.assertEqual(ratio_to_ppm('0.0000025'), 2)
            self.assertEqual(r_to_micro('-1.2345675'), -1234568)
            self.assertEqual(price_to_int('0.00000001', 8), 1)

    def test_invalid_inputs(self):
        for convert in (lambda x: price_to_int(x, 0), ratio_to_ppm, r_to_micro):
            for value in (1.0, True, 1, None):
                with self.assertRaises(TypeError):
                    convert(value)
            for value in ('NaN', 'sNaN', 'Infinity', '-Infinity', 'bad', '1e2', ' 1', '+1', '1_0', '١٢', str(INT64_MAX + 1), str(INT64_MIN - 1)):
                with self.assertRaises(ValueError):
                    convert(value)
        for digits in (-1, 9, True, 1.0):
            with self.assertRaises(ValueError):
                price_to_int('1', digits)


class TaintEdges(unittest.TestCase):
    def test_union_preserves_every_flag(self):
        self.assertEqual(combine_taint(), Taint.NONE)
        self.assertEqual(combine_taint(*Taint), Taint(127))
        for flag in Taint:
            self.assertEqual(combine_taint(flag, flag, Taint.NONE), flag)
            self.assertEqual(combine_taint(Taint.RETRO_LABEL, flag), combine_taint(flag, Taint.RETRO_LABEL))
        self.assertEqual(combine_taint(combine_taint(1, 2), 4), Taint(7))

    def test_invalid_masks(self):
        for value in (-1, 128, True, 1.0, '1', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                combine_taint(value)


class ModelEdges(unittest.TestCase):
    def setUp(self):
        self.blob = RawBlob(DIGEST, 1)
        self.obs = SourceObservation(OBS_ID, DIGEST, 'source', 'v1', 'MANUAL_IMPORT', -1, COMP_ID)
        self.bar = BarFact(FBAR_ID, 'EURUSD', 'M1', 'BID', -1, 1, 10, 12, 9, 11, 0, None, None, None, COMP_ID)
        self.quote = QuoteFact(FQT_ID, 'EURUSD', -1, None, 10, 11, None, None, COMP_ID)
        self.link = FactLink(FBAR_ID, OBS_ID, 'row:1', COMP_ID, None, AvailabilityBasis.UNKNOWN)
        self.member = DatasetMembership(DS_ID, 'BAR', FBAR_ID, OBS_ID, 'row:1')

    def test_valid_models(self):
        for model in (self.blob, self.obs, self.bar, self.quote, self.link, self.member):
            model.validate()
        for basis in AvailabilityBasis:
            replace(self.link, availability_basis=basis, available_at_us=None if basis is AvailabilityBasis.UNKNOWN else -1).validate()
        replace(self.quote, bid=INT64_MIN, ask=INT64_MAX, bid_volume=0, ask_volume=0, source_seq=0).validate()

    def test_integer_fields_reject_non_int64(self):
        for model, fields in ((self.blob, ('byte_size',)), (self.obs, ('acquired_at_us',)), (self.bar, ('open_time_us', 'close_time_us', 'open', 'high', 'low', 'close', 'tick_volume', 'real_volume', 'spread_points')), (self.quote, ('time_us', 'source_seq', 'bid', 'ask', 'bid_volume', 'ask_volume')), (self.link, ('available_at_us', 'quality_flags'))):
            for field in fields:
                for value in (True, 1.0, INT64_MAX + 1, INT64_MIN - 1):
                    with self.subTest(model=type(model).__name__, field=field, value=value), self.assertRaises((ValueError, TypeError)):
                        replace(model, **{field: value}).validate()

    def test_typed_ids_and_nfc_storage(self):
        with self.assertRaises(ValueError):
            replace(self.obs, obs_id=FBAR_ID).validate()
        with self.assertRaises(ValueError):
            replace(self.bar, fact_id=FQT_ID).validate()
        with self.assertRaises(ValueError):
            replace(self.member, dataset_id=OBS_ID).validate()
        with self.assertRaises(ValueError):
            replace(self.member, fact_kind='BAR', fact_id=FQT_ID).validate()
        with self.assertRaises(ValueError):
            replace(self.obs, source_id='e\u0301').validate()
        with self.assertRaises(ValueError):
            replace(self.link, locator='e\u0301').validate()

    def test_invalid_model_relationships(self):
        cases = ((self.blob, {'blob_sha256': 'X' * 64}), (self.blob, {'byte_size': 0}), (self.obs, {'blob_sha256': None}), (self.obs, {'source_id': 1}), (self.obs, {'acquisition_kind': 'OTHER'}), (self.bar, {'high': 10}), (self.bar, {'low': 11}), (self.bar, {'close_time_us': -1}), (self.bar, {'tick_volume': -1}), (self.bar, {'real_volume': -1}), (self.bar, {'spread_points': -1}), (self.bar, {'timeframe': 'M2'}), (self.bar, {'price_side': 'OTHER'}), (self.quote, {'ask': 9}), (self.quote, {'bid_volume': -1}), (self.quote, {'ask_volume': -1}), (self.quote, {'source_seq': -1}), (self.quote, {'instrument_id': ''}), (self.bar, {'instrument_id': 'a\n'}), (self.link, {'availability_basis': 'UNKNOWN'}), (self.link, {'available_at_us': 0}), (self.link, {'availability_basis': AvailabilityBasis.DERIVED}), (self.link, {'quality_flags': -1}), (self.member, {'fact_kind': 'OTHER'}), (self.member, {'locator': 1}))
        for model, changes in cases:
            with self.subTest(model=type(model).__name__, changes=changes), self.assertRaises((ValueError, TypeError, CanonicalEncodingError)):
                replace(model, **changes).validate()


if __name__ == '__main__':
    unittest.main()
