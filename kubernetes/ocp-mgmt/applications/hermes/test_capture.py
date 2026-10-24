from enum import Enum
import importlib.util
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
