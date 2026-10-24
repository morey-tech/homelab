from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).parent / 'personal-notes'))
from store import Store, digest, reminder_time, split_page, page
from reminders import Reminders, update_section


class MemoryStore(Store):
    def __init__(self):
        self.files = {}
        self.revisions = {}
        self.race = None
        self.fail_path = None

    def request(self, method, path='', body=None, revision=None):
        import json
        if self.fail_path == path:
            raise OSError('service unavailable')
        if method == 'GET' and not path:
            return json.dumps([{'name': name} for name in self.files]), None
        if method == 'GET':
            if path not in self.files:
                raise HTTPError('',404,'missing',{},None)
            return self.files[path], str(self.revisions[path])
        if self.race:
            race, self.race = self.race, None
            race(self, path)
        if revision != (str(self.revisions[path]) if path in self.files else None):
            raise HTTPError('',412,'conflict',{},None)
        self.files[path] = body
        self.revisions[path] = self.revisions.get(path,0) + 1
        return '', str(self.revisions[path])


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.capture = self.store.capture('signal:owner:123', '2026-10-24T15:00:00+00:00', 'Original voice transcript')
        self.ops = [dict(action='project',project='Garage',content='The opening is 82 centimetres.'),
                    dict(action='create_task',title='Check fitting size',project='Garage',remind_at='2026-10-25T10:00:00-04:00'),
                    dict(action='journal',date='2026-10-24',content='Today was productive; too long troubleshooting DNS.')]

    def test_multi_intent_and_duplicate_are_idempotent(self):
        self.assertTrue(self.store.apply(self.capture,self.ops)['ok'])
        before = dict(self.store.files)
        self.assertTrue(self.store.apply(self.capture,self.ops)['ok'])
        self.assertEqual(before,self.store.files)
        task = self.store.tasks()[0]
        self.assertEqual(task['due'],'')
        self.assertEqual(task['project'],'Garage')
        self.assertEqual(len(self.store.tasks()),1)

    def test_capture_preserves_first_transcript(self):
        again = self.store.capture('signal:owner:123','2026-10-24T16:00:00+00:00','Different transcription')
        self.assertEqual(again,self.capture)
        self.assertIn('Original voice transcript',self.store.get_capture(again)[1])

    def test_conflict_retries_without_losing_phone_edits(self):
        self.store.edit('Projects/Garage.md',lambda _: '# Garage\n')
        def race(store,path):
            if path == 'Inbox/Plans/' + self.capture + '.md':
                store.race = race
                return
            store.files[path] += '\nPhone edit\n'
            store.revisions[path] += 1
        self.store.race = race
        self.assertTrue(self.store.apply(self.capture,self.ops)['ok'])
        self.assertIn('Phone edit',self.store.files['Projects/Garage.md'])
        self.assertIn('82 centimetres',self.store.files['Projects/Garage.md'])

    def test_partial_failure_retries_original_plan(self):
        self.store.fail_path = 'Journal/2026-10-24.md'
        result = self.store.apply(self.capture,self.ops)
        self.assertFalse(result['ok'])
        self.assertEqual([r['ok'] for r in result['results']],[True,True,False])
        self.store.fail_path = None
        self.assertTrue(self.store.apply(self.capture,self.ops)['ok'])
        self.assertEqual(len(self.store.tasks()),1)
        with self.assertRaises(ValueError):
            self.store.apply(self.capture,[dict(action='note',content='Changed plan')])

    def test_no_write_without_capture(self):
        before = dict(self.store.files)
        with self.assertRaises(ValueError):
            self.store.apply('a'*32,self.ops)
        self.assertEqual(self.store.files,before)

    def test_timezone_offsets_and_dst(self):
        for valid in ['2026-07-01T10:00:00-04:00','2026-12-01T10:00:00-05:00']:
            self.assertEqual(reminder_time(valid),valid)
        for invalid in ['2026-03-08T02:30:00-05:00','2026-07-01T10:00:00-05:00','2026-10-25T10:00:00']:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                reminder_time(invalid)

    def test_path_escape_rejected(self):
        result = self.store.apply(self.capture,[dict(action='project',project='../config',content='bad')])
        self.assertFalse(result['ok'])
        self.assertNotIn('Projects/../config.md',self.store.files)


class ManagedSectionTests(unittest.TestCase):
    def test_migrates_legacy_markers_and_preserves_surrounding_notes(self):
        for escape in ['', '\\']:
            with self.subTest(escape=escape):
                old = ('# Tasks\n\nIntro from the phone\n\n' + escape +
                       '<!-- managed-tasks:start -->\n## Open tasks\n\nOld table\n' + escape +
                       '<!-- managed-tasks:end -->\n\nKeep this footer\n')
                updated = update_section(old, 'Tasks', 'Open tasks', 'New table', 'managed-tasks')
                self.assertNotIn('managed-tasks', updated)
                self.assertNotIn('Old table', updated)
                self.assertEqual(updated.count('## Open tasks'), 1)
                self.assertIn('Intro from the phone', updated)
                self.assertIn('## Notes\n\nKeep this footer', updated)
                self.assertEqual(update_section(updated, 'Tasks', 'Open tasks',
                                                'New table', 'managed-tasks'), updated)

    def test_refresh_keeps_following_sections(self):
        old = '# Tasks\n\n## Open tasks\n\nOld table\n\n## My notes\n\nKeep this\n### Detail\nAlso keep\n'
        updated = update_section(old, 'Tasks', 'Open tasks', 'New table', 'managed-tasks')
        self.assertTrue(updated.endswith('## My notes\n\nKeep this\n### Detail\nAlso keep\n'))
        self.assertNotIn('Old table', updated)
        self.assertNotIn('## Notes', updated)

    def test_ambiguous_boundaries_fail_without_replacing_text(self):
        for old in ['<!-- managed-tasks:start -->\nPersonal text',
                    '<!-- managed-tasks:end -->\n<!-- managed-tasks:start -->',
                    '## Open tasks\nOne\n## Open tasks\nTwo']:
            with self.subTest(old=old), self.assertRaises(ValueError):
                update_section(old, 'Tasks', 'Open tasks', 'New table', 'managed-tasks')


class ReminderTests(unittest.TestCase):
    def setUp(self):
        NotesTests.setUp(self)
        self.store.apply(self.capture,self.ops)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name)/'receipts.sqlite')
        self.sent = []
        self.engine = Reminders(self.database,self.store,self.sent.append)
        self.addCleanup(lambda:self.engine.db.close())
        self.now = datetime.fromisoformat('2026-10-25T10:00:00-04:00').timestamp()

    def test_worker_migrates_dashboard_and_indexes_without_duplicates(self):
        for title, marker in [('Tasks', 'managed-tasks'), ('Inbox', 'managed-index'),
                              ('Journal', 'managed-index'), ('Projects', 'managed-index')]:
            self.store.edit(title + '.md', lambda _, title=title, marker=marker:
                '# ' + title + '\n\n<!-- ' + marker + ':start -->\nOld list\n<!-- ' +
                marker + ':end -->\n\nMy handwritten notes\n')
        self.engine.tick(self.now)
        pages = {title: self.store.read(title + '.md')[0] for title in ['Tasks','Inbox','Journal','Projects']}
        for text in pages.values():
            self.assertNotIn('<!-- managed-', text)
            self.assertNotIn('Old list', text)
            self.assertIn('## Notes\n\nMy handwritten notes', text)
        self.assertIn('Check fitting size', pages['Tasks'])
        self.assertIn('[[Projects/Garage]]', pages['Projects'])
        self.engine.tick(self.now + 30)
        for title, text in pages.items():
            self.assertEqual(self.store.read(title + '.md')[0], text)

    def test_restart_does_not_resend(self):
        self.engine.tick(self.now)
        self.assertEqual(len(self.sent),1)
        self.engine.db.close()
        self.engine = Reminders(self.database,self.store,self.sent.append)
        self.engine.tick(self.now+60)
        self.assertEqual(len(self.sent),1)

    def test_restore_receipts_after_database_loss(self):
        self.engine.tick(self.now)
        restored = Reminders(':memory:', self.store, self.sent.append)
        self.addCleanup(restored.db.close)
        restored.tick(self.now+60)
        self.assertEqual(len(self.sent), 1)

    def test_due_change_does_not_resend_reminder(self):
        self.engine.tick(self.now)
        task = self.store.tasks()[0]
        capture = self.store.capture('signal:owner:124', '2026-10-25T15:00:00+00:00', 'Change due date only')
        self.assertTrue(self.store.apply(capture, [dict(action='reschedule_task', task_id=task['task_id'], due='2026-10-28')])['ok'])
        self.engine.tick(self.now+60)
        self.assertEqual(len(self.sent), 1)

    def test_receipt_failure_prevents_delivery(self):
        self.store.fail_path = 'System/ReminderReceipts.md'
        with self.assertRaises(OSError):
            self.engine.tick(self.now)
        self.assertEqual(self.sent, [])

    def test_phone_completion_suppresses_pending_reminder(self):
        self.engine.tick(self.now-30)
        task = self.store.tasks()[0]
        self.store.edit(task['path'],lambda text:text.replace('- [ ]','- [x]'))
        self.engine.tick(self.now)
        self.assertEqual(self.sent,[])
        self.assertEqual(self.engine.db.execute('SELECT state FROM deliveries').fetchone()[0],'cancelled')

    def test_manual_reschedule_changes_delivery(self):
        self.engine.tick(self.now-30)
        task = self.store.tasks()[0]
        self.store.edit(task['path'],lambda text:text.replace('10:00:00-04:00','11:00:00-04:00'))
        self.engine.tick(self.now)
        self.assertEqual(self.sent,[])
        self.engine.tick(self.now+3600)
        self.assertEqual(len(self.sent),1)

    def test_completion_between_scan_and_delivery_with_open_subtask(self):
        tasks = self.store.tasks(include_done=True)
        self.store.edit(tasks[0]['path'], lambda text: text.replace('- [ ]', '- [x]') + '\n- [ ] Follow-up\n')
        with patch.object(self.store, 'tasks', return_value=tasks):
            self.engine.tick(self.now)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.engine.db.execute('SELECT state FROM deliveries').fetchone()[0], 'cancelled')

    def test_changed_task_identity_between_scan_and_delivery(self):
        tasks = self.store.tasks(include_done=True)
        self.store.edit(tasks[0]['path'], lambda text: text.replace('task_id: ' + tasks[0]['task_id'], 'task_id: ' + 'f' * 32))
        with patch.object(self.store, 'tasks', return_value=tasks):
            self.engine.tick(self.now)
        self.assertEqual(self.sent, [])

    def test_completed_task_with_open_subtask_cannot_be_scheduled(self):
        task = self.store.tasks()[0]
        self.store.edit(task['path'], lambda text: text.replace('- [ ]', '- [x]') + '\n- [ ] Follow-up\n')
        capture = self.store.capture('signal:owner:125', '2026-10-25T15:00:00+00:00', 'Remind again')
        result = self.store.apply(capture, [dict(action='schedule_reminder', task_id=task['task_id'], remind_at='2026-10-26T10:00:00-04:00')])
        self.assertFalse(result['ok'])

    def test_failures_are_bounded_and_recorded(self):
        self.engine.deliver = lambda task: (_ for _ in ()).throw(OSError('offline'))
        for i in range(10):
            self.engine.tick(self.now+i*2000)
        state,attempts = self.engine.db.execute('SELECT state,attempts FROM deliveries').fetchone()
        self.assertEqual((state,attempts),('failed',5))
        self.assertEqual(self.sent,[])

    def test_unavailable_notes_never_sends(self):
        self.store.fail_path = ''
        with self.assertRaises(OSError):
            self.engine.tick(self.now)
        self.assertEqual(self.sent,[])

if __name__ == '__main__':
    unittest.main()
