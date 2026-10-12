"""Durable intake and reviews; approvals atomically enqueue retrieval indexing."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
import uuid


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


MIGRATION = """
BEGIN IMMEDIATE;
CREATE TABLE ingestion_jobs (
 id TEXT PRIMARY KEY, episode INTEGER NOT NULL, status TEXT NOT NULL,
 phase TEXT NOT NULL DEFAULT 'Queued', completed INTEGER NOT NULL DEFAULT 0,
 total INTEGER NOT NULL DEFAULT 0, error TEXT, result_id TEXT REFERENCES episodes(id),
 source_commit TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX one_active_episode ON ingestion_jobs(episode) WHERE status IN ('queued','running');
PRAGMA user_version = 2;
COMMIT;
"""


class StoreMixin:
    @contextmanager
    def transaction(self, write=False):
        connection = self.connect()
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def enqueue(self, episode):
        if type(episode) is not int or not 1 <= episode <= 99999:
            raise APIError('Enter an episode number between 1 and 99999.')
        with self.transaction(True) as db:
            existing = db.execute("SELECT * FROM ingestion_jobs WHERE episode=? AND status IN ('queued','running')", (episode,)).fetchone()
            if existing:
                return dict(existing)
            if db.execute("SELECT count(*) FROM ingestion_jobs WHERE status IN ('queued','running')").fetchone()[0] >= 10:
                raise APIError('The intake queue is full. Wait for a run to finish.', 429)
            key = uuid.uuid4().hex
            db.execute("INSERT INTO ingestion_jobs(id,episode,status) VALUES(?,?,'queued')", (key, episode))
            return dict(db.execute('SELECT * FROM ingestion_jobs WHERE id=?', (key,)).fetchone())

    def jobs(self):
        with self.transaction() as db:
            return [dict(r) for r in db.execute('SELECT * FROM ingestion_jobs ORDER BY created_at DESC,rowid DESC LIMIT 50')]

    def recover_jobs(self):
        with self.transaction(True) as db:
            db.execute("UPDATE ingestion_jobs SET status='failed', phase='Interrupted', error='The service restarted during preparation. Retry this episode.', updated_at=CURRENT_TIMESTAMP WHERE status='running'")

    def claim_job(self):
        with self.transaction(True) as db:
            row = db.execute("SELECT * FROM ingestion_jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE ingestion_jobs SET status='running',phase='Starting',updated_at=CURRENT_TIMESTAMP WHERE id=?", (row['id'],))
                return dict(row)

    def job_progress(self, key, phase, completed=0, total=0, source_commit=None):
        with self.transaction(True) as db:
            db.execute('UPDATE ingestion_jobs SET phase=?,completed=?,total=?,source_commit=COALESCE(?,source_commit),updated_at=CURRENT_TIMESTAMP WHERE id=?',
                       (phase, completed, total, source_commit, key))

    def fail_job(self, key, message):
        with self.transaction(True) as db:
            db.execute("UPDATE ingestion_jobs SET status='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (message[:2000], key))

    def existing_intake(self, intake_id):
        with self.transaction() as db:
            return db.execute('SELECT 1 FROM episodes WHERE id=?', (intake_id,)).fetchone() is not None

    def finish_existing(self, job_id, intake_id):
        with self.transaction(True) as db:
            db.execute("UPDATE ingestion_jobs SET status='complete',phase='Already in the review inbox',result_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (intake_id, job_id))

    def import_intake(self, job_id, intake, report):
        """One transaction: all sections, questions, and evidence become visible together."""
        with self.transaction(True) as db:
            db.execute('INSERT INTO episodes(id,episode_number,title,source_json) VALUES(?,?,?,?)',
                       (intake['id'], intake['episode'], f"Episode {intake['episode']}", json.dumps(report['manifest'])))
            for i, section in enumerate(report['sections']):
                ids = set(section['passage_ids'])
                payload = {**section, 'passages': [p for p in report['passages'] if p['id'] in ids]}
                db.execute('INSERT INTO sections VALUES(?,?,?,?)', (intake['id'] + ':' + section['id'], intake['id'], i, json.dumps(payload)))
            for question in intake['questions']:
                db.execute('INSERT INTO questions(id,section_id,content_json) VALUES(?,?,?)',
                           (question['id'], intake['id'] + ':' + question['section'], json.dumps(question)))
            db.execute("UPDATE ingestion_jobs SET status='complete',phase=?,completed=?,total=?,result_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (f"Ready: {len(intake['questions'])} questions", len(report['sections']), len(report['sections']), intake['id'], job_id))

    def inbox(self):
        with self.transaction() as db:
            questions = [json.loads(r[0]) for r in db.execute('SELECT content_json FROM questions ORDER BY created_at,rowid')]
            records, revisions = {}, {}
            for row in db.execute('SELECT question_id,state_json,revision FROM reviews'):
                records[row[0]] = json.loads(row[1])
                revisions[row[0]] = row[2]
            counts = {name: db.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                      for name in ('episodes', 'sections', 'questions', 'reviews')}
            return {'apiVersion': 1, 'reviewEnabled': True, 'counts': counts,
                    'bundle': {'id': 'server', 'questions': questions}, 'records': records, 'revisions': revisions}

    def save_review(self, question_id, body):
        if not isinstance(body, dict) or set(body) != {'revision', 'review'} or type(body['revision']) is not int:
            raise APIError('A review and its current revision are required.')
        review = validate_review_state(body['review'])
        with self.transaction(True) as db:
            question = db.execute('SELECT content_json FROM questions WHERE id=?', (question_id,)).fetchone()
            if not question:
                raise APIError('Question not found.', 404)
            previous = db.execute('SELECT state_json,revision FROM reviews WHERE question_id=?', (question_id,)).fetchone()
            revision = previous['revision'] if previous else 0
            if body['revision'] != revision:
                raise APIError('This question changed in another tab. Reload the inbox before editing again.', 409)
            old = json.loads(previous['state_json']) if previous else None
            if old and old['status'] != 'pending':
                if review['status'] != 'pending' or any(review[k] for k in ('sourceChecked', 'materialChecked', 'scopeChecked', 'evidence', 'teaching')):
                    raise APIError('Reopen this question and read the evidence before changing its decision.')
            source_was_read = old and old['sourceChecked']
            original = json.loads(question['content_json'])
            old_draft = old or {'question': original['question'], 'outline': original['outline']}
            edited = any(review[k] != old_draft[k] for k in ('question', 'outline'))
            judgments = any(review[k] for k in ('materialChecked', 'scopeChecked', 'evidence', 'teaching'))
            if edited and (not source_was_read or judgments or review['status'] != 'pending'):
                raise APIError('Read the source before editing, then grade the revised draft separately.')
            if not source_was_read and judgments:
                raise APIError('Save the source-reading acknowledgment before grading.')
            if review['status'] != 'pending' and (not old or not old['sourceChecked']):
                raise APIError('Save the source-reading acknowledgment before deciding.')
            review['updatedAt'] = datetime.now(timezone.utc).isoformat()
            if review['status'] != 'pending':
                review['decidedAt'] = review['updatedAt']
            db.execute('INSERT INTO reviews(question_id,state_json,revision) VALUES(?,?,?) ON CONFLICT(question_id) DO UPDATE SET state_json=excluded.state_json,revision=excluded.revision,updated_at=CURRENT_TIMESTAMP',
                       (question_id, json.dumps(review), revision + 1))
            from publication_store import queue_revision
            queue_revision(db, question_id, revision + 1, review)
            return {'revision': revision + 1, 'review': review}


def validate_review_state(value):
    if not isinstance(value, dict):
        raise APIError('Invalid review.')
    review = dict(value)
    for key, limit in (('question', 1000), ('notes', 5000)):
        if not isinstance(review.get(key), str) or len(review[key]) > limit:
            raise APIError(f'Invalid {key}.')
    outline = review.get('outline')
    if not isinstance(outline, list) or not 1 <= len(outline) <= 4 or any(not isinstance(s, str) or len(s) > 2000 for s in outline):
        raise APIError('Invalid answer outline.')
    if review.get('status') not in ('pending', 'approved', 'changes_requested', 'excluded'):
        raise APIError('Invalid review status.')
    for key in ('scopeChecked', 'sourceChecked', 'materialChecked'):
        if type(review.get(key)) is not bool:
            raise APIError('Invalid review checks.')
    if review.get('evidence') not in ('', 'strong', 'partial', 'unsupported') or review.get('teaching') not in ('', 'clear', 'needs_work'):
        raise APIError('Invalid review grades.')
    if review.get('productionApproved') is not False or review.get('approvalScope') != 'prototype_review':
        raise APIError('Review decisions do not authorize Discord delivery.')
    if not review['sourceChecked'] and any(review[k] for k in ('materialChecked', 'scopeChecked', 'evidence', 'teaching')):
        raise APIError('Read the supporting evidence first.')
    if review['status'] != 'pending':
        if not isinstance(review.get('reviewedBy'), str) or not 1 <= len(review['reviewedBy'].strip()) <= 100 or not review['sourceChecked']:
            raise APIError('A reviewer name and source acknowledgment are required.')
        if review['status'] == 'approved':
            if (review['evidence'] != 'strong' or review['teaching'] != 'clear'
                    or not review['scopeChecked'] or not review['materialChecked']
                    or not review['question'].strip() or any(not s.strip() for s in outline)):
                raise APIError('Complete all required checks before approval.')
        elif not review['notes'].strip():
            raise APIError('Explain the decision in a review note.')
    else:
        review['reviewedBy'] = review['decidedAt'] = None
    return {k: review.get(k) for k in ('question', 'outline', 'notes', 'status', 'evidence', 'teaching',
            'scopeChecked', 'sourceChecked', 'materialChecked', 'productionApproved', 'approvalScope',
            'reviewedBy', 'decidedAt', 'updatedAt')}
