"""Run on your computer after GitOps deployment and an oc port-forward.

Requires qrencode locally. Does not store the linking URI or print account data.
"""
import shutil
import subprocess
from signal_account import rpc


def main():
    if not shutil.which("qrencode"):
        raise SystemExit("Install qrencode first (on macOS: brew install qrencode)")
    if rpc("listAccounts"):
        raise SystemExit("An account is already linked. Refusing to add another.")
    uri = rpc("startLink")["deviceLinkUri"]
    print("In Signal on your iPhone: Settings → Linked Devices → Link New Device.")
    subprocess.run(["qrencode", "-t", "ANSIUTF8"], input=uri, text=True, check=True)
    rpc("finishLink", {"deviceLinkUri": uri, "deviceName": "Hermes homelab"}, timeout=180)
    print("Linked. Hermes will enable Note to Self within roughly 30 seconds.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError):
        raise SystemExit("Linking failed or timed out. Check the port-forward and retry.")
