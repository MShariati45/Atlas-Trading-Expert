import sqlite3
import tempfile
import unittest
from pathlib import Path

from atlas2.model.research import Preregistration, TRIAL_EVENTS
from atlas2.research.registry import ResearchRegistry
from atlas2.store.backup import verify
from atlas2.store.records import RunManifest, RunAttemptStart
from atlas2.store.repository import Store, StoreConflict, ConflictKind


class ResearchRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'store'
        self.store = Store(self.root)
        self.addCleanup(self.store.close)
        self.registry = ResearchRegistry(self.store)

    def experiment(self, key='exp-1', kind='CONFIRMATORY', payload=None):
        return self.registry.register_experiment(
            payload or {'hypothesis': 'h1'}, 'ali', key, kind,
        )

    def trial(self, exp=None, key='trial-1'):
        exp = exp or self.experiment()
        return self.registry.plan_trial(exp.experiment_id, {'p': 1}, 'ali', key)

    def start_trial(self, trial=None, key='start-1'):
        trial = trial or self.trial()
        return self.registry.record_trial_event(trial.trial_id, 'STARTED', 'ali', key)

    def run_attempt(self, attempt_id='attempt-1', attempt_no=1):
        manifest_id = 'manifest-' + str(attempt_no)
        self.store.put(RunManifest(manifest_id, '0' * 64, None, 'REPLAY', '{}'))
        start = RunAttemptStart(attempt_id, manifest_id, 1, attempt_no, attempt_no, '{}')
        self.store.put(start)
        return start

    def test_prereg_hash_stability_and_request_retry(self):
        a = Preregistration.from_payload({'b': 2, 'a': 1})
        b = Preregistration.from_payload({'a': 1, 'b': 2})
        self.assertEqual(a, b)
        first = self.registry.register_experiment({'b': 2, 'a': 1}, 'ali', 'same')
        retry = self.registry.register_experiment({'a': 1, 'b': 2}, 'ali', 'same')
        self.assertEqual(first, retry)
        self.assertEqual(self.store.conn.execute('SELECT count(*) FROM research_experiments').fetchone()[0], 1)
        with self.assertRaises(StoreConflict) as ctx:
            self.registry.register_experiment({'a': 9}, 'ali', 'same')
        self.assertEqual(ctx.exception.kind, ConflictKind.LOGICAL_KEY_CONFLICT)
        with self.assertRaises(ValueError):
            Preregistration.from_payload({'experiment_id': 'self-reference'})

    def test_amendment_lineage_and_sequence(self):
        exp = self.experiment()
        a1 = self.registry.amend_experiment(exp.experiment_id, {'hypothesis': 'h2'}, 'ali', 'amend-1')
        a2 = self.registry.amend_experiment(exp.experiment_id, {'hypothesis': 'h3'}, 'ali', 'amend-2')
        self.assertEqual((a1.sequence, a2.sequence), (1, 2))
        self.assertEqual(a2.parent_effective_digest, a1.new_payload_digest)
        self.assertEqual(self.registry.effective_preregistration(exp.experiment_id), (a2.new_payload_digest, 2))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute(
                'INSERT INTO research_amendments VALUES (?,?,?,?,?,?)',
                ('bad', exp.experiment_id, 4, a2.new_payload_digest, a1.new_payload_digest, 4),
            )

    def test_started_event_seals_and_post_seal_amendment_disqualifies(self):
        exp = self.experiment()
        trial = self.trial(exp)
        started = self.registry.record_trial_event(trial.trial_id, 'STARTED', 'ali', 'started')
        seal = self.registry.seal_state(exp.experiment_id)
        self.assertEqual(seal.source, 'TRIAL_STARTED')
        self.assertEqual(seal.evidence_id, started.event_id)
        self.assertTrue(self.registry.confirmatory_eligible(exp.experiment_id))
        amendment = self.registry.amend_experiment(exp.experiment_id, {'hypothesis': 'changed'}, 'ali', 'late-amend')
        self.assertGreater(amendment.sequence, seal.amendment_sequence)
        self.assertFalse(self.registry.confirmatory_eligible(exp.experiment_id))
        # A running trial remains pinned to the preregistration it started under.
        completed = self.registry.record_trial_event(trial.trial_id, 'COMPLETED', 'ali', 'completed')
        self.assertEqual(completed.effective_prereg_digest, started.effective_prereg_digest)
        with self.assertRaises(ValueError):
            self.registry.record_trial_event(trial.trial_id, 'STARTED', 'ali', 'started-again')
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute(
                'INSERT INTO research_trial_events VALUES (?,?,?,?,?,?,?)',
                ('raw-second-start', trial.trial_id, 'STARTED', started.effective_prereg_digest,
                 started.amendment_sequence, started.evidence_order + 100, started.recorded_at_us + 1),
            )

    def test_repeated_parameter_point_gets_distinct_trial_index(self):
        exp = self.experiment()
        first = self.registry.plan_trial(exp.experiment_id, {'p': 1}, 'ali', 'trial-a')
        second = self.registry.plan_trial(exp.experiment_id, {'p': 1}, 'ali', 'trial-b')
        retry = self.registry.plan_trial(exp.experiment_id, {'p': 1}, 'ali', 'trial-a')
        self.assertEqual((first.trial_index, second.trial_index), (1, 2))
        self.assertNotEqual(first.trial_id, second.trial_id)
        self.assertEqual(first, retry)

    def test_trial_event_vocabulary_and_result_pin(self):
        exp = self.experiment()
        trial = self.trial(exp)
        with self.assertRaises(ValueError):
            self.registry.record_trial_event(trial.trial_id, 'BOGUS', 'ali', 'bad-event')
        started = self.registry.record_trial_event(trial.trial_id, 'STARTED', 'ali', 'started')
        self.assertEqual(set(TRIAL_EVENTS), {
            'PLANNED','STARTED','FAILED','ABANDONED','COMPLETED','INSPECTED','SELECTED','REPLICATED'
        })
        attempt1 = self.run_attempt('attempt-1', 1)
        primary = self.registry.record_trial_result(
            trial.trial_id, 'PRIMARY', attempt1.attempt_id, {'r_micro': 10}, 'ali', 'result-1'
        )
        self.assertEqual(primary.effective_prereg_digest, started.effective_prereg_digest)
        attempt2 = self.run_attempt('attempt-2', 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry.record_trial_result(
                trial.trial_id, 'PRIMARY', attempt2.attempt_id, {'r_micro': 20}, 'ali', 'result-2'
            )
        replication = self.registry.record_trial_result(
            trial.trial_id, 'REPLICATION', attempt2.attempt_id, {'r_micro': 20}, 'ali', 'rep-1'
        )
        self.assertEqual(replication.result_kind, 'REPLICATION')

    def test_decision_unique_per_experiment(self):
        exp = self.experiment()
        first = self.registry.decide(exp.experiment_id, {'decision': 'KEEP'}, 'ali', 'decision-1')
        self.assertEqual(first.experiment_id, exp.experiment_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry.decide(exp.experiment_id, {'decision': 'REJECT'}, 'ali', 'decision-2')

    def test_grant_type_restriction_and_deterministic_batch_session(self):
        segment = self.registry.add_holdout_segment('EURUSD', 100, 200)
        exploratory = self.experiment('explore', 'EXPLORATORY')
        with self.assertRaises(ValueError):
            self.registry.grant_holdout(exploratory.experiment_id, segment.segment_id, 'ali', 'g0')
        exp = self.experiment('confirm')
        grant = self.registry.grant_holdout(exp.experiment_id, segment.segment_id, 'ali', 'g1')
        retry = self.registry.grant_holdout(exp.experiment_id, segment.segment_id, 'ali', 'g1')
        self.assertEqual(grant, retry)
        self.assertEqual(grant.batch_session_id, retry.batch_session_id)

    def test_exposure_seals_overlap_and_same_session_repeat(self):
        exp = self.experiment()
        segment = self.registry.add_holdout_segment('EURUSD', 100, 200)
        grant = self.registry.grant_holdout(exp.experiment_id, segment.segment_id, 'ali', 'g1')
        p1 = self.registry.guard_holdout(grant.grant_id, 'ali', 'final-oos', 'OUTCOME_VIEW', 50, 150, 'read-1')
        self.assertEqual((p1.exposures[0].start_us, p1.exposures[0].end_us), (100, 150))
        seal = self.registry.seal_state(exp.experiment_id)
        self.assertEqual(seal.source, 'HOLDOUT_EXPOSURE')
        p2 = self.registry.guard_holdout(grant.grant_id, 'ali', 'final-oos', 'OUTCOME_VIEW', 120, 170, 'read-2')
        self.assertEqual(p1.batch_session_id, p2.batch_session_id)
        self.assertEqual(self.registry.holdout_status(segment.segment_id).status, 'GRANTED_IN_USE')
        with self.assertRaises(ValueError):
            self.registry.guard_holdout(grant.grant_id, 'ali', 'final-oos', 'OUTCOME_VIEW', 1, 50, 'no-overlap')
        with self.assertRaises(ValueError):
            self.registry.guard_holdout(grant.grant_id, 'ali', 'final-oos', 'NOT_A_ROUTE', 100, 120, 'bad-route')

    def test_adaptive_second_session_marks_inspected(self):
        exp = self.experiment()
        segment = self.registry.add_holdout_segment('EURUSD', 100, 200)
        g1 = self.registry.grant_holdout(exp.experiment_id, segment.segment_id, 'ali', 'g1')
        self.registry.guard_holdout(g1.grant_id, 'ali', 'final-oos', 'MARKET_VIEW', 100, 120, 'r1')
        g2 = self.registry.grant_holdout(exp.experiment_id, segment.segment_id, 'ali', 'g2')
        self.assertNotEqual(g1.batch_session_id, g2.batch_session_id)
        self.registry.guard_holdout(g2.grant_id, 'ali', 'final-oos', 'MARKET_VIEW', 110, 130, 'r2')
        status = self.registry.holdout_status(segment.segment_id)
        self.assertEqual(status.status, 'INSPECTED')
        self.assertEqual(len(status.batch_session_ids), 2)
        self.assertFalse(self.registry.confirmatory_eligible(exp.experiment_id))

    def test_stale_unused_grant_rejected_but_started_session_can_finish(self):
        exp = self.experiment()
        segment = self.registry.add_holdout_segment('EURUSD', 100, 200)
        unused = self.registry.grant_holdout(exp.experiment_id, segment.segment_id, 'ali', 'g-unused')
        self.registry.amend_experiment(exp.experiment_id, {'hypothesis': 'h2'}, 'ali', 'amend')
        with self.assertRaises(ValueError):
            self.registry.guard_holdout(unused.grant_id, 'ali', 'final', 'MARKET_VIEW', 100, 120, 'stale')

        exp2 = self.experiment('exp2')
        g = self.registry.grant_holdout(exp2.experiment_id, segment.segment_id, 'ali', 'g-live')
        first = self.registry.guard_holdout(g.grant_id, 'ali', 'final', 'MARKET_VIEW', 100, 120, 'live-1')
        self.registry.amend_experiment(exp2.experiment_id, {'hypothesis': 'changed'}, 'ali', 'late')
        second = self.registry.guard_holdout(g.grant_id, 'ali', 'final', 'MARKET_VIEW', 120, 140, 'live-2')
        self.assertEqual(first.batch_session_id, second.batch_session_id)
        self.assertFalse(self.registry.confirmatory_eligible(exp2.experiment_id))

    def test_exposure_and_request_are_one_transaction(self):
        exp = self.experiment()
        segment = self.registry.add_holdout_segment('EURUSD', 100, 200)
        grant = self.registry.grant_holdout(exp.experiment_id, segment.segment_id, 'ali', 'g1')
        self.store.conn.execute("""
            CREATE TRIGGER fail_holdout_receipt BEFORE INSERT ON sys_request_keys
            WHEN NEW.action_kind='research.holdout_exposure'
            BEGIN SELECT RAISE(ABORT,'INJECTED_RECEIPT_FAILURE'); END
        """)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'INJECTED_RECEIPT_FAILURE'):
                self.registry.guard_holdout(grant.grant_id, 'ali', 'final', 'EXPORT', 100, 120, 'crash')
            self.assertEqual(self.store.conn.execute('SELECT count(*) FROM research_exposures').fetchone()[0], 0)
            self.assertEqual(self.store.conn.execute(
                "SELECT count(*) FROM sys_request_keys WHERE action_kind='research.holdout_exposure'"
            ).fetchone()[0], 0)
        finally:
            self.store.conn.execute('DROP TRIGGER fail_holdout_receipt')

    def test_dataset_versions_do_not_affect_holdout_identity(self):
        segment = self.registry.add_holdout_segment('EURUSD', 100, 200)
        before = self.registry.holdout_status(segment.segment_id)
        self.store.put(RunManifest('dataset-like-run-a', '1' * 64, None, 'REPLAY', '{}'))
        self.store.put(RunManifest('dataset-like-run-b', '2' * 64, None, 'REPLAY', '{}'))
        self.assertEqual(before, self.registry.holdout_status(segment.segment_id))
        columns = {r['name'] for r in self.store.conn.execute('PRAGMA table_info(research_holdout_segments)')}
        self.assertNotIn('dataset_id', columns)

    def test_research_rows_immutable_and_schema_verified(self):
        exp = self.experiment()
        trial = self.trial(exp)
        self.registry.record_trial_event(trial.trial_id, 'STARTED', 'ali', 'start')
        segment = self.registry.add_holdout_segment('EURUSD', 100, 200)
        grant = self.registry.grant_holdout(exp.experiment_id, segment.segment_id, 'ali', 'g1')
        self.registry.guard_holdout(grant.grant_id, 'ali', 'final', 'LABEL_TASK', 100, 110, 'read')
        verify(self.store.root)
        tables = [
            'research_preregistrations','research_experiments','research_trials',
            'research_trial_events','research_holdout_segments','research_holdout_grants',
            'research_exposures',
        ]
        for table in tables:
            column = self.store.conn.execute(f'PRAGMA table_info({table})').fetchone()['name']
            for sql in (f'UPDATE {table} SET {column}={column}', f'DELETE FROM {table}',
                        f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                with self.subTest(table=table, sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    self.store.conn.execute(sql)
        sql = self.store.conn.execute(
            "SELECT sql FROM sqlite_schema WHERE name='immut_research_exposures_update'"
        ).fetchone()[0]
        self.store.conn.execute('DROP TRIGGER immut_research_exposures_update')
        with self.assertRaisesRegex(ValueError, 'schema drift'):
            verify(self.store.root)
        self.store.conn.execute(sql)
        verify(self.store.root)


if __name__ == '__main__':
    unittest.main()
