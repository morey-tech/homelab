import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from backup import safe_name
from restore import restore


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name)/'backup.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as target:
            info = tarfile.TarInfo('Journal/test.md')
            info.size = 8
            target.addfile(info, io.BytesIO(b'original'))
        checksum = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.archive.with_suffix('.gz.sha256').write_text(checksum+'  backup.tar.gz\n')

    def test_checksum_failure_makes_no_requests(self):
        self.archive.write_bytes(b'corrupted')
        with patch('restore.urlopen') as opener, self.assertRaises(ValueError):
            restore(self.archive, 'http://example', 'test-token')
        opener.assert_not_called()

    def test_existing_different_content_is_not_overwritten(self):
        response = io.BytesIO(b'phone edit')
        response.headers = {'ETag': 'revision-2'}
        with patch('restore.urlopen', return_value=response) as opener, self.assertRaises(ValueError):
            restore(self.archive, 'http://example', 'test-token')
        self.assertEqual(opener.call_count, 1)

    def test_explicit_replace_uses_revision_and_aborts_on_race(self):
        requests = []
        def opener(request, **kwargs):
            requests.append(request)
            if request.get_method() == 'GET':
                result = io.BytesIO(b'phone edit')
                result.headers = {'ETag': 'revision-2'}
                return result
            self.assertEqual(request.get_header('If-match'), 'revision-2')
            raise HTTPError(request.full_url, 412, 'changed', {}, None)
        with patch('restore.urlopen', side_effect=opener), self.assertRaises(HTTPError):
            restore(self.archive, 'http://example', 'test-token', replace_existing=True)
        self.assertEqual(len(requests), 2)

    def test_missing_files_use_create_only(self):
        def opener(request, **kwargs):
            if request.get_method() == 'GET':
                raise HTTPError(request.full_url, 404, 'missing', {}, None)
            self.assertEqual(request.get_header('If-none-match'), '*')
            self.assertEqual(request.data, b'original')
            return io.BytesIO(b'')
        with patch('restore.urlopen', side_effect=opener):
            restore(self.archive, 'http://example', 'test-token')

    def test_unsafe_archive_names(self):
        for name in ['../escape', '/absolute', 'folder/../escape', '.', 'a\\b', '\x00']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_name(name)
