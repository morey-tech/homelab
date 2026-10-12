"""Revision-aware LanceDB writes and retrieval checked against live review state."""
import json
import threading
from urllib.request import build_opener, HTTPRedirectHandler

import pyarrow as pa
from publication_contract import MODEL, TABLE, fingerprint, normalized_vector, valid_id, validate_mutation


class RevisionConflict(Exception):
    pass


class ApprovalUnavailable(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


REVIEW_STATE_URL = 'http://rr-lessons-review:8080/api/retrieval-state'


def live_review_state():
    try:
        with build_opener(NoRedirects()).open(REVIEW_STATE_URL, timeout=5) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Review state too large')
        value = json.loads(raw)
        rows = value['approved']
        if not isinstance(rows, list):
            raise ValueError('Invalid review state')
        eligible = {}
        for row in rows:
            if (not valid_id(row['question_id']) or type(row['revision']) is not int or row['revision'] < 1
                    or type(row['indexed_revision']) is not int):
                raise ValueError('Invalid review revision')
            if row['revision'] == row['indexed_revision']:
                eligible[row['question_id']] = row['revision']
        return eligible
    except Exception:
        # Outages must never fall back to a cached approval or raw vector result.
        raise ApprovalUnavailable('Current review approvals are unavailable') from None


SCHEMA = pa.schema([
    ('question_id', pa.string()), ('revision', pa.int64()), ('active', pa.bool_()),
    ('record_json', pa.string()), ('model_json', pa.string()), ('mutation_hash', pa.string()),
    ('vector', pa.list_(pa.float32(), MODEL['dimensions'])),
])


class QuestionIndex:
    def __init__(self, db, approvals=live_review_state):
        self.db, self.approvals = db, approvals
        self.lock = threading.Lock()

    def table(self, create=False):
        if create:
            return self.db.create_table(TABLE, schema=SCHEMA, exist_ok=True)
        if TABLE in self.db.list_tables().tables:
            return self.db.open_table(TABLE)
        return None

    def put(self, question_id, body):
        validate_mutation(question_id, body)
        checksum = fingerprint(body)
        with self.lock:
            table = self.table(create=True)
            current = table.search().where(f"question_id = '{question_id}'").limit(1).to_list()
            if current:
                old = current[0]
                if body['revision'] < old['revision'] or (body['revision'] == old['revision'] and checksum != old['mutation_hash']):
                    raise RevisionConflict('A newer or different mutation for this review revision already exists')
                if body['revision'] == old['revision']:
                    return {'revision': body['revision'], 'active': body['active']}
            row = {'question_id': question_id, 'revision': body['revision'], 'active': body['active'],
                   'record_json': json.dumps(body['record'], ensure_ascii=False),
                   'model_json': json.dumps(MODEL), 'mutation_hash': checksum,
                   'vector': normalized_vector(body['vector']) if body['active'] else [0.0] * MODEL['dimensions']}
            table.merge_insert('question_id').when_matched_update_all().when_not_matched_insert_all().execute([row])
        return {'revision': body['revision'], 'active': body['active']}

    def search(self, body):
        if not isinstance(body, dict) or set(body) != {'vector', 'model', 'limit'} or body['model'] != MODEL:
            raise ValueError('Query must use the same embedding model and revision as the index')
        if type(body['limit']) is not int or not 1 <= body['limit'] <= 20:
            raise ValueError('Limit must be between 1 and 20')
        vector = normalized_vector(body['vector'])
        eligible = self.approvals()
        if not eligible:
            return {'results': []}
        table = self.table()
        if table is None:
            return {'results': []}
        # IDs are validated before interpolation, including state providers used in tests.
        if any(not valid_id(key) or type(rev) is not int or rev < 1 for key, rev in eligible.items()):
            raise ApprovalUnavailable('Invalid approval state')
        predicate = 'active = true AND (' + ' OR '.join(
            f"(question_id = '{key}' AND revision = {revision})" for key, revision in eligible.items()) + ')'
        rows = table.search(vector).distance_type('cosine').where(predicate, prefilter=True).limit(body['limit']).to_list()
        # Check again after the query, including reopens that raced with vector search.
        current = self.approvals()
        return {'results': [{'record': json.loads(row['record_json']), 'distance': row['_distance']}
                            for row in rows if current.get(row['question_id']) == row['revision']]}
