# SPDX-License-Identifier: Apache-2.0
"""B2's scored item: the value, not a key's name (#104). Synthetic strings only."""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import b2_build as b2  # noqa: E402


class Frame:
    """The two columns and `itertuples` that `documents` reads from a DataFrame."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def itertuples(self, index: bool = False):
        Row = collections.namedtuple("Row", "body candidate_string label secret_type")
        return (Row(r["body"], r["candidate"], r["label"], "Generic") for r in self.rows)


def scored(body: str, candidate: str, label: int = 1) -> tuple[str, str, collections.Counter]:
    stats: collections.Counter = collections.Counter()
    docs = b2.documents(Frame([{"body": body, "candidate": candidate, "label": label}]), stats)
    assert len(docs) == 1
    doc = docs[0]
    it = doc["items"][0]
    return doc["text"][it["start"]:it["end"]], it["class"], stats


def item(body: str, candidate: str, label: int = 1) -> tuple[str, str]:
    return scored(body, candidate, label)[:2]


def test_value_after_a_credential_key_inside_the_candidate():
    assert item("conf:\n  db_password: abab1212\n", "db_password: abab1212") == ("abab1212", "MUST_MASK")


def test_short_value_after_a_key_is_ambiguous():
    assert item("smtp_password: abc12\n", "smtp_password: abc12") == ("abc12", "AMBIGUOUS")


def test_key_whose_value_is_outside_the_candidate_is_ambiguous():
    assert item('{"client_secret": "cdcd3434cdcd"}', "client_secret") == ("client_secret", "AMBIGUOUS")


def test_key_with_a_masked_value_is_ambiguous():
    assert item("api_token = ********\n", "api_token = ********") == ("api_token", "AMBIGUOUS")


def test_multiword_name_without_credential_word():
    assert item("  database_user: someuser1\n", "database_user: someuser1", label=0) == ("someuser1", "MUST_KEEP")


def test_ruby_hash_and_quoted_json_keys():
    # Values of 8+ characters but shorter than the key, so the longest run is the name.
    text, cls, stats = scored('"auth_token" => "efef5656"', '"auth_token" => "efef5656"')
    assert (text, cls, stats["key_value_1"]) == ("efef5656", "MUST_MASK", 1)
    text, cls, stats = scored('{"session_id":"ghgh7878"}', '"session_id":"ghgh7878"')
    assert (text, cls, stats["key_value_1"]) == ("ghgh7878", "MUST_MASK", 1)


def test_name_ending_in_the_assignment_equals():
    assert item('PASSWORD="abab1212cd"\n', 'PASSWORD="abab1212cd"') == ("abab1212cd", "MUST_MASK")
    assert item("DB_PASSWORD='x'\n", "DB_PASSWORD='x'") == ("x", "AMBIGUOUS")
    assert item("DB_PASSWORD=\nnext", "DB_PASSWORD=") == ("DB_PASSWORD=", "AMBIGUOUS")


def test_key_at_line_end_is_ambiguous():
    assert item("db_password:\n  abab1212\n", "db_password:") == ("db_password", "AMBIGUOUS")


def test_random_run_before_a_colon_stays_the_item():
    # A digit or short camelCase humps read as a value, not a name.
    assert item("ijij9090ijij9090: bad credentials", "ijij9090ijij9090") == ("ijij9090ijij9090", "MUST_MASK")
    assert item("aBcDeFgHiJkLmNoP: rejected", "aBcDeFgHiJkLmNoP") == ("aBcDeFgHiJkLmNoP", "MUST_MASK")


def test_single_word_without_credential_word_stays_the_item():
    assert item("hostname: db1\n", "hostname: db1") == ("hostname", "MUST_MASK")


def test_host_port_and_user_pass_are_not_assignments():
    assert item("connect broker_host:9092 now", "broker_host:9092") == ("broker_host", "MUST_MASK")
    assert item("login admin_user:abab1212 ok", "admin_user:abab1212") == ("admin_user", "MUST_MASK")


def test_exceptions_hosts_and_random_humps_are_not_names():
    assert item("java.lang.IllegalStateException: Failed to load", "java.lang.IllegalStateException") == (
        "java.lang.IllegalStateException", "MUST_MASK")
    assert item("smtp.gmail.com: connection refused", "smtp.gmail.com") == ("smtp.gmail.com", "MUST_MASK")
    assert item("rQ7KeyzWm4pXt2Lb: denied", "rQ7KeyzWm4pXt2Lb") == ("rQ7KeyzWm4pXt2Lb", "MUST_MASK")
    assert item("xAuthQ9z8y7x6w5v4u3t2: bad", "xAuthQ9z8y7x6w5v4u3t2") == ("xAuthQ9z8y7x6w5v4u3t2", "MUST_MASK")
    assert item("authq9z8y7x6w5v4: denied", "authq9z8y7x6w5v4") == ("authq9z8y7x6w5v4", "MUST_MASK")


def test_leading_name_equals_is_cut_as_before():
    assert item("export API_KEY=klkl1313klkl\n", "API_KEY=klkl1313klkl") == ("klkl1313klkl", "MUST_MASK")


def test_is_key_name():
    for name in ("password", "db_password", "dbPassword", "x-api-key", "Authorization", "client_id", "SMTP_USER",
                 "spring.datasource.password", "oauth2_token", "db_password2"):
        assert b2.is_key_name(name), name
    for run in ("hostname", "ijij9090ijij9090", "aBcDeFgHiJkLmNoP", "abc123def456", "a/b+c=", "clientID9",
                "spring.datasource.username", "ValueError", "NullPointerException", "smtp.gmail.com"):
        assert not b2.is_key_name(run), run
