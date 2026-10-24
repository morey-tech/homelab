"""Deterministic reminders. SilverBullet owns schedules; SQLite owns delivery receipts."""
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.request import Request, urlopen

from store import Store, reminder_time, split_page, task_checkbox


def update_section(old, title, heading, content, legacy_name):
    """Refresh one generated level-two section, retaining surrounding user text."""
    old = old or '# ' + title + '\n\n[[index|Home]]\n'
    start = list(re.finditer(r'(?m)^\\?<!-- ' + legacy_name + r':start -->[ \t]*$', old))
    end = list(re.finditer(r'(?m)^\\?<!-- ' + legacy_name + r':end -->[ \t]*$', old))
    if start or end:
        if len(start) != 1 or len(end) != 1 or start[0].start() >= end[0].start():
            raise ValueError('Ambiguous legacy section; refusing to replace page text')
        prefix, suffix = old[:start[0].start()], old[end[0].end():]
        # Legacy suffixes could be free text. Give them their own section so
        # the next heading-based refresh cannot absorb them into generated text.
        if not re.match(r'\s*#{1,2} ', suffix):
            suffix = '## Notes\n\n' + suffix.lstrip('\n')
    else:
        headings = list(re.finditer(r'(?m)^## ' + re.escape(heading) + r'[ \t]*$', old))
        if len(headings) > 1:
            raise ValueError('Duplicate generated heading; refusing to replace page text')
        if headings:
            start_at = headings[0]
            boundary = re.search(r'(?m)^#{1,2} ', old[start_at.end():])
            prefix = old[:start_at.start()]
            suffix = old[start_at.end() + boundary.start():] if boundary else '## Notes\n'
        else:
            prefix, suffix = old, '## Notes\n'
    return prefix.rstrip() + '\n\n## ' + heading + '\n\n' + content.rstrip() + '\n\n' + suffix.lstrip('\n')


class Reminders:
    def __init__(self, database, store, deliver):
        self.db = sqlite3.connect(database, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS deliveries (key TEXT PRIMARY KEY, task_id TEXT, state TEXT, attempts INTEGER, retry_at REAL, detail TEXT)')
        self.store, self.deliver = store, deliver
        self.restored = False

    def restore_receipts(self):
        if self.restored:
            return
        if not self.db.execute('SELECT 1 FROM deliveries LIMIT 1').fetchone():
            saved, _ = self.store.read('System/ReminderReceipts.md')
            if saved:
                rows = json.loads(saved.split('```json\n', 1)[1].split('\n```', 1)[0])
                if not isinstance(rows, list):
                    raise ValueError('Invalid reminder receipt backup')
                for row in rows:
                    if (len(row) != 6 or row[2] not in ('pending', 'sending', 'sent', 'failed', 'cancelled')
                            or not isinstance(row[3], int) or not 0 <= row[3] <= 5):
                        raise ValueError('Invalid reminder receipt backup')
                with self.db:
                    self.db.executemany('INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?, ?, ?, ?)', rows)
        self.restored = True

    def checkpoint(self):
        rows = self.db.execute('SELECT key, task_id, state, attempts, retry_at, detail FROM deliveries ORDER BY key').fetchall()
        saved = '# Reminder delivery receipts\n\nManaged recovery data; do not edit.\n\n```json\n' + json.dumps(rows) + '\n```\n'
        self.store.edit('System/ReminderReceipts.md', lambda _: saved)

    def tick(self, now=None):
        now = now if now is not None else time.time()
        self.restore_receipts()
        tasks = self.store.tasks(include_done=True)  # A failed read aborts delivery.
        active_keys = set()
        for task in tasks:
            if task.get('remind_at') and not task['done']:
                try:
                    at = reminder_time(task['remind_at'])
                    active_keys.add(hashlib.sha256((task['task_id'] + ':' + str(task.get('reminder_id', '')) + ':' + at).encode()).hexdigest())
                except (ValueError, TypeError):
                    pass
        with self.db:
            for (key,) in self.db.execute("SELECT key FROM deliveries WHERE state IN ('pending', 'sending')").fetchall():
                if key not in active_keys:
                    self.db.execute("UPDATE deliveries SET state='cancelled' WHERE key=?", (key,))
        for task in tasks:
            at = task.get('remind_at')
            if not at or task['done']:
                continue
            try:
                at = reminder_time(at)
            except (ValueError, TypeError):
                continue  # Invalid manual edits fail closed; shown on the dashboard.
            due = datetime.fromisoformat(at).timestamp()
            key = hashlib.sha256((task['task_id'] + ':' + str(task.get('reminder_id', '')) + ':' + at).encode()).hexdigest()
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?, 0, 0, ?)',
                                (key, task['task_id'], 'pending', ''))
            state, attempts, retry_at = self.db.execute('SELECT state, attempts, retry_at FROM deliveries WHERE key=?', (key,)).fetchone()
            if state in ('sent', 'failed', 'cancelled') or due > now or retry_at > now:
                continue
            if attempts >= 5:
                with self.db:
                    self.db.execute("UPDATE deliveries SET state='failed', detail='Retry limit reached' WHERE key=?", (key,))
                continue
            # Re-read immediately before sending; a phone edit after this check
            # can still race an in-flight network request (documented boundary).
            latest, _ = self.store.read(task['path'])
            if latest is None:
                continue
            meta, body = split_page(latest)
            checkbox = task_checkbox(body)
            if (not checkbox or checkbox[1] != ' ' or meta.get('task_id') != task['task_id']
                    or str(meta.get('reminder_id', '')) != str(task.get('reminder_id', ''))
                    or meta.get('remind_at') != task.get('remind_at')):
                with self.db:
                    self.db.execute("UPDATE deliveries SET state='cancelled' WHERE key=?", (key,))
                continue
            if now - due > 86400:
                with self.db:
                    self.db.execute("UPDATE deliveries SET state='failed', detail='More than 24 hours overdue' WHERE key=?", (key,))
                continue
            # Persist the attempt before network I/O; restarts retry after the lease.
            attempts += 1
            with self.db:
                self.db.execute("UPDATE deliveries SET state='sending', attempts=?, retry_at=? WHERE key=?",
                                (attempts, now + 120, key))
            # Backup the lease before external delivery. If notes are unavailable,
            # leave it leased and retry later instead of sending without a record.
            self.checkpoint()
            try:
                self.deliver(task)
            except Exception:
                state = 'failed' if attempts >= 5 else 'pending'
                with self.db:
                    self.db.execute('UPDATE deliveries SET state=?, retry_at=?, detail=? WHERE key=?',
                                    (state, now + min(1800, 30 * 2 ** attempts), 'Delivery failed or acknowledgement uncertain', key))
            else:
                with self.db:
                    self.db.execute("UPDATE deliveries SET state='sent', detail='' WHERE key=?", (key,))
        # Schedules removed/changed/completed on the phone disappear from the
        # active set; history remains for audit and duplicate suppression.
        self.dashboard(tasks)
        self.checkpoint()
        self.indexes()

    def indexes(self):
        for title, prefix, heading in [('Inbox', 'Inbox/', 'Captures and notes'),
                                       ('Journal', 'Journal/', 'Journal entries'),
                                       ('Projects', 'Projects/', 'Project pages')]:
            paths = self.store.list_pages(prefix)
            content = '\n'.join('- [[' + p[:-3] + ']]' for p in paths)
            self.store.edit(title + '.md', lambda old: update_section(
                old, title, heading, content, 'managed-index'))

    def dashboard(self, tasks):
        lines = ['| Task | Due | Reminder (Toronto) | Delivery |', '|---|---|---|---|']
        for task in sorted((t for t in tasks if not t['done']), key=lambda t: str(t.get('due') or '9999')):
            rows = self.db.execute('SELECT state, detail FROM deliveries WHERE task_id=? ORDER BY rowid DESC LIMIT 1', (task['task_id'],)).fetchone()
            status = (rows[0] + (': ' + rows[1] if rows[1] else '')) if rows else 'not scheduled'
            at = task.get('remind_at', '')
            if at:
                try:
                    reminder_time(at)
                except (ValueError, TypeError):
                    status = 'invalid reminder time — edit required'
            else:
                status = 'not scheduled'
            title = task['title'].replace('|', '/').replace('[', '(').replace(']', ')')
            lines.append(f"| [[{task['path'][:-3]}|{title}]] | {task.get('due', '')} | {at} | {status} |")
        self.store.edit('Tasks.md', lambda old: update_section(
            old, 'Tasks', 'Open tasks', '\n'.join(lines), 'managed-tasks'))


def deliver_ntfy(task):
    password = Path('/reminder-auth/value').read_text().strip()
    credentials = base64.b64encode(('hermes:' + password).encode()).decode()
    # Generic notification body; personal task content remains in SilverBullet.
    payload = {'topic': 'personal-reminders', 'title': 'Personal reminder',
               'message': 'A task reminder is due. Open your notes to review it.',
               'click': 'https://silverbullet.apps.ocp-mgmt.rh-lab.morey.tech/' + task['path'][:-3]}
    request = Request('http://ntfy.ntfy.svc.cluster.local:8080/', data=json.dumps(payload).encode(),
                      headers={'Authorization': 'Basic ' + credentials, 'Content-Type': 'application/json'})
    with urlopen(request, timeout=20) as response:
        result = json.load(response)
        if not result.get('id') or result.get('topic') != 'personal-reminders':
            raise ValueError('Notification service did not acknowledge delivery')


if __name__ == '__main__':
    os.umask(0o077)
    state = Path('/opt/data/personal-notes')
    state.mkdir(mode=0o700, exist_ok=True)
    engine = Reminders(state / 'reminders.sqlite', Store(), deliver_ntfy)
    while True:
        try:
            engine.tick()
            (state / 'worker-heartbeat').write_text(str(time.time()))
        except Exception:
            print('Reminder reconciliation failed; no success assumed', flush=True)
        time.sleep(30)
