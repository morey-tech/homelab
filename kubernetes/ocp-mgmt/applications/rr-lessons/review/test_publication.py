import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'contracts'))
from publication_contract import MODEL, normalized_vector
from publisher import Publisher, approved_record, embed
from server import Database, ReviewApp, SCHEMA
from store import MIGRATION
import test_ingestion
from test_ingestion import pending
import prepare


class FakeEmbedding:
    calls = []
    base_url = 'https://embedding.example/v1'
    name = MODEL['name']

    def __init__(self, url, name, token_path):
        assert name == MODEL['name']

    def post(self, url, body):
        if url.endswith('/tokenize'):
            return {'count': 12}
        self.calls.append(body['input'][0])
        return {'data': [{'index': 0, 'embedding': [2.0] + [0.0] * (MODEL['dimensions'] - 1)}]}


class FakeIndex:
    def __init__(self):
        self.writes = []

    def put(self, key, body):
        self.writes.append((key, body))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        test_ingestion.IngestionTests.setUp(self)
        test_ingestion.IngestionTests.run_episode(self)
        self.q = self.db.inbox()['bundle']['questions'][0]
        self.index = FakeIndex()
        self.publisher = Publisher(self.db, self.root / 'token', self.index, FakeEmbedding)
        FakeEmbedding.calls = []

    def save(self, review):
        revision = self.db.inbox()['revisions'].get(self.q['id'], 0)
        return self.db.save_review(self.q['id'], {'revision': revision, 'review': review})

    def approve(self, question=None):
        review = pending(self.q)
        review['sourceChecked'] = True
        self.save(review)
        if question:
            review['question'] = question
            review['outline'] = ['The corrected, human-approved explanation.']
            self.save(review)
        review.update(status='approved', reviewedBy='Human reviewer', materialChecked=True,
                      evidence='strong', teaching='clear', scopeChecked=True)
        return self.save(review)

    def reopen(self):
        review = self.db.inbox()['records'][self.q['id']]
        review.update(status='pending', sourceChecked=False, materialChecked=False, scopeChecked=False,
                      evidence='', teaching='', reviewedBy=None, decidedAt=None)
        return self.save(review)

    def test_only_approval_queues_final_wording_and_publishes_evidence(self):
        self.assertEqual(self.db.publications(), [])
        self.assertIsNone(self.db.claim_publication())
        saved = self.approve('What does the revised study finding actually establish?')
        job = self.db.claim_publication()
        self.assertEqual(self.db.retrieval_state()['approved'][0]['indexed_revision'], 0)
        self.publisher.run(job)
        self.assertEqual(FakeEmbedding.calls, ['What does the revised study finding actually establish?'])
        body = self.index.writes[0][1]
        self.assertEqual(body['revision'], saved['revision'])
        self.assertEqual(body['record']['outline'], ['The corrected, human-approved explanation.'])
        self.assertEqual(body['record']['passages'], self.q['passages'])
        self.assertEqual(body['record']['source'], self.q['source'])
        self.assertEqual(body['record']['embedding_text'], FakeEmbedding.calls[0])
        self.assertEqual(body['vector'][0], 1)
        self.assertFalse(body['record']['productionApproved'])
        self.assertEqual(self.db.retrieval_state()['approved'][0]['indexed_revision'], saved['revision'])
        self.assertEqual(self.db.request_publication(self.q['id']), {'status': 'complete'})
        self.assertIsNone(self.db.claim_publication())

    def test_reopen_invalidates_before_network_withdrawal(self):
        self.approve()
        self.publisher.run(self.db.claim_publication())
        self.reopen()
        self.assertEqual(self.db.retrieval_state(), {'approved': []})
        job = self.db.claim_publication()
        self.assertEqual(job['action'], 'withdraw')
        self.publisher.run(job)
        self.assertEqual(len(FakeEmbedding.calls), 1)
        self.assertFalse(self.index.writes[-1][1]['active'])
        self.assertIsNone(self.index.writes[-1][1]['record'])

    def test_reopen_during_embedding_discards_result(self):
        self.approve()
        job = self.db.claim_publication()
        with patch('publisher.embed', side_effect=lambda *args: (self.reopen(), [1.0]+[0.0]*2559)[1]):
            self.publisher.run(job)
        self.assertEqual(self.index.writes, [])
        self.assertEqual(self.db.publications()[0]['action'], 'withdraw')
        self.publisher.run(self.db.claim_publication())
        self.assertFalse(self.index.writes[-1][1]['active'])

    def test_late_ack_cannot_mark_newer_revision_indexed(self):
        self.approve()
        job = self.db.claim_publication()
        with patch.object(self.index, 'put', side_effect=lambda *args: self.reopen()):
            self.publisher.run(job)
        row = self.db.publications()[0]
        self.assertEqual((row['action'], row['status'], row['indexed_revision']), ('withdraw', 'queued', 0))

    def test_lost_ack_retry_reuses_vector_and_same_revision(self):
        self.approve()
        job = self.db.claim_publication()
        with patch.object(self.index, 'put', side_effect=prepare.PreparationError('LanceDB timeout')):
            with self.assertRaises(prepare.PreparationError):
                self.publisher.run(job)
        self.db.fail_publication(job, 'LanceDB timeout')
        with self.db.transaction(True) as db:
            db.execute('UPDATE publications SET next_attempt=0')
        retry = self.db.claim_publication()
        self.publisher.run(retry)
        self.assertEqual(len(FakeEmbedding.calls), 1)
        self.assertEqual(retry['revision'], job['revision'])
        self.assertEqual(self.db.publications()[0]['status'], 'complete')

    def test_cached_dense_vector_preserves_exact_request_after_lost_ack(self):
        self.approve()
        job = self.db.claim_publication()
        vector = normalized_vector([float(n % 7 + 1) for n in range(2560)])
        sent = []
        def lost_ack(key, body):
            sent.append(body)
            raise prepare.PreparationError('Lost acknowledgment')
        with patch('publisher.embed', return_value=vector) as embedding:
            with patch.object(self.index, 'put', side_effect=lost_ack):
                with self.assertRaises(prepare.PreparationError): self.publisher.run(job)
            self.db.fail_publication(job, 'Lost acknowledgment')
            with self.db.transaction(True) as db: db.execute('UPDATE publications SET next_attempt=0')
            self.publisher.run(self.db.claim_publication())
            self.assertEqual(embedding.call_count, 1)
        self.assertEqual(sent[0], self.index.writes[0][1])

    def test_restart_recovers_inflight_and_retry_limit_is_visible(self):
        self.approve()
        self.db.claim_publication()
        self.db.recover_publications()
        job = self.db.claim_publication()
        job['attempts'] = 5
        self.db.fail_publication(job, 'Model unavailable')
        self.assertEqual(self.db.publications()[0]['status'], 'failed')
        self.assertIsNone(self.db.claim_publication())
        self.db.request_publication(self.q['id'])
        self.assertEqual(self.db.claim_publication()['attempts'], 1)

    def test_approval_and_queue_are_one_transaction(self):
        review = pending(self.q)
        review['sourceChecked'] = True
        self.save(review)
        review.update(status='approved', reviewedBy='Reviewer', evidence='strong', teaching='clear',
                      scopeChecked=True, materialChecked=True)
        with patch('publication_store.queue_revision', side_effect=sqlite3.OperationalError('disk failure')):
            with self.assertRaises(sqlite3.OperationalError):
                self.save(review)
        self.assertEqual(self.db.inbox()['records'][self.q['id']]['status'], 'pending')
        self.assertEqual(self.db.publications(), [])

    def test_version_two_upgrade_does_not_publish_earlier_approvals(self):
        path = self.root / 'version2.sqlite3'
        with sqlite3.connect(path) as db:
            db.executescript(SCHEMA + MIGRATION)
            db.execute("INSERT INTO episodes VALUES('e',428,'Episode','{}',CURRENT_TIMESTAMP)")
            db.execute("INSERT INTO sections VALUES('s','e',0,'{}')")
            db.execute("INSERT INTO questions(id,section_id,content_json) VALUES(?,'s',?)", (self.q['id'], json.dumps(self.q)))
            review = pending(self.q)
            review.update(status='approved',sourceChecked=True,materialChecked=True,scopeChecked=True,
                          evidence='strong',teaching='clear',reviewedBy='Earlier reviewer',decidedAt='2026-10-12T00:00:00Z')
            db.execute('INSERT INTO reviews(question_id,state_json) VALUES(?,?)', (self.q['id'],json.dumps(review)))
        upgraded = Database(path)
        upgraded.initialize()
        self.assertEqual(upgraded.publications(), [])
        upgraded.request_publication(self.q['id'])
        self.assertEqual(upgraded.claim_publication()['action'], 'index')

    def test_publication_api_uses_stored_approval_and_same_origin(self):
        self.approve()
        with self.db.transaction(True) as db: db.execute('DELETE FROM publications')
        app = ReviewApp(self.db, self.root, publisher=object(), public_origin='https://review.example')
        async def request(payload, origin='https://review.example'):
            sent = []
            async def send(message): sent.append(message)
            async def receive(): return {'type': 'http.request', 'body': json.dumps(payload).encode()}
            await app({'type': 'http', 'method': 'POST', 'path': '/api/publications/' + self.q['id'],
                       'headers': [(b'origin', origin.encode()), (b'content-type', b'application/json')]}, receive, send)
            return sent[0]['status']
        self.assertEqual(asyncio.run(request({}, 'https://elsewhere.example')), 403)
        self.assertEqual(asyncio.run(request({'question': 'Unreviewed replacement'})), 400)
        self.assertEqual(self.db.publications(), [])
        self.assertEqual(asyncio.run(request({})), 202)
        self.assertEqual(self.db.claim_publication()['action'], 'index')

    def test_embedding_budget_and_invalid_vectors_fail_before_publish(self):
        for vector in ([0.0]*2560, [1.0], [float('nan')]*2560, [True]*2560):
            with self.assertRaises(ValueError): normalized_vector(vector)
        model = FakeEmbedding('', MODEL['name'], '')
        with patch.object(model, 'post', return_value={'count': 4097}):
            with self.assertRaises(prepare.PreparationError): embed(model, 'Question?')


if __name__ == '__main__':
    unittest.main()
