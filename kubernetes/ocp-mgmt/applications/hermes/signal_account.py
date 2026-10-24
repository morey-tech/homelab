"""Discover the one locally linked account; never log its number or keys."""
import json
import re
from urllib.request import Request, urlopen


URL = "http://127.0.0.1:8080"


def rpc(method, params=None, timeout=5, url=URL):
    request = Request(url + "/api/v1/rpc", data=json.dumps({
        "jsonrpc": "2.0", "id": "hermes-local", "method": method,
        "params": params or {},
    }).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if "error" in result or "result" not in result:
        raise ValueError("Signal RPC failed")
    return result["result"]


def account_environment(accounts):
    if not isinstance(accounts, list):
        raise ValueError("Invalid Signal account response")
    if not accounts:
        return {}
    if len(accounts) != 1:
        raise ValueError("Exactly one linked Signal account is supported")
    number = accounts[0].get("number", "")
    if not isinstance(number, str) or not re.fullmatch(r"\+[1-9][0-9]{6,14}", number):
        raise ValueError("A numbered Signal account is required by this Hermes adapter")
    return {
        "SIGNAL_HTTP_URL": URL,
        "SIGNAL_ACCOUNT": number,
        "SIGNAL_ALLOWED_USERS": number,
        "SIGNAL_ALLOW_ALL_USERS": "false",
        "SIGNAL_GROUP_ALLOWED_USERS": "",
        # No default notification destination: alerts use a separate service.
        "SIGNAL_HOME_CHANNEL": "",
        "SIGNAL_IGNORE_STORIES": "true",
    }


def read_account_environment():
    return account_environment(rpc("listAccounts"))
