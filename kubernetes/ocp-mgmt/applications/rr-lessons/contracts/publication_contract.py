"""Versioned wire contract shared by the review publisher and LanceDB service."""
import hashlib
import json
import math
import re

MODEL = {
    'name': 'qwen3-embedding-4b', 'repository': 'Qwen/Qwen3-Embedding-4B',
    'revision': '5cf2132abc99cad020ac570b19d031efec650f2b', 'dimensions': 2560,
    'input_format': 'approved-question-v1', 'normalization': 'l2',
}
TABLE = 'approved_questions_qwen3_4b_v1'
MAX_BODY = 512 * 1024


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9:_-]{1,160}', value) is not None


def normalized_vector(value):
    if (not isinstance(value, list) or len(value) != MODEL['dimensions']
            or any(type(n) not in (int, float) or not math.isfinite(n) for n in value)):
        raise ValueError('Embedding has invalid dimensions or non-finite values')
    norm = math.sqrt(sum(n * n for n in value))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError('Embedding must have a finite, nonzero norm')
    return [n / norm for n in value]


def validate_mutation(question_id, body):
    if not valid_id(question_id) or not isinstance(body, dict) or set(body) != {'revision', 'active', 'record', 'vector', 'model'}:
        raise ValueError('Invalid publication request')
    if type(body['revision']) is not int or body['revision'] < 1 or type(body['active']) is not bool:
        raise ValueError('Invalid publication revision or action')
    if body['model'] != MODEL:
        raise ValueError('Embedding model or revision does not match this table')
    if not body['active']:
        if body['record'] is not None or body['vector'] is not None:
            raise ValueError('Withdrawal must not contain a record or vector')
        return
    record = body['record']
    if (not isinstance(record, dict) or record.get('question_id') != question_id
            or record.get('review_revision') != body['revision'] or record.get('approved_for_retrieval') is not True
            or record.get('productionApproved') is not False):
        raise ValueError('Record must identify the approved review revision')
    question = record.get('question')
    if not isinstance(question, str) or not question.strip() or len(question) > 1000:
        raise ValueError('Approved question is missing or too long')
    if record.get('embedding_text') != question or record.get('embedding_input_sha256') != fingerprint(question):
        raise ValueError('Embedding input must match the approved question')
    if not isinstance(record.get('outline'), list) or not record['outline'] or not record.get('passages'):
        raise ValueError('Approved outline and source passages are required')
    normalized_vector(body['vector'])
