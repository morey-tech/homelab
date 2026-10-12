"""SQLite outbox: approval and desired index revision commit atomically."""
import json
import time

from store import APIError

MIGRATION = """
BEGIN IMMEDIATE;
CREATE TABLE publications (
 question_id TEXT PRIMARY KEY REFERENCES questions(id),
 revision INTEGER NOT NULL, action TEXT NOT NULL,
 status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 error TEXT, next_attempt REAL NOT NULL DEFAULT 0,
 indexed_revision INTEGER NOT NULL DEFAULT 0,
 payload_json TEXT, vector_json TEXT,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
PRAGMA user_version=3;
COMMIT;
"""


def queue_revision(db, question_id, revision, review):
    previous = db.execute('SELECT 1 FROM publications WHERE question_id=?', (question_id,)).fetchone()
    approved = review['status'] == 'approved'
    if not approved and not previous:
        return
    payload = None
    if approved:
        original = json.loads(db.execute('SELECT content_json FROM questions WHERE id=?', (question_id,)).fetchone()[0])
        payload = json.dumps({'original': original, 'review': review})
    db.execute('''INSERT INTO publications(question_id,revision,action,status,payload_json)
                  VALUES(?,?,?,'queued',?) ON CONFLICT(question_id) DO UPDATE SET
                  revision=excluded.revision,action=excluded.action,status='queued',attempts=0,error=NULL,
                  next_attempt=0,indexed_revision=0,payload_json=excluded.payload_json,vector_json=NULL,
                  updated_at=CURRENT_TIMESTAMP''',
               (question_id, revision, 'index' if approved else 'withdraw', payload))


class PublicationStoreMixin:
    def publications(self):
        with self.transaction() as db:
            return [dict(row) for row in db.execute('''SELECT question_id,revision,action,status,attempts,error,
                indexed_revision,updated_at FROM publications ORDER BY updated_at DESC,question_id''')]

    def retrieval_state(self):
        # No cached approval state: reopening invalidates eligibility in the review transaction.
        with self.transaction() as db:
            return {'approved': [dict(row) for row in db.execute('''SELECT r.question_id,r.revision,
                COALESCE(p.indexed_revision,0) AS indexed_revision FROM reviews r
                LEFT JOIN publications p ON p.question_id=r.question_id
                WHERE json_extract(r.state_json,'$.status')='approved' ''')]}

    def request_publication(self, question_id):
        with self.transaction(True) as db:
            row = db.execute('SELECT * FROM reviews WHERE question_id=?', (question_id,)).fetchone()
            if not row:
                raise APIError('Review not found.', 404)
            review = json.loads(row['state_json'])
            previous = db.execute('SELECT * FROM publications WHERE question_id=?', (question_id,)).fetchone()
            if previous and previous['revision'] == row['revision'] and previous['status'] != 'failed':
                return {'status': previous['status']}
            if review['status'] != 'approved' and not previous:
                raise APIError('Approve the question before indexing it.')
            # Retain a cached vector when retrying the same failed revision.
            if previous and previous['revision'] == row['revision']:
                db.execute("UPDATE publications SET status='queued',attempts=0,error=NULL,next_attempt=0 WHERE question_id=?", (question_id,))
            else:
                queue_revision(db, question_id, row['revision'], review)
            return {'status': 'queued'}

    def recover_publications(self):
        with self.transaction(True) as db:
            db.execute("UPDATE publications SET status='queued',next_attempt=0 WHERE status='processing'")

    def claim_publication(self):
        with self.transaction(True) as db:
            row = db.execute("SELECT * FROM publications WHERE status='queued' AND next_attempt<=? ORDER BY CASE action WHEN 'withdraw' THEN 0 ELSE 1 END,updated_at LIMIT 1", (time.time(),)).fetchone()
            if row:
                db.execute("UPDATE publications SET status='processing',attempts=attempts+1 WHERE question_id=?", (row['question_id'],))
                return {**dict(row), 'attempts': row['attempts'] + 1}

    def publication_current(self, job):
        with self.transaction() as db:
            row = db.execute('SELECT revision,status FROM publications WHERE question_id=?', (job['question_id'],)).fetchone()
            return bool(row and row['revision'] == job['revision'] and row['status'] == 'processing')

    def cache_vector(self, job, vector):
        with self.transaction(True) as db:
            db.execute('UPDATE publications SET vector_json=? WHERE question_id=? AND revision=?',
                       (json.dumps(vector, allow_nan=False), job['question_id'], job['revision']))

    def complete_publication(self, job):
        with self.transaction(True) as db:
            db.execute("UPDATE publications SET status='complete',indexed_revision=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE question_id=? AND revision=?",
                       (job['revision'] if job['action'] == 'index' else 0, job['question_id'], job['revision']))

    def fail_publication(self, job, message):
        with self.transaction(True) as db:
            db.execute("UPDATE publications SET status=?,error=?,next_attempt=?,updated_at=CURRENT_TIMESTAMP WHERE question_id=? AND revision=?",
                       ('failed' if job['attempts'] >= 5 else 'queued', message[:2000],
                        time.time() + min(300, 10 * 2**min(job['attempts'] - 1, 5)), job['question_id'], job['revision']))
