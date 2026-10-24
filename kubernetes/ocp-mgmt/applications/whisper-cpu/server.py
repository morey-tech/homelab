"""Bounded OpenAI-compatible Whisper endpoint using the pinned CPU image's libraries."""
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing as mp
import os
import signal
import tempfile
import threading

MAX_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 300
TIMEOUT = 120
MODEL = os.environ.get('WHISPER_MODEL', 'Systran/faster-whisper-base.en')


def parse_upload(content_type, body):
    if not content_type.lower().startswith('multipart/form-data;'):
        raise ValueError('Expected multipart/form-data')
    message = BytesParser(policy=policy.default).parsebytes(
        ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + body)
    values = {}
    for part in message.iter_parts():
        name = part.get_param('name', header='content-disposition')
        if name in values:
            raise ValueError('Duplicate multipart field')
        values[name] = part.get_payload(decode=True)
    if values.get('model', b'').decode() != 'whisper-1':
        raise ValueError('Model must be whisper-1 (the server selects the configured CPU model)')
    if not values.get('file'):
        raise ValueError('Missing audio file')
    fmt = values.get('response_format', b'json').decode()
    if fmt not in ('json', 'text'):
        raise ValueError('Supported response formats: json, text')
    return values['file'], fmt


def infer(connection, ready):
    import av
    import numpy as np
    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL, device='cpu', compute_type='int8', cpu_threads=2,
                         num_workers=1, download_root='/cache/models')
    ready.set()
    while True:
        path = connection.recv()
        try:
            samples, count = [], 0
            with av.open(path) as audio:
                resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
                for frame in audio.decode(audio=0):
                    for decoded in resampler.resample(frame):
                        values = decoded.to_ndarray().flatten()
                        count += len(values)
                        if count > MAX_SECONDS * 16000:
                            raise ValueError('Audio exceeds five minutes')
                        samples.append(values)
                for decoded in resampler.resample(None):
                    values = decoded.to_ndarray().flatten()
                    count += len(values)
                    samples.append(values)
            if not samples or count > MAX_SECONDS * 16000:
                raise ValueError('Empty or oversized audio')
            data = np.concatenate(samples).astype(np.float32) / 32768.0
            segments, _ = model.transcribe(data, beam_size=5, vad_filter=True)
            segments = list(segments)
            connection.send({'text': ''.join(s.text for s in segments).strip(),
                             'uncertain': any(s.avg_logprob < -1 for s in segments)})
        except Exception as error:
            connection.send({'error': 'Audio decoding or CPU transcription failed',
                             'kind': type(error).__name__})


class Worker:
    def __init__(self):
        self.lock = threading.Lock()
        self.start()

    def start(self):
        self.connection, child = mp.Pipe()
        self.ready = mp.Event()
        self.process = mp.Process(target=infer, args=(child, self.ready), daemon=True)
        self.process.start()
        child.close()

    def restart(self):
        self.process.kill()
        self.process.join(timeout=5)
        self.connection.close()
        self.start()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *_):
        pass  # Never log uploads, tokens, transcripts or filenames.

    def reply(self, status, value, plain=False):
        body = (value if plain else json.dumps(value)).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain' if plain else 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/healthz':
            alive = worker.process.is_alive()
            return self.reply(200 if alive else 503, {'alive': alive})
        if self.path == '/readyz':
            ok = worker.process.is_alive() and worker.ready.is_set()
            return self.reply(200 if ok else 503, {'ready': ok, 'device': 'cpu'})
        self.reply(404, {'error': 'Unknown endpoint'})

    def do_POST(self):
        if self.path != '/inference-server/local-llm/v1/audio/transcriptions':
            return self.reply(404, {'error': 'Unknown endpoint'})
        if not worker.lock.acquire(blocking=False):
            return self.reply(429, {'error': 'CPU transcription is busy; retry later'})
        try:
            if not worker.process.is_alive():
                worker.restart()
            if not worker.ready.is_set():
                return self.reply(503, {'error': 'CPU model is loading'})
            length = int(self.headers.get('Content-Length', '0'))
            if self.headers.get('Transfer-Encoding') or not 0 < length <= MAX_BYTES:
                return self.reply(413, {'error': 'A Content-Length of 1–16 MiB is required'})
            body = self.rfile.read(length)
            if len(body) != length:
                return self.reply(400, {'error': 'Incomplete audio upload'})
            audio, fmt = parse_upload(self.headers.get('Content-Type', ''), body)
            with tempfile.NamedTemporaryFile(dir='/tmp') as temp:
                temp.write(audio)
                temp.flush()
                worker.connection.send(temp.name)
                if not worker.connection.poll(TIMEOUT):
                    worker.restart()
                    return self.reply(504, {'error': 'CPU transcription timed out'})
                result = worker.connection.recv()
            if 'error' in result:
                return self.reply(422, result)
            return self.reply(200, result['text'] if fmt == 'text' else result, fmt == 'text')
        except (ValueError, UnicodeError):
            self.reply(400, {'error': 'Invalid transcription request'})
        except (OSError, EOFError):
            self.reply(503, {'error': 'CPU transcription unavailable'})
        finally:
            worker.lock.release()


if __name__ == '__main__':
    os.umask(0o077)
    mp.set_start_method('spawn')
    worker = Worker()
    server = ThreadingHTTPServer((os.environ.get('BIND_ADDRESS', '0.0.0.0'), int(os.environ.get('PORT', '8000'))), Handler)
    def stop(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    finally:
        worker.process.terminate()
        worker.process.join(timeout=5)
        if worker.process.is_alive():
            worker.process.kill()
            worker.process.join(timeout=5)
        worker.connection.close()
        server.server_close()
