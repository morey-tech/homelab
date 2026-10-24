import unittest
from server import parse_upload


def upload(fields):
    return b''.join(b'--test\r\nContent-Disposition: form-data; name="' + key.encode() +
                    b'"\r\n\r\n' + value + b'\r\n' for key, value in fields) + b'--test--\r\n'


class UploadTests(unittest.TestCase):
    def test_audio_is_preserved(self):
        data = b'\x00\xffaudio\x00'
        self.assertEqual(parse_upload('multipart/form-data; boundary=test', upload([
            ('model', b'whisper-1'), ('file', data)])), (data, 'json'))

    def test_rejects_wrong_model_duplicate_file_and_unsupported_format(self):
        cases = [[('model', b'other'), ('file', b'a')],
                 [('model', b'whisper-1'), ('file', b'a'), ('file', b'b')],
                 [('model', b'whisper-1'), ('file', b'a'), ('response_format', b'verbose_json')],
                 [('model', b'whisper-1')]]
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                parse_upload('multipart/form-data; boundary=test', upload(fields))

    def test_rejects_json(self):
        with self.assertRaises(ValueError):
            parse_upload('application/json', b'{}')
