"""Restore a checked backup through the authenticated API using conditional writes."""
import argparse
import hashlib
from pathlib import Path
import tarfile
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from backup import safe_name


def restore(archive, base_url, token, replace_existing=False):
    expected = archive.with_suffix(archive.suffix + '.sha256').read_text().split()[0]
    with archive.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
            raise ValueError('Backup checksum does not match')
    headers = {'Authorization': 'Bearer ' + token, 'X-Sync-Mode': 'true'}
    with tarfile.open(archive) as source:
        members = source.getmembers()
        names = set()
        for member in members:
            name = safe_name(member.name)
            if not member.isfile() or member.size > 100*1024*1024 or name in names:
                raise ValueError('Unsafe or duplicate archive member')
            names.add(name)
        for member in members:
            url = base_url.rstrip('/') + '/.fs/' + quote(member.name, safe='/')
            content = source.extractfile(member).read()
            revision = None
            try:
                with urlopen(Request(url, headers=headers), timeout=30) as response:
                    existing = response.read(100*1024*1024+1)
                    revision = response.headers.get('ETag')
                if existing == content:
                    continue
                if not replace_existing or not revision:
                    raise ValueError('Existing page differs; restore to an empty space or explicitly allow replacement')
            except HTTPError as error:
                if error.code != 404:
                    raise
            conditional = {'If-Match': revision} if revision else {'If-None-Match': '*'}
            with urlopen(Request(url, data=content, method='PUT', headers={**headers, **conditional}), timeout=30):
                pass
    print('Restored backup; matching existing files were preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--base-url', default='http://127.0.0.1:3000')
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--replace-existing', action='store_true')
    args = parser.parse_args()
    restore(args.archive, args.base_url, args.token_file.read_text().strip(), args.replace_existing)
