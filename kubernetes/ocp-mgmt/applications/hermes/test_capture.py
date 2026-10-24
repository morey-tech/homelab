from enum import Enum
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock

from test_personal_notes import MemoryStore

spec = importlib.util.spec_from_file_location('notes_plugin_test', Path(__file__).parent/'personal-notes/__init__.py',
                                            submodule_search_locations=[str(Path(__file__).parent/'personal-notes')])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class Platform(Enum):
    SIGNAL = 'signal'


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.sender = AsyncMock()
        self.gateway = SimpleNamespace(adapters={Platform.SIGNAL: self.sender})
        self.event = SimpleNamespace(source=SimpleNamespace(platform=Platform.SIGNAL, chat_type='dm',
            chat_id='+15555550123', user_id='+15555550123'), text='', media_urls=['/tmp/test.ogg'],
            media_types=['audio/ogg'], raw_message={'timestamp_ms': 1792868400000})

    async def invoke(self):
        with patch.dict(plugin.os.environ, {'SIGNAL_ACCOUNT': '+15555550123'}), patch.object(plugin, 'Store', return_value=self.store):
            return await plugin.capture_input(self.event, self.gateway)

    async def test_original_voice_saved_before_rewrite_and_duplicate_avoids_stt(self):
        with patch.object(plugin, 'transcribe', return_value=('82 centimetres', True)) as stt:
            result = await self.invoke()
            self.assertEqual(result['action'], 'rewrite')
            self.assertIn('confidence is low', result['text'])
            captures = self.store.list_pages('Inbox/Captures/')
            self.assertEqual(len(captures), 1)
            self.assertIn('82 centimetres', self.store.read(captures[0])[0])
            self.event.media_urls = ['/tmp/test.ogg']
            self.event.media_types = ['audio/ogg']
            await self.invoke()
            self.assertEqual(stt.call_count, 1)
            self.assertEqual(self.event.message_id, '1792868400000')

    async def test_unavailable_transcription_drops_turn_and_reports_failure(self):
        with patch.object(plugin, 'transcribe', side_effect=OSError('offline')):
            self.assertEqual((await self.invoke())['action'], 'skip')
        self.assertFalse(self.store.files)
        self.sender.send.assert_awaited_once()

    async def test_other_sender_is_rejected_before_stt_or_write(self):
        self.event.source.user_id = '+15555550999'
        with patch.object(plugin, 'transcribe') as stt:
            self.assertEqual((await self.invoke())['action'], 'skip')
            stt.assert_not_called()
        self.sender.send.assert_not_awaited()
        self.assertFalse(self.store.files)


class CaptureRetryTests(unittest.TestCase):
    def test_bad_reference_then_corrected_retry_creates_task_not_note(self):
        # Keep the plugin's package-local Store/CaptureError classes together;
        # replace only HTTP storage with the shared in-memory transport.
        class PluginMemoryStore(plugin.Store):
            __init__ = MemoryStore.__init__
            request = MemoryStore.request

        store = PluginMemoryStore()
        capture = store.capture('signal:owner:retry', '2026-10-24T18:32:32+00:00',
                                'I want to map the basement outlets to their circuits')
        operations = [{'action': 'create_task', 'title': 'Map basement outlets to circuits'}]
        before = dict(store.files)
        invalid_ids = [capture[:15] + '9' + capture[15:], 'a' * 32, None]
        with patch.object(plugin, 'Store', return_value=store):
            for invalid in invalid_ids:
                with self.subTest(capture_id=invalid):
                    result = json.loads(plugin.handle({'action': 'apply_capture',
                        'capture_id': invalid, 'operations': operations}))
                    self.assertFalse(result['ok'])
                    self.assertEqual(result['error'], 'capture_reference_error')
                    self.assertFalse(result['actions_applied'])
                    self.assertIn('SAME operations unchanged', result['retry_instruction'])
                    self.assertEqual(store.files, before)
            args = {'action': 'apply_capture', 'capture_id': capture, 'operations': operations}
            self.assertTrue(json.loads(plugin.handle(args))['ok'])
            written = dict(store.files)
            self.assertTrue(json.loads(plugin.handle(args))['ok'])
            self.assertEqual(store.files, written)
        tasks = store.tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['title'], operations[0]['title'])
        self.assertEqual(tasks[0]['due'], '')
        self.assertEqual(tasks[0]['remind_at'], '')
        self.assertEqual(tasks[0]['project'], '')
        self.assertFalse(store.list_pages('Inbox/Notes/'))
