"""Small compatibility shim for the pinned v0.22.5 Signal adapter.

Upstream's echo timestamps are volatile. Mark every outbound chunk before RPC,
so reconnects and crashes between send and acknowledgement cannot create loops.
Keep the marker visible: it identifies assistant replies in Note to Self.
"""
MARKER = '\n\n[Hermes reply]'


def install(adapter_class=None):
    if adapter_class is None:
        from plugins.platforms.signal.adapter import SignalAdapter
        adapter_class = SignalAdapter
    if getattr(adapter_class, '_personal_notes_guard', False):
        return
    original_rpc = adapter_class._rpc
    original_envelope = adapter_class._handle_envelope

    async def rpc(self, method, params, *args, **kwargs):
        if method == 'send':
            recipients = params.get('recipient', [])
            allowed = {self._account_normalized,
                       self._recipient_uuid_by_number.get(self._account_normalized)} - {None, ''}
            if params.get('groupId') or not recipients or any(r not in allowed for r in recipients):
                raise ValueError('Personal notes may reply only to Note to Self')
            params = dict(params)
            params['message'] = (params.get('message') or '') + MARKER
        return await original_rpc(self, method, params, *args, **kwargs)

    async def envelope(self, payload):
        data = payload.get('envelope', payload)
        sent = (data.get('syncMessage') or {}).get('sentMessage') or {}
        source = data.get('sourceNumber') or data.get('source')
        destination = sent.get('destinationNumber') or sent.get('destination')
        if (not self._account_normalized or source != self._account_normalized
                or destination != self._account_normalized or sent.get('groupInfo')):
            return  # Reject other chats before downloading any attachments.
        if (sent.get('message') or '').endswith(MARKER):
            return
        # Use the original message ID, not a sync envelope's delivery timestamp.
        data = {**data, 'timestamp': sent.get('timestamp')}
        return await original_envelope(self, {'envelope': data})

    adapter_class._rpc = rpc
    adapter_class._handle_envelope = envelope
    adapter_class.MAX_MESSAGE_LENGTH -= len(MARKER)
    adapter_class._personal_notes_guard = True
