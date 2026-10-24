"""SilverBullet is authoritative; writes use revision checks and capture operation IDs."""
from datetime import datetime, date, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo('America/Toronto')


class CaptureError(ValueError):
    """A capture reference failed before any plan or action was written."""


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def load_yaml(text):
    try:
        from ruamel.yaml import YAML
        return YAML(typ='safe').load(text)
    except ImportError:
        import yaml
        return yaml.safe_load(text)


def dump_yaml(value):
    # JSON is also YAML, but conventional front matter stays easier to edit.
    try:
        from ruamel.yaml import YAML
        output = io.StringIO()
        YAML().dump(value, output)
        return output.getvalue()
    except ImportError:
        import yaml
        return yaml.safe_dump(value, sort_keys=False)


def split_page(text):
    if not text.startswith('---\n'):
        return {}, text
    head, body = text[4:].split('\n---\n', 1)
    meta = load_yaml(head)
    if not isinstance(meta, dict):
        raise ValueError('Invalid page metadata')
    meta = {key: (value.isoformat() if isinstance(value, (datetime, date)) else value) for key, value in meta.items()}
    return meta, body


def page(meta, body):
    return '---\n' + dump_yaml(meta).rstrip() + '\n---\n' + body


def task_checkbox(body):
    """Only the first top-level checkbox controls the task's state."""
    return re.search(r'^- \[([ xX])\] (.+)$', body, re.M)


def reminder_time(value):
    """Require an offset matching Toronto; reject nonexistent DST wall times."""
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError('Reminder needs an explicit America/Toronto UTC offset')
    local = parsed.astimezone(TORONTO)
    if parsed.replace(tzinfo=None) != local.replace(tzinfo=None) or parsed.utcoffset() != local.utcoffset():
        raise ValueError('Reminder time or UTC offset does not match America/Toronto')
    return local.isoformat(timespec='seconds')


def valid_path(path):
    if not isinstance(path, str) or not path.endswith('.md') or path.startswith('/'):
        raise ValueError('Expected a relative Markdown page path')
    if any(p in ('', '.', '..') or p.startswith('.') for p in path.split('/')) or '\\' in path:
        raise ValueError('Invalid page path')
    if len(path) > 240:
        raise ValueError('Page path is too long')
    return path


class Store:
    def __init__(self, url=None, token=None, opener=urlopen):
        self.url = url or 'http://silverbullet.silverbullet.svc.cluster.local:3000'
        self.token = token
        self.opener = opener

    def request(self, method, path='', body=None, revision=None):
        token = self.token if self.token is not None else Path('/notes-auth/value').read_text().strip()
        headers = {'Authorization': 'Bearer ' + token, 'X-Sync-Mode': 'true'}
        if body is not None:
            headers['Content-Type'] = 'text/markdown; charset=utf-8'
        if method == 'PUT':
            headers['If-Match' if revision else 'If-None-Match'] = revision or '*'
        request = Request(self.url + '/.fs' + ('/' + quote(path, safe='/') if path else ''),
                          data=body.encode() if body is not None else None, headers=headers, method=method)
        with self.opener(request, timeout=15) as response:
            content = response.read(2 * 1024 * 1024 + 1)
            if len(content) > 2 * 1024 * 1024:
                raise ValueError('Page exceeds the 2 MiB tool limit')
            return content.decode(), response.headers.get('ETag')

    def read(self, path):
        valid_path(path)
        try:
            text, revision = self.request('GET', path)
            if not revision:
                raise ValueError('Server did not supply a revision; refusing an unsafe edit')
            return text, revision
        except HTTPError as error:
            if error.code == 404:
                return None, None
            raise

    def edit(self, path, transform):
        for _ in range(5):
            text, revision = self.read(path)
            replacement = transform(text)
            if replacement == text:
                return path
            try:
                self.request('PUT', path, replacement, revision)
                return path
            except HTTPError as error:
                if error.code != 412:
                    raise
        raise ValueError('Page kept changing; no overwrite performed, please retry')

    def list_pages(self, prefix):
        files = json.loads(self.request('GET')[0])
        return sorted(f['name'] for f in files if f['name'].startswith(prefix) and f['name'].endswith('.md'))

    def capture(self, source_id, timestamp, transcript, uncertain=False):
        key = digest(source_id)
        path = f'Inbox/Captures/{key}.md'
        content = page(dict(tags=['capture'], capture_id=key, source_id=source_id,
                            captured_at=timestamp, timezone='America/Toronto', uncertain=uncertain), '\n' + transcript + '\n')
        # Existing captures are immutable even if a second STT attempt differs.
        self.edit(path, lambda old: old if old is not None else content)
        return key

    def get_capture(self, key):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{32}', key):
            raise CaptureError('Invalid capture ID: copy the exact 32-character capture_id from the current input')
        text, _ = self.read(f'Inbox/Captures/{key}.md')
        if text is None:
            raise CaptureError('Capture not found: check the capture_id against the current input; do not invent one')
        return split_page(text)

    def tasks(self, project=None, include_done=False):
        result = []
        for path in self.list_pages('Tasks/'):
            text, _ = self.read(path)
            if text is None:
                continue
            meta, body = split_page(text)
            match = task_checkbox(body)
            if not match or not meta.get('task_id'):
                continue
            done = match[1].lower() == 'x'
            if (include_done or not done) and (not project or meta.get('project') == project):
                result.append({**meta, 'path': path, 'title': match[2], 'done': done})
        return result

    def apply(self, capture_id, operations):
        self.get_capture(capture_id)
        if not isinstance(operations, list) or not 1 <= len(operations) <= 20:
            raise ValueError('Expected 1–20 operations')
        # Freeze the complete plan before any effects, so retries cannot invent
        # new operation IDs or reinterpret an already partly applied message.
        plan_path = f'Inbox/Plans/{capture_id}.md'
        plan_text = page(dict(tags=['capture-plan'], capture=capture_id),
                         '\n```json\n' + json.dumps(operations, ensure_ascii=False, indent=2) + '\n```\n')
        self.edit(plan_path, lambda old: old if old is not None else plan_text)
        stored = self.read(plan_path)[0]
        planned = json.loads(stored.split('```json\n', 1)[1].split('\n```', 1)[0])
        if operations != planned:
            raise ValueError('This capture already has a plan; use its original plan or a new follow-up capture')
        results = []
        for index, operation in enumerate(planned):
            try:
                path = self.apply_one(capture_id, index, operation)
                results.append({'ok': True, 'path': path,
                                'url': 'https://silverbullet.apps.ocp-mgmt.rh-lab.morey.tech/' + quote(path[:-3], safe='/'),
                                'remind_at': operation.get('remind_at')})
            except Exception as error:
                # Never claim the rest succeeded or expose HTTP headers/tokens.
                results.append({'ok': False, 'operation': index, 'error': type(error).__name__,
                                'detail': str(error) if isinstance(error, ValueError) else 'Service request failed; retry the same plan'})
                break
        return {'ok': len(results) == len(planned) and all(r['ok'] for r in results), 'results': results,
                'remaining': len(planned) - len(results)}

    def apply_one(self, capture, index, op):
        key = digest(capture + ':' + str(index))
        marker = f'<!-- capture-operation:{key} -->'
        action = op.get('action')
        content = op.get('content', '')
        if not isinstance(content, str) or len(content) > 30000:
            raise ValueError('Content must be text under 30,000 characters')
        citation = f'[[Inbox/Captures/{capture}|Source capture]]'
        if action in ('note', 'journal', 'project'):
            if action == 'note':
                path = f'Inbox/Notes/{key}.md'
            elif action == 'journal':
                day = date.fromisoformat(op['date']).isoformat()
                path = f'Journal/{day}.md'
            else:
                path = valid_path('Projects/' + op['project'] + '.md')
            if not content.strip():
                raise ValueError('Empty note content')
            return self.edit(path, lambda old: old if old and marker in old else
                             (old or '# ' + path.rsplit('/', 1)[-1][:-3] + '\n') +
                             '\n' + content + '\n\n' + citation + '\n' + marker + '\n')
        if action == 'create_task':
            title = op.get('title', '').strip()
            if not title or '\n' in title:
                raise ValueError('Task requires a single-line title')
            due = date.fromisoformat(op['due']).isoformat() if op.get('due') else ''
            at = reminder_time(op['remind_at']) if op.get('remind_at') else ''
            meta = dict(tags=['personal-task'], task_id=key, due=due, remind_at=at,
                        reminder_id=key, project=op.get('project', ''), capture=capture)
            path = f'Tasks/{key}.md'
            return self.edit(path, lambda old: old if old is not None else page(
                meta, f'\n# {title}\n\n- [ ] {title}\n\n{content}\n\n{citation}\n{marker}\n'))
        if action not in ('complete_task', 'reschedule_task', 'schedule_reminder', 'cancel_reminder', 'snooze_reminder'):
            raise ValueError('Unsupported action')
        task_id = op.get('task_id', '')
        if not re.fullmatch('[a-f0-9]{32}', task_id):
            raise ValueError('Use an existing stable task ID from list_tasks')
        path = f'Tasks/{task_id}.md'
        def update(old):
            if old is None:
                raise ValueError('Task no longer exists')
            if marker in old:
                return old
            meta, body = split_page(old)
            if meta.get('task_id') != task_id:
                raise ValueError('Task ID does not match its page')
            checkbox = task_checkbox(body)
            if action == 'complete_task':
                if not checkbox:
                    raise ValueError('Task checkbox is missing')
                body = body[:checkbox.start(1)] + 'x' + body[checkbox.end(1):]
                meta['remind_at'] = ''
            elif action == 'cancel_reminder':
                meta['remind_at'] = ''
            elif action == 'reschedule_task':
                meta['due'] = date.fromisoformat(op['due']).isoformat() if op.get('due') else ''
            else:
                if not checkbox or checkbox[1] != ' ':
                    raise ValueError('Cannot schedule a reminder for a completed task')
                meta['remind_at'] = reminder_time(op['remind_at'])
            if action != 'reschedule_task':
                meta['reminder_id'] = key
            return page(meta, body.rstrip() + '\n\n' + citation + '\n' + marker + '\n')
        return self.edit(path, update)
