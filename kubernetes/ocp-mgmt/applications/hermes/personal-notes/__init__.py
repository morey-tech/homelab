"""Pinned Hermes v0.22.5 hooks: capture before the agent, then expose revision-safe tools."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .store import Store, digest, TORONTO

BASE_URL = 'https://maas.apps.ocp-mgmt.rh-lab.morey.tech/inference-server/local-llm/v1'


def transcribe(path):
    from openai import OpenAI
    if not 0 < Path(path).stat().st_size <= 15 * 1024 * 1024:
        raise ValueError('Audio must be between 1 byte and 15 MiB')
    with OpenAI(api_key=Path('/maas/MAAS_API_KEY').read_text().strip(),
                base_url=BASE_URL, timeout=140, max_retries=0) as client:
        with open(path, 'rb') as audio:
            result = client.audio.transcriptions.create(model='whisper-1', file=audio, response_format='json')
    if not result.text.strip():
        raise ValueError('No speech was recognized; please repeat the voice note')
    return result.text, bool((result.model_extra or {}).get('uncertain'))


async def capture_input(event, gateway, **_):
    source = event.source
    if not source or not source.platform or source.platform.value != 'signal':
        return None
    account = os.environ.get('SIGNAL_ACCOUNT', '')
    # This hook runs BEFORE Hermes authorization. Perform a strict own-account
    # DM check before reading audio, writing notes, or replying.
    if not account or source.chat_type != 'dm' or source.chat_id != account or source.user_id != account:
        return {'action': 'skip', 'reason': 'Note to Self only'}
    if (event.text or '').startswith('/'):
        return None
    try:
        raw = event.raw_message or {}
        stamp = raw.get('timestamp_ms')
        if not isinstance(stamp, int) or stamp <= 0:
            raise ValueError('Signal source timestamp is missing')
        source_id = 'signal:' + account + ':' + str(stamp)
        capture_id = digest(source_id)
        # v0.22.5 does not fill message_id for Signal. Preserve its native
        # millisecond ID for the gateway's admission/delivery ledger as well.
        event.message_id = str(stamp)
        store = Store()
        existing, _revision = await asyncio.to_thread(store.read, f'Inbox/Captures/{capture_id}.md')
        uncertain = False
        if existing is None:
            transcript = event.text or ''
            for path, media_type in zip(event.media_urls, event.media_types):
                if media_type.startswith('audio/'):
                    text, low_confidence = await asyncio.to_thread(transcribe, path)
                    uncertain |= low_confidence
                    transcript += ('\n\n' if transcript else '') + text
            if not transcript.strip():
                raise ValueError('Send a text or voice note')
            timestamp = datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()
            await asyncio.to_thread(store.capture, source_id, timestamp, transcript, uncertain)
        # Read the immutable original, including after a duplicate delivery.
        metadata, transcript = await asyncio.to_thread(store.get_capture, capture_id)
        uncertain = bool(metadata.get('uncertain'))
        event.media_urls = []
        event.media_types = []
        local = datetime.fromisoformat(metadata['captured_at']).astimezone(TORONTO)
        context = (f'Original input saved as capture {capture_id}. Source time: {local.isoformat()}; '
                   'timezone America/Toronto. Use the personal_notes tool for all durable notes/tasks. '
                   'Inspect Inbox/Plans/' + capture_id + '.md before retrying an existing plan. '
                   'Do not claim a write or reminder succeeded unless its tool result says ok. '
                   'Keep task due dates separate from reminder times. Ask about material ambiguity. ')
        if uncertain:
            context += 'Transcription confidence is low: ask before acting on ambiguous measurements or dates. '
        return {'action': 'rewrite', 'text': context + '\n\nOriginal input:\n' + transcript}
    except Exception:
        # No hosted or on-pod STT fallback. Failure must not become an agent
        # turn claiming success. Keep error details and credentials out of chat.
        adapter = gateway.adapters.get(source.platform)
        if adapter:
            try:
                await adapter.send(source.chat_id, 'I could not transcribe or save this capture. No requested actions were applied. Please retry.')
            except Exception:
                pass
        return {'action': 'skip', 'reason': 'Capture unavailable'}


def handle(args, **_):
    try:
        store = Store()
        action = args.get('action')
        if action == 'apply_capture':
            result = store.apply(args['capture_id'], args['operations'])
        elif action == 'list_tasks':
            result = {'ok': True, 'tasks': store.tasks(args.get('project'), args.get('include_done', False))}
        elif action == 'read_page':
            text, revision = store.read(args['path'])
            result = {'ok': text is not None, 'content': text, 'revision': revision}
        elif action == 'find_pages':
            prefix = args.get('prefix', '')
            if prefix not in ('Inbox/', 'Journal/', 'Projects/', 'Tasks/'):
                raise ValueError('Choose Inbox/, Journal/, Projects/, or Tasks/')
            result = {'ok': True, 'pages': store.list_pages(prefix)}
        else:
            raise ValueError('Unsupported tool action')
        return json.dumps(result, ensure_ascii=False)
    except Exception as error:
        return json.dumps({'ok': False, 'error': type(error).__name__,
                           'detail': str(error) if isinstance(error, ValueError) else 'Operation failed; do not claim success'})


def register(ctx):
    from .signal_guard import install
    install()
    ctx.register_hook('pre_gateway_dispatch', capture_input)
    ctx.register_tool(name='personal_notes', toolset='personal_notes', handler=handle,
        description='Authoritative personal notes, journals, tasks and reminders in SilverBullet.',
        schema={'name': 'personal_notes', 'description': '''Read and safely update SilverBullet. Every write requires the capture_id provided with the input. Read Inbox/Plans/CAPTURE_ID.md before retrying and reuse its operations exactly. apply_capture freezes the operation list then applies it idempotently; inspect each result for partial failure. Operations: note(content); journal(date YYYY-MM-DD,content); project(project name,content); create_task(title,content?,project?,due? YYYY-MM-DD,remind_at? ISO date/time WITH America/Toronto offset); complete_task(task_id); reschedule_task(task_id,due); schedule_reminder/snooze_reminder(task_id,remind_at); cancel_reminder(task_id). Use list_tasks to resolve stable task IDs and ask if multiple tasks match. Reminders are durable task metadata, delivered deterministically by the worker. For a standalone reminder create a task with no due date. Never invent content or dates. A low-confidence transcript is not a reliable measurement. Ask for clarification before freezing a plan with ambiguous actions. Use find_pages and read_page for project lookup and journal summaries. SilverBullet is authoritative; Hermes todo/memory is not the task store.''',
                'parameters': {'type': 'object', 'required': ['action'], 'properties': {
                    'action': {'type': 'string', 'enum': ['apply_capture','list_tasks','read_page','find_pages']},
                    'capture_id': {'type': 'string'}, 'operations': {'type': 'array', 'items': {'type': 'object'}},
                    'project': {'type': 'string'}, 'include_done': {'type': 'boolean'},
                    'path': {'type': 'string'}, 'prefix': {'type': 'string'}}}})
