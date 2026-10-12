"""Publish the current human-approved revision; never generate or send lessons."""
import fcntl
import json
import logging
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener

import prepare
from pipeline import RotatingTokenModel
from publication_contract import MODEL, MAX_BODY, fingerprint, normalized_vector

LOG = logging.getLogger('uvicorn.error')
EMBEDDING_URL = 'https://qwen3-embedding-4b-inference-server.apps.ocp-mgmt.rh-lab.morey.tech/v1'
LANCEDB_URL = 'http://rr-lessons-lancedb:8080'


def approved_record(job):
    snapshot = json.loads(job['payload_json'])
    original, review = snapshot['original'], snapshot['review']
    if review['status'] != 'approved':
        raise prepare.PreparationError('Publication snapshot is not approved')
    text = review['question']
    return {
        'question_id': job['question_id'], 'review_revision': job['revision'],
        'question': text, 'outline': review['outline'], 'concept': original['concept'],
        'qualifications': original['qualifications'], 'prerequisites': original['prerequisites'],
        'episode': original['episode'], 'section': original['section'], 'source': original['source'],
        'passages': original['passages'], 'original_claims': original['claims'],
        'reviewed_by': review['reviewedBy'], 'approved_at': review['decidedAt'],
        'approved_for_retrieval': True, 'productionApproved': False,
        'embedding_text': text, 'embedding_input_sha256': fingerprint(text),
    }


def embed(model, text):
    count = model.post(model.base_url[:-3] + '/tokenize', {'model': model.name, 'prompt': text}).get('count')
    if type(count) is not int or not 0 < count <= 4096:
        raise prepare.PreparationError('Embedding input exceeds context budget or tokenizer returned an invalid count')
    result = model.post(model.base_url + '/embeddings', {'model': model.name, 'input': [text], 'encoding_format': 'float'})
    rows = result.get('data')
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) or rows[0].get('index') != 0:
        raise prepare.PreparationError('Embedding service returned unexpected rows')
    try:
        return normalized_vector(rows[0].get('embedding'))
    except ValueError as exc:
        raise prepare.PreparationError(str(exc)) from None


class IndexClient:
    def __init__(self):
        self.opener = build_opener(prepare.NoRedirects())

    def put(self, question_id, body):
        raw = prepare.encoded(body)
        if len(raw) > MAX_BODY:
            raise prepare.PreparationError('Prepared publication exceeds the index request size limit')
        request = Request(LANCEDB_URL + '/v1/questions/' + quote(question_id, safe=''), data=raw,
                          method='PUT', headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=30) as response:
                result = json.loads(response.read(4097))
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise prepare.PreparationError(f'LanceDB HTTP {status}') from None
        except (URLError, OSError, ValueError):
            raise prepare.PreparationError('LanceDB unavailable or returned an invalid response') from None
        if result != {'revision': body['revision'], 'active': body['active']}:
            raise prepare.PreparationError('LanceDB did not acknowledge the expected review revision')


class Publisher:
    def __init__(self, database, token_path, index=None, model_factory=RotatingTokenModel):
        self.db, self.token_path = database, token_path
        self.index = index or IndexClient()
        self.model_factory = model_factory
        self.stopping = threading.Event()

    def run(self, job):
        if not self.db.publication_current(job):
            return
        active = job['action'] == 'index'
        record, vector = None, None
        if active:
            record = approved_record(job)
            cache = json.loads(job['vector_json']) if job['vector_json'] else None
            if cache and cache['model'] == MODEL and cache['input_sha256'] == record['embedding_input_sha256']:
                normalized_vector(cache['vector'])  # Validate without changing the acknowledged wire values.
                vector = cache['vector']
            else:
                LOG.info('Embedding approved question %s revision %s', job['question_id'], job['revision'])
                model = self.model_factory(EMBEDDING_URL, MODEL['name'], self.token_path)
                vector = embed(model, record['question'])
                self.db.cache_vector(job, {'model': MODEL, 'input_sha256': record['embedding_input_sha256'], 'vector': vector})
        # A reopen/edit during slow embedding supersedes this task without publishing it.
        if not self.db.publication_current(job):
            return
        self.index.put(job['question_id'], {'revision': job['revision'], 'active': active,
                                          'record': record, 'vector': vector, 'model': MODEL})
        self.db.complete_publication(job)
        LOG.info('%s question %s revision %s', 'Indexed' if active else 'Withdrew', job['question_id'], job['revision'])

    def start(self):
        self.lock = open(self.db.path.parent / 'publication.lock', 'a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.db.recover_publications()
        self.thread = threading.Thread(target=self.loop, name='approved-question-publisher', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=1)
        if not self.thread.is_alive():
            self.lock.close()

    def loop(self):
        while not self.stopping.is_set():
            try:
                job = self.db.claim_publication()
                if not job:
                    self.stopping.wait(2)
                    continue
                try:
                    self.run(job)
                except Exception as exc:
                    message = str(exc) if isinstance(exc, prepare.PreparationError) else 'Publication failed. Check the pod logs.'
                    LOG.exception('Publication failed for %s revision %s', job['question_id'], job['revision'])
                    self.db.fail_publication(job, message)
            except Exception:
                LOG.exception('Publication queue unavailable')
                self.stopping.wait(5)
