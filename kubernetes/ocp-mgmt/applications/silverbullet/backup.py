"""Consistent, authenticated filesystem-API backups; no live SQLite file copying."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import time
from urllib.parse import quote
from urllib.request import Request, urlopen


def safe_name(name):
    path = PurePosixPath(name)
    if not name or name in (".", "..") or "\x00" in name or path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Unsafe backup member name")
    return name


def backup(base_url, token, directory, keep=14):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    headers = {"Authorization": "Bearer " + token, "X-Sync-Mode": "true"}

    def request(path):
        return urlopen(Request(base_url + path, headers=headers), timeout=30)

    def inventory():
        with request("/.fs") as response:
            files = json.load(response)
        # Bundled, read-only library pages belong to the pinned image.
        return {safe_name(f["name"]): (f["lastModified"], f["size"])
                for f in files if f.get("perm") != "ro"}

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = directory / (stamp + ".tar.gz")
    temporary = directory / (stamp + ".partial")
    try:
        before = inventory()
        with tarfile.open(temporary, "w:gz") as archive:
            for name, (modified, size) in sorted(before.items()):
                if size > 100 * 1024 * 1024:
                    raise ValueError("Backup member exceeds the 100 MiB limit")
                with request("/.fs/" + quote(name, safe="/")) as response:
                    if int(response.headers["X-Last-Modified"]) != modified:
                        raise ValueError("Space changed during backup; retry on next Job")
                    content = response.read(100 * 1024 * 1024 + 1)
                if len(content) != size:
                    raise ValueError("Backup member size changed")
                info = tarfile.TarInfo(name)
                info.size, info.mtime, info.mode = size, modified / 1000, 0o600
                archive.addfile(info, io.BytesIO(content))
        if inventory() != before:
            raise ValueError("Space changed during backup; retry on next Job")
        with temporary.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
            os.fsync(source.fileno())
        temporary.replace(target)
        target.with_suffix(target.suffix + ".sha256").write_text(digest + "  " + target.name + "\n")
        for old in sorted(directory.glob("*.tar.gz"), reverse=True)[keep:]:
            old.unlink()
            old.with_suffix(old.suffix + ".sha256").unlink(missing_ok=True)
        print("Completed notes backup; retained at most", keep, "archives", flush=True)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    os.umask(0o077)
    backup("http://silverbullet:3000", Path("/auth/value").read_text().strip(),
           Path("/backups/notes"))
