import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'contracts'))
import lancedb
from publication_contract import MODEL, TABLE, fingerprint
from question_index import QuestionIndex, RevisionConflict, ApprovalUnavailable, live_review_state


def mutation(revision=2, active=True):
    question = 'What can this study establish?'
    record = {'question_id': 'e428:test', 'review_revision': revision, 'question': question,
              'outline': ['A carefully scoped finding.'], 'passages': [{'text': 'Original evidence.'}],
              'approved_for_retrieval': True, 'productionApproved': False,
              'embedding_text': question, 'embedding_input_sha256': fingerprint(question)} if active else None
    return {'revision': revision, 'active': active, 'record': record, 'model': MODEL,
            'vector': [1.0] + [0.0]*2559 if active else None}


class QuestionIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = lancedb.connect(self.temp.name)
        self.eligible = {}
        self.index = QuestionIndex(self.db, lambda: self.eligible.copy())
        self.query = {'vector': [1.0]+[0.0]*2559, 'model': MODEL, 'limit': 5}

    def test_idempotent_publication_and_persistence(self):
        body = mutation()
        self.index.put('e428:test', body)
        self.index.put('e428:test', body)
        self.assertEqual(self.db.open_table(TABLE).count_rows(), 1)
        self.assertEqual(self.index.search(self.query)['results'], [])
        self.eligible['e428:test'] = 2
        result = self.index.search(self.query)['results']
        self.assertEqual(result[0]['record']['question'], body['record']['question'])
        restarted = QuestionIndex(lancedb.connect(self.temp.name), lambda: self.eligible)
        self.assertEqual(restarted.search(self.query)['results'], result)
        changed = mutation()
        changed['record']['outline'] = ['A different answer']
        with self.assertRaises(RevisionConflict): self.index.put('e428:test', changed)

    def test_tombstone_prevents_delayed_retry_from_restoring_revoked_content(self):
        self.index.put('e428:test', mutation())
        self.index.put('e428:test', mutation(3, False))
        with self.assertRaises(RevisionConflict): self.index.put('e428:test', mutation())
        self.eligible['e428:test'] = 2
        self.assertEqual(self.index.search(self.query)['results'], [])
        self.index.put('e428:test', mutation(4))
        self.eligible['e428:test'] = 4
        self.assertEqual(len(self.index.search(self.query)['results']), 1)

    def test_live_review_gate_hides_rows_before_withdrawal_arrives(self):
        self.index.put('e428:test', mutation())
        self.eligible['e428:test'] = 2
        self.assertEqual(len(self.index.search(self.query)['results']), 1)
        self.eligible.clear()
        self.assertEqual(self.index.search(self.query)['results'], [])
        self.eligible['e428:test'] = 4
        self.assertEqual(self.index.search(self.query)['results'], [])

    def test_reopen_racing_with_search_is_checked_again(self):
        self.index.put('e428:test', mutation())
        self.index.approvals = unittest.mock.Mock(side_effect=[{'e428:test': 2}, {}])
        self.assertEqual(self.index.search(self.query)['results'], [])

    def test_unavailable_review_service_fails_closed(self):
        self.index.put('e428:test', mutation())
        self.index.approvals = unittest.mock.Mock(side_effect=ApprovalUnavailable('offline'))
        with self.assertRaises(ApprovalUnavailable): self.index.search(self.query)
        with patch('question_index.build_opener', side_effect=OSError('offline')):
            with self.assertRaises(ApprovalUnavailable): live_review_state()

    def test_model_revision_vector_and_identifier_validation(self):
        for change in ({'model': {**MODEL, 'revision': 'other'}}, {'vector': [0.0]*2560},
                       {'vector': [float('nan')]*2560}, {'vector': [1.0]}, {'revision': True}):
            with self.assertRaises(ValueError): self.index.put('e428:test', {**mutation(), **change})
        with self.assertRaises(ValueError): self.index.put("q' OR true", mutation())
        with self.assertRaises(ValueError): self.index.search({**self.query, 'model': {}})


if __name__ == '__main__':
    unittest.main()
