"""Run Hermes without the image's root/s6 bootstrap; restart on secret rotation."""
import os
from pathlib import Path
import signal
import subprocess
import time


SECRET_PATHS = {
    "OPENAI_API_KEY": Path("/maas/MAAS_API_KEY"),
    "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": Path("/dashboard-password/value"),
    "HERMES_DASHBOARD_BASIC_AUTH_SECRET": Path("/dashboard-signing-key/value"),
}
COMMAND = ["/opt/hermes/.venv/bin/hermes", "dashboard", "--host", "127.0.0.1",
           "--port", "9119", "--no-open"]


def read_credentials(paths):
    values = {name: path.read_text().strip() for name, path in paths.items()}
    if not all(values.values()):
        raise ValueError("Empty credential projection")
    return values


def seed_state(state, config_dir):
    state.mkdir(parents=True, exist_ok=True)
    (state / "workspace").mkdir(exist_ok=True)
    # Never replace user state or import another agent's files.
    for name, content in [("SOUL.md", (config_dir / "SOUL.md").read_text()),
                          # Schema stamp matches the pinned v0.22.5 image.
                          ("config.yaml", "_config_version: 51\n")]:
        try:
            with (state / name).open("x") as target:
                target.write(content)
        except FileExistsError:
            pass


def supervise(command=COMMAND, paths=SECRET_PATHS, poll_seconds=30, grace_seconds=30):
    credentials = read_credentials(paths)
    child = subprocess.Popen(command, env={**os.environ, **credentials}, start_new_session=True)
    stopping = False

    def stop(signum=None, frame=None):
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    next_poll = time.monotonic() + poll_seconds
    try:
        while child.poll() is None and not stopping:
            if time.monotonic() >= next_poll:
                try:
                    if read_credentials(paths) != credentials:
                        print("Credential projection changed; restarting Hermes", flush=True)
                        stopping = True
                except (OSError, ValueError):
                    print("Credential projection unavailable; retaining running Hermes", flush=True)
                next_poll = time.monotonic() + poll_seconds
            time.sleep(0.1)
        return child.returncode if not stopping else 0
    finally:
        # Stop the dashboard process group; container exit also reaps detached PTYs.
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        state = Path(os.environ.get("HERMES_HOME", "/opt/data"))
        seed_state(state, Path("/config"))
        # Use the image's own merge/preservation logic for bundled skill updates.
        subprocess.run(["/opt/hermes/.venv/bin/python", "-B", "/opt/hermes/tools/skills_sync.py"],
                       check=True, cwd="/opt/hermes")
        os.chdir(state / "workspace")
        raise SystemExit(supervise())
    except (OSError, ValueError, subprocess.CalledProcessError):
        # Do not log credential contents or environment variables.
        raise SystemExit("Cannot start Hermes; check mounted files and writable state")
