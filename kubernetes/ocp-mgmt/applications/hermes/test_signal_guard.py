import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent / 'personal-notes'))
from signal_guard import install, MARKER


class SignalGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        class Adapter:
            MAX_MESSAGE_LENGTH = 2000
            _account_normalized = '+15555550123'
            _recipient_uuid_by_number = {'+15555550123': 'own-uuid'}
            async def _rpc(self, method, params, *args, **kwargs):
                return params
            async def _handle_envelope(self, payload):
                return payload
        self.adapter_class = Adapter
        install(Adapter)
        self.adapter = Adapter()

    def payload(self, message='my note', destination='+15555550123'):
        return {'envelope': {'sourceNumber': '+15555550123', 'timestamp': 999,
                            'syncMessage': {'sentMessage': {'timestamp': 123, 'message': message,
                                                           'destinationNumber': destination}}}}

    async def test_original_timestamp_and_echo_filter_survive_restart(self):
        sent = await self.adapter._rpc('send', {'recipient': ['own-uuid'], 'message': 'Saved'})
        restarted = self.adapter_class()
        self.assertIsNone(await restarted._handle_envelope(self.payload(sent['message'])))
        result = await restarted._handle_envelope(self.payload())
        self.assertEqual(result['envelope']['timestamp'], 123)

    async def test_other_chats_are_rejected_before_attachment_download(self):
        self.assertIsNone(await self.adapter._handle_envelope(self.payload(destination='+15555550999')))
        with self.assertRaises(ValueError):
            await self.adapter._rpc('send', {'recipient': ['+15555550999'], 'message': 'wrong recipient'})

    async def test_each_chunk_is_marked_and_install_is_idempotent(self):
        install(self.adapter_class)
        self.assertEqual(self.adapter.MAX_MESSAGE_LENGTH, 2000-len(MARKER))
        for chunk in ['first', 'second']:
            result = await self.adapter._rpc('send', {'recipient': ['own-uuid'], 'message': chunk})
            self.assertEqual(result['message'], chunk+MARKER)
