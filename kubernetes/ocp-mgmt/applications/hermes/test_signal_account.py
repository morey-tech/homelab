import unittest
from signal_account import account_environment


class SignalAccountTests(unittest.TestCase):
    def test_unlinked_does_not_enable_gateway(self):
        self.assertEqual(account_environment([]), {})

    def test_only_self_is_allowed_and_no_automatic_notification_destination(self):
        environment = account_environment([{"number": "+16135550123"}])
        self.assertEqual(environment["SIGNAL_ALLOWED_USERS"], environment["SIGNAL_ACCOUNT"])
        self.assertEqual(environment["SIGNAL_ALLOW_ALL_USERS"], "false")
        self.assertEqual(environment["SIGNAL_GROUP_ALLOWED_USERS"], "")
        self.assertEqual(environment["SIGNAL_HOME_CHANNEL"], "")

    def test_rejects_ambiguous_or_invalid_accounts(self):
        for accounts in ({}, [{"number": None}], [{"number": "*"}],
                         [{"number": "+16135550123"}, {"number": "+16135550124"}]):
            with self.subTest(accounts=accounts), self.assertRaises(ValueError):
                account_environment(accounts)
