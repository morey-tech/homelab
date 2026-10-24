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


def supervise(command=COMMAND, paths=SECRET_PATHS, poll_seconds=30, grace_seconds=30,
              account_reader=None, gateway_command=None):
    credentials = read_credentials(paths)
    account = {}
    if account_reader:
        try:
            account = account_reader()
        except OSError:
            # The sidecar may still be starting. A later successful poll restarts
            # this container to enable the gateway; browser login stays usable.
            pass
    environment = {**os.environ, **credentials, **account}
    children = []
    stopping = False

    def stop(signum=None, frame=None):
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    next_poll = time.monotonic() + poll_seconds
    try:
        if account and gateway_command:
            children.append(subprocess.Popen(gateway_command, env=environment, start_new_session=True))
        children.append(subprocess.Popen(command, env=environment, start_new_session=True))
        while all(child.poll() is None for child in children) and not stopping:
            if time.monotonic() >= next_poll:
                try:
                    current_account = account_reader() if account_reader else {}
                    if read_credentials(paths) != credentials or current_account != account:
                        print("Credential projection or linked account changed; restarting Hermes", flush=True)
                        stopping = True
                except (OSError, ValueError):
                    print("Credential projection unavailable; retaining running Hermes", flush=True)
                next_poll = time.monotonic() + poll_seconds
            time.sleep(0.1)
        return next((child.returncode for child in children if child.returncode is not None), 0) if not stopping else 0
    finally:
        # Stop both process groups before waiting on either one.
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for child in children:
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
        from signal_account import read_account_environment
        raise SystemExit(supervise(
            account_reader=read_account_environment,
            gateway_command=["/opt/hermes/.venv/bin/hermes", "gateway", "run", "--external-supervisor"],
        ))
    except (OSError, ValueError, subprocess.CalledProcessError):
        # Do not log credential contents or environment variables.
        raise SystemExit("Cannot start Hermes; check mounted files and writable state")
