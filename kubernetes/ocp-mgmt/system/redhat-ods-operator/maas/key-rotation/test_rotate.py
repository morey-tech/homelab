"""Failure-path tests with no cluster access or real credentials."""
import base64
import copy
import datetime as dt
import unittest
from unittest.mock import patch

import rotate

NOW = dt.datetime(2026, 10, 19, tzinfo=rotate.UTC)


def iso(value):
    return value.isoformat()


def secret(days=60, key="old-key", key_id="old-id"):
    return {"metadata": {"resourceVersion": "7"}, "data": {
        k: base64.b64encode(v.encode()).decode() for k, v in {
            "MAAS_API_KEY": key, "key-id": key_id,
            "expires-at": iso(NOW + dt.timedelta(days=days)),
        }.items()}}


class FakeClient:
    subscription = "devspaces-workspaces"

    def __init__(self, old=None):
        self.old = copy.deepcopy(old)
        self.candidate = {"key": "new-key", "id": "new-id", "subscription": self.subscription,
                          "createdAt": iso(NOW), "expiresAt": iso(NOW + dt.timedelta(days=90))}
        self.minted = 0
        self.revoked = []
        self.errors = {}
        self.write_error = False
        self.write_committed = False

    def read(self):
        return self.old

    def mint(self):
        self.minted += 1
        return self.candidate

    def validate(self, key):
        if key in self.errors:
            raise self.errors[key]

    def save(self, old, candidate):
        if not self.write_error or self.write_committed:
            self.old = secret(90, candidate["key"], candidate["id"])
        if self.write_error:
            raise TimeoutError()

    def revoke(self, key_id):
        self.revoked.append(key_id)


class RotationTests(unittest.TestCase):
    def test_bootstrap(self):
        c = FakeClient()
        rotate.rotate(c, NOW)
        self.assertEqual(rotate.stored(c.old, "key-id"), "new-id")

    def test_valid_key_not_rotated_early(self):
        c = FakeClient(secret(31))
        rotate.rotate(c, NOW)
        self.assertEqual(c.minted, 0)

    def test_renewal_threshold_and_old_key_not_revoked(self):
        c = FakeClient(secret(30))
        rotate.rotate(c, NOW)
        self.assertEqual(c.minted, 1)
        self.assertEqual(c.revoked, [])

    def test_rejected_existing_key_replaced(self):
        c = FakeClient(secret())
        c.errors["old-key"] = rotate.RequestError(401)
        rotate.rotate(c, NOW)
        self.assertEqual(c.minted, 1)

    def test_gateway_outage_preserves_key_without_minting(self):
        old = secret()
        c = FakeClient(old)
        c.errors["old-key"] = rotate.RequestError(503)
        with self.assertRaises(rotate.RequestError):
            rotate.rotate(c, NOW)
        self.assertEqual(c.old, old)
        self.assertEqual(c.minted, 0)

    def test_candidate_failure_preserves_old_and_revokes_candidate(self):
        old = secret(29)
        c = FakeClient(old)
        c.errors["new-key"] = ValueError("missing model")
        with self.assertRaises(ValueError):
            rotate.rotate(c, NOW)
        self.assertEqual(c.old, old)
        self.assertEqual(c.revoked, ["new-id"])

    def test_short_lifetime_rejected(self):
        c = FakeClient()
        c.candidate["expiresAt"] = iso(NOW + dt.timedelta(days=89))
        with self.assertRaises(ValueError):
            rotate.rotate(c, NOW)
        self.assertIsNone(c.old)
        self.assertEqual(c.revoked, ["new-id"])

    def test_server_timestamp_delay_allowed(self):
        c = FakeClient()
        c.candidate["createdAt"] = iso(NOW + dt.timedelta(seconds=2))
        rotate.rotate(c, NOW)
        self.assertEqual(c.minted, 1)

    def test_failed_write_keeps_old_and_never_revokes_ambiguous_key(self):
        old = secret(29)
        c = FakeClient(old)
        c.write_error = True
        with self.assertRaises(TimeoutError):
            rotate.rotate(c, NOW)
        self.assertEqual(c.old, old)
        self.assertEqual(c.revoked, [])

    def test_committed_write_with_lost_response_is_success(self):
        c = FakeClient(secret(29))
        c.write_error = c.write_committed = True
        rotate.rotate(c, NOW)
        self.assertEqual(rotate.stored(c.old, "key-id"), "new-id")
        self.assertEqual(c.revoked, [])

    def test_malformed_state_does_not_mint(self):
        c = FakeClient(secret())
        c.old["data"]["expires-at"] = "not-base64"
        with self.assertRaises(Exception):
            rotate.rotate(c, NOW)
        self.assertEqual(c.minted, 0)

    def test_save_uses_resource_version_and_does_not_mutate_old(self):
        c = rotate.Client.__new__(rotate.Client)
        c.name, c.namespace, c.kube = "maas-workspace-key", "devspaces-maas", "https://kubernetes.default.svc"
        c.secret_path = "/api/v1/namespaces/devspaces-maas/secrets"
        old = secret(29)
        with patch.object(c, "request") as request:
            c.save(old, FakeClient().candidate)
        args = request.call_args.args
        self.assertEqual(args[2], "PUT")
        self.assertEqual(args[3]["metadata"]["resourceVersion"], "7")
        self.assertEqual(rotate.stored(old, "MAAS_API_KEY"), "old-key")


if __name__ == "__main__":
    unittest.main()
