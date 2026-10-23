"""Prepare a UID-owned Hermes home below the root-owned PVC mount point."""
import os
from pathlib import Path
import stat


def prepare_state(volume):
    home = volume / "hermes-home"
    home.mkdir(mode=0o700, exist_ok=True)
    info = home.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("Hermes home must be a real directory owned by the application UID")
    # The previous deployment used the volume root itself as HERMES_HOME.
    # Recreate stops its processes before this init container runs. Rename on
    # the same volume preserves state (including SQLite WALs) without copying it.
    legacy = [p for p in volume.iterdir() if p.name not in (home.name, "lost+found")]
    if any(os.path.lexists(home / p.name) for p in legacy):
        raise ValueError("Legacy and private Hermes homes overlap; refusing to overwrite state")
    home.chmod(0o700)
    for source in legacy:
        source.rename(home / source.name)
    # An interrupted migration resumes: moved entries no longer exist at root.
    return home


if __name__ == "__main__":
    os.umask(0o077)
    try:
        prepare_state(Path("/state"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Cannot prepare Hermes state: {exc}")
    print("Hermes private state directory ready", flush=True)
