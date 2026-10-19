"""Renew the shared Dev Spaces MaaS key without logging credentials."""
import base64
import copy
import datetime as dt
import json
import os
from pathlib import Path
import ssl
import sys
import urllib.error
import urllib.request
import uuid

UTC = dt.timezone.utc
LIFETIME = dt.timedelta(days=90)
RENEW_BEFORE = dt.timedelta(days=30)
MODELS = {"local-llm", "claude-sonnet-4-6"}


class RequestError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(f"HTTP {status}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self):
        self.token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        self.kube = "https://kubernetes.default.svc"
        self.maas = os.environ["MAAS_URL"].rstrip("/")
        self.namespace = os.environ["POD_NAMESPACE"]
        self.name = "maas-workspace-key"
        self.subscription = "devspaces-workspaces"
        self.secret_path = f"/api/v1/namespaces/{self.namespace}/secrets"
        kube_tls = ssl.create_default_context(cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
        self.openers = {
            self.kube: urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=kube_tls)),
            self.maas: urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context())),
        }

    def request(self, base, path, method="GET", data=None, key=None):
        token = key if key is not None else self.token_path.read_text().strip()
        req = urllib.request.Request(base + path, method=method,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            data=json.dumps(data).encode() if data is not None else None)
        try:
            with self.openers[base].open(req, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            # Do not log response bodies: key-management responses may contain keys.
            raise RequestError(error.code) from None

    def read(self):
        try:
            return self.request(self.kube, f"{self.secret_path}/{self.name}")
        except RequestError as error:
            if error.status == 404:
                return None
            raise

    def mint(self):
        return self.request(self.maas, "/maas-api/v1/api-keys", "POST", {
            "name": "devspaces-" + uuid.uuid4().hex,
            "description": "Automatically rotated shared Dev Spaces credential",
            "expiresIn": "90d", "subscription": self.subscription,
        })

    def validate(self, key):
        result = self.request(self.maas, "/v1/models", key=key)
        if not MODELS.issubset({m["id"] for m in result.get("data", [])}):
            raise ValueError("MaaS key cannot discover both required models")

    def revoke(self, key_id):
        self.request(self.maas, "/maas-api/v1/api-keys/" + key_id, "DELETE")

    def save(self, old, candidate):
        secret = copy.deepcopy(old) if old else {
            "apiVersion": "v1", "kind": "Secret", "type": "Opaque",
            "metadata": {"name": self.name, "namespace": self.namespace},
        }
        secret["metadata"].pop("managedFields", None)
        secret["metadata"].setdefault("labels", {})["app.kubernetes.io/managed-by"] = "maas-key-rotator"
        secret["data"] = {k: base64.b64encode(v.encode()).decode() for k, v in {
            "MAAS_API_KEY": candidate["key"], "key-id": candidate["id"],
            "created-at": candidate["createdAt"], "expires-at": candidate["expiresAt"],
        }.items()}
        # resourceVersion on PUT prevents concurrent writers replacing a newer key.
        path = self.secret_path + ("/" + self.name if old else "")
        self.request(self.kube, path, "PUT" if old else "POST", secret)


def timestamp(value):
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Missing timezone")
    return result


def stored(secret, field):
    return base64.b64decode(secret["data"][field], validate=True).decode()


def rotate(client, now=None):
    now = now or dt.datetime.now(UTC)
    old = client.read()
    if old:
        # Malformed state fails closed instead of silently generating keys repeatedly.
        expiry = timestamp(stored(old, "expires-at"))
        if expiry - now > RENEW_BEFORE:
            try:
                client.validate(stored(old, "MAAS_API_KEY"))
                print("Current key is valid; renewal is not due")
                return
            except RequestError as error:
                if error.status not in (401, 403):
                    raise
                print("Current key was rejected; issuing a replacement")

    candidate = client.mint()
    try:
        if candidate["subscription"] != client.subscription:
            raise ValueError("Unexpected subscription")
        # MaaS stamps createdAt after its database write, so allow API latency.
        if timestamp(candidate["expiresAt"]) - timestamp(candidate["createdAt"]) < LIFETIME - dt.timedelta(minutes=5):
            raise ValueError("MaaS returned a key with less than 90 days of lifetime")
        if timestamp(candidate["expiresAt"]) - now < LIFETIME - dt.timedelta(minutes=5):
            raise ValueError("MaaS returned an already-aged key")
        client.validate(candidate["key"])
    except Exception:
        try:
            client.revoke(candidate["id"])
        except Exception:
            print("WARNING: unable to revoke rejected candidate; it will expire", file=sys.stderr)
        raise

    try:
        client.save(old, candidate)
    except Exception:
        # A timeout may occur AFTER the API server persists the Secret. Never
        # revoke this candidate on an ambiguous write and invalidate published keys.
        persisted = client.read()
        if not persisted or stored(persisted, "key-id") != candidate["id"]:
            raise
    # Deliberately leave the old key valid until its original expiration, so
    # existing workspace environments retain the full issued 90-day lifetime.
    print("Published a validated 90-day key; previous key keeps its original expiry")


if __name__ == "__main__":
    try:
        rotate(Client())
    except Exception as error:
        # Exception text/tracebacks could include credentials from unexpected payloads.
        status = f" (HTTP {error.status})" if isinstance(error, RequestError) else ""
        print(f"Key renewal failed: {type(error).__name__}{status}; existing Secret was not intentionally cleared", file=sys.stderr)
        sys.exit(1)
