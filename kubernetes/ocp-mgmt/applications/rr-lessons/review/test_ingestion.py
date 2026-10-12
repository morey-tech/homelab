import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'prototype'))
import prepare
from pipeline import Pipeline, RotatingTokenModel, make_intake
from server import Database, ReviewApp, SCHEMA
from store import APIError


SOURCE = b'## Episode 428\n\nHost: What explains the finding?\n\nGuest: Private businesses account for much of the wealth described in this study. This applies to the study population, rather than every household.\n'


class FakeModel:
    base_url = 'https://model.example/v1'
    name = 'test'

    def __init__(self, base_url, name, token_path):
        if base_url != prepare.DEFAULT_URL or name != 'local-llm':
            raise AssertionError('Intake must only use the GPU preparation model')

    def complete(self, messages, schema):
        payload = json.loads(messages[1]['content'])
        if 'candidate' in payload:
            content = {'supported': True, 'context_sufficient': True, 'teachable': True,
                       'reason': 'The cited passage supports this limited claim.', 'confidence': 'high',
                       'confidence_reason': 'The scope is explicit.'}
        else:
            content = {'questions': [{'concept': 'Business ownership', 'question': 'What role do private businesses play in this study?',
                'answer_outline': [{'claim': 'Private businesses account for much of the wealth in this study.', 'passage_ids': [payload['focus_ids'][-1]]}],
                'context_ids': [], 'qualifications': ['The claim is about the study population.'], 'prerequisites': []}]}
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content)}}]}



def pending(question):
    return dict(question=question['question'], outline=question['outline'], evidence='', teaching='',
                scopeChecked=False, sourceChecked=False, materialChecked=False, notes='', status='pending',
                updatedAt=None, decidedAt=None, reviewedBy=None, approvalScope='prototype_review', productionApproved=False)


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = Database(self.root / 'reviews.sqlite3')
        self.db.initialize()
        self.pipeline = Pipeline(self.db, self.root / 'ingestion', self.root / 'token')
        self.source = prepare.source_from_bytes(SOURCE, 'a' * 40, 428)

    def run_episode(self):
        job = self.db.enqueue(428)
        self.db.claim_job()
        with patch('pipeline.fetch_source', return_value=self.source), patch('pipeline.RotatingTokenModel', FakeModel):
            self.pipeline.run(job)
        return job

    def test_complete_pipeline_import_and_idempotent_repeat_preserve_review(self):
        job = self.run_episode()
        inbox = self.db.inbox()
        self.assertEqual(inbox['counts'], dict(episodes=1, sections=1, questions=1, reviews=0))
        q = inbox['bundle']['questions'][0]
        self.assertEqual(q['episode'], 428)
        self.assertTrue(any(p['isEvidence'] for p in q['passages']))
        for p in q['passages']:
            self.assertEqual(p['text'], SOURCE.decode()[p['start_char']:p['end_char']])
            self.assertIn('a' * 40, p['source_url'])
        review = pending(q)
        self.db.save_review(q['id'], {'revision': 0, 'review': review})
        self.assertNotIn('embeddingText', q)
        with self.db.transaction() as db:
            manifest = json.loads(db.execute('SELECT source_json FROM episodes').fetchone()[0])
            self.assertNotIn('embedding', manifest)
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='embeddings'").fetchone()[0], 0)
        with patch('pipeline.fetch_source', return_value=self.source), patch('pipeline.RotatingTokenModel', side_effect=AssertionError('must reuse intake')):
            second = self.db.enqueue(428)
            self.db.claim_job()
            self.pipeline.run(second)
        self.assertEqual(self.db.counts()['questions'], 1)
        self.assertEqual(self.db.counts()['reviews'], 1)
        self.assertEqual(self.db.jobs()[0]['phase'], 'Already in the review inbox')

    def test_queue_deduplicates_active_jobs_and_recovers_only_running(self):
        first = self.db.enqueue(428)
        self.assertEqual(self.db.enqueue(428)['id'], first['id'])
        self.db.claim_job()
        second = self.db.enqueue(429)
        self.db.recover_jobs()
        by_id = {j['id']: j for j in self.db.jobs()}
        self.assertEqual(by_id[first['id']]['status'], 'failed')
        self.assertIn('restarted', by_id[first['id']]['error'])
        self.assertEqual(by_id[second['id']]['status'], 'queued')
        self.assertNotEqual(self.db.enqueue(428)['id'], first['id'])

    def test_queue_input_validation_and_bound(self):
        for value in (True, 0, -1, '428', 1.5, 100000, None):
            with self.assertRaises(APIError):
                self.db.enqueue(value)
        for n in range(10):
            self.db.enqueue(n+1)
        with self.assertRaisesRegex(APIError, 'full'):
            self.db.enqueue(20)

    def test_failed_extraction_does_not_import_partial_intake(self):
        job = self.db.enqueue(428)
        self.db.claim_job()
        with patch('pipeline.fetch_source', return_value=self.source), patch('pipeline.RotatingTokenModel', FakeModel), \
                patch.object(FakeModel, 'complete', side_effect=prepare.PreparationError('Unavailable model')):
            with self.assertRaises(prepare.PreparationError):
                self.pipeline.run(job)
        self.assertEqual(self.db.counts()['episodes'], 0)

    def test_import_rolls_back_if_a_question_insert_fails(self):
        job = self.run_episode()
        report = json.loads((self.root / 'ingestion/runs' / job['id'] / 'report.json').read_text())
        intake = make_intake(report, 'other')
        # The first question is valid; the second fails after earlier inserts succeeded.
        intake['questions'].append({**intake['questions'][0], 'id': 'other:invalid', 'section': 'missing'})
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.import_intake(job['id'], intake, report)
        self.assertFalse(self.db.existing_intake('other'))
        self.assertEqual(self.db.counts()['questions'], 1)
        self.assertEqual(self.db.counts()['sections'], 1)

    def test_rejected_valid_candidates_keep_reason_and_evidence(self):
        job = self.run_episode()
        report = json.loads((self.root / 'ingestion/runs' / job['id'] / 'report.json').read_text())
        entry = report['questions'][0]
        entry.update(status='rejected', rejection_reason='Scope is too broad.')
        entry['review']['confidence'] = 'low'
        question = make_intake(report, 'test')['questions'][0]
        self.assertEqual(question['recommendation'], 'revise')
        self.assertIn('Scope is too broad', question['reviewNotes'][0])
        self.assertTrue(question['passages'])
        entry['review']['confidence'] = None
        entry['error'] = 'Invalid confidence'
        self.assertEqual(make_intake(report, 'test')['questions'][0]['modelConfidence'], 'not assessed (unvalidated)')

    def test_rotating_token_is_read_for_every_request(self):
        token = self.root / 'token'
        token.write_text('first')
        model = RotatingTokenModel('https://model.example/v1', 'model', token)
        with patch.object(prepare.Model, 'post', return_value={}):
            token.write_text('second')
            model.post('https://model.example/v1/chat/completions', {})
        self.assertEqual(model.token, 'second')

    def test_version_one_migration_preserves_existing_data(self):
        path = self.root / 'old.sqlite3'
        with sqlite3.connect(path) as db:
            db.executescript(SCHEMA)
            db.execute("INSERT INTO episodes(id,episode_number,title,source_json) VALUES('old',1,'Old','{}')")
        old = Database(path)
        old.initialize()
        self.assertEqual(old.counts()['episodes'], 1)
        self.assertEqual(old.jobs(), [])

    def test_source_rejects_wrong_episode_utf8_and_heading_only(self):
        for raw in (b'## Episode 429\n\nwrong', b'\xff', b'## Episode 428\n## Episode 428\n'):
            with self.assertRaises(prepare.PreparationError):
                prepare.source_from_bytes(raw, 'a'*40, 428)
        with patch('pipeline.fetch_source', return_value=prepare.source_from_bytes(b'## Episode 428\n', 'a'*40, 428)):
            with self.assertRaisesRegex(prepare.PreparationError, 'no transcript body'):
                self.pipeline.run(self.db.enqueue(428))

    def test_review_requires_checks_and_detects_concurrent_edit(self):
        self.run_episode()
        q = self.db.inbox()['bundle']['questions'][0]
        r = pending(q)
        approved = {**r, 'status': 'approved', 'reviewedBy': 'Reviewer'}
        with self.assertRaises(APIError):
            self.db.save_review(q['id'], {'revision': 0, 'review': approved})
        r['sourceChecked'] = True
        result = self.db.save_review(q['id'], {'revision': 0, 'review': r})
        approved = {**r, 'status': 'approved', 'reviewedBy': 'Reviewer', 'evidence': 'strong',
                    'teaching': 'clear', 'scopeChecked': True, 'materialChecked': True}
        result = self.db.save_review(q['id'], {'revision': result['revision'], 'review': approved})
        self.assertFalse(result['review']['productionApproved'])
        with self.assertRaises(APIError) as error:
            self.db.save_review(q['id'], {'revision': 1, 'review': r})
        self.assertEqual(error.exception.status, 409)
        with self.assertRaises(APIError):
            self.db.save_review(q['id'], {'revision': 2, 'review': approved})
        reopened = pending(q)
        self.db.save_review(q['id'], {'revision': 2, 'review': reopened})
        with self.assertRaises(APIError):
            self.db.save_review(q['id'], {'revision': 3, 'review': approved})

    def test_editing_requires_source_reading_and_clears_judgments(self):
        self.run_episode()
        q = self.db.inbox()['bundle']['questions'][0]
        original = pending(q)
        edited = {**original, 'question': 'A revised question?'}
        with self.assertRaises(APIError):
            self.db.save_review(q['id'], {'revision': 0, 'review': edited})
        read = {**original, 'sourceChecked': True}
        self.db.save_review(q['id'], {'revision': 0, 'review': read})
        with self.assertRaises(APIError):
            self.db.save_review(q['id'], {'revision': 1, 'review': {**edited, 'sourceChecked': True, 'evidence': 'strong'}})
        result = self.db.save_review(q['id'], {'revision': 1, 'review': {**edited, 'sourceChecked': True}})
        self.assertEqual(result['review']['question'], 'A revised question?')
        self.assertEqual(result['review']['evidence'], '')

    def test_http_review_validation_and_missing_question(self):
        self.run_episode()
        q = self.db.inbox()['bundle']['questions'][0]
        app = ReviewApp(self.db, self.root, public_origin='https://review.example')
        async def request(question_id, review):
            sent = []
            async def send(message): sent.append(message)
            async def receive(): return {'type': 'http.request', 'body': json.dumps({'revision': 0, 'review': review}).encode()}
            await app({'type': 'http', 'method': 'PUT', 'path': '/api/reviews/' + question_id,
                       'headers': [(b'origin', b'https://review.example'), (b'content-type', b'application/json')]}, receive, send)
            return sent[0]['status']
        self.assertEqual(asyncio.run(request(q['id'], pending(q))), 200)
        self.assertEqual(asyncio.run(request(q['id'], pending(q))), 409)
        self.assertEqual(asyncio.run(request('unknown', pending(q))), 404)

    def test_http_queue_origin_content_type_and_body_validation(self):
        app = ReviewApp(self.db, self.root, worker=object(), public_origin='https://review.example')
        async def request(body, origin='https://review.example', content_type='application/json'):
            sent=[]
            async def send(message): sent.append(message)
            async def receive(): return {'type': 'http.request', 'body': body}
            await app({'type': 'http', 'method': 'POST', 'path': '/api/ingestions',
                       'headers': [(b'origin', origin.encode()), (b'content-type', content_type.encode())]}, receive, send)
            return sent[0]['status'], json.loads(sent[1]['body'])
        self.assertEqual(asyncio.run(request(b'{"episode":428}'))[0], 202)
        self.assertEqual(asyncio.run(request(b'{"episode":428}', origin='https://evil.example'))[0], 403)
        self.assertEqual(asyncio.run(request(b'{"episode":428}', content_type='text/plain'))[0], 415)
        self.assertEqual(asyncio.run(request(b'not json'))[0], 400)
        self.assertEqual(asyncio.run(request(b' ' * 32769))[0], 413)
        self.assertEqual(asyncio.run(request(b'{"episode":true}'))[0], 400)
        self.assertEqual(len(self.db.jobs()), 1)


if __name__ == '__main__':
    unittest.main()
