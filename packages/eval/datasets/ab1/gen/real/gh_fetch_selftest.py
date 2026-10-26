# SPDX-License-Identifier: Apache-2.0
"""Offline test of gen/real/gh_fetch.py, on the fake `gh api` payloads in gen/real/fixtures/.

    python gen/real/gh_fetch_selftest.py

No network: a fake runner stands in for `subprocess.run`, serving the fixture JSON by looking at
the `gh api` argument the caller asked for, so the whole path is exercised — argument shape,
JSON parsing, pull-request skipping, the length / language / technical rules, the seeded priority,
the licence check, the resumable `gh_tried_<lang>.txt`, the output record and the rate-limit sleep.
Prints one PASS line per check and the number of the issue chosen. Writes only to a temporary
directory, which it removes afterwards.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import gh_fetch  # noqa: E402
from common import derive_seed  # noqa: E402

FIXTURES = HERE / "fixtures"
ISSUES = json.loads((FIXTURES / "issues.json").read_text(encoding="utf-8"))
REPO = json.loads((FIXTURES / "repository.json").read_text(encoding="utf-8"))
REPO_GPL = json.loads((FIXTURES / "repository_gpl.json").read_text(encoding="utf-8"))
RATE_OK = {"resources": {"core": {"remaining": 4999, "reset": 0}}}
RATE_LOW = {"resources": {"core": {"remaining": 3, "reset": 4102444800}}}
CHECKS = 0
CALLS: list[str] = []


def fixture_runner(payloads: dict[str, object]):
    def runner(cmd, check, capture_output):
        assert cmd[:2] == ["gh", "api"], cmd
        CALLS.append(cmd[2])
        if cmd[2] not in payloads:
            raise subprocess.CalledProcessError(1, cmd, output=b"", stderr=b"not found")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payloads[cmd[2]]).encode(), b"")
    return runner


def check(name: str, ok: bool) -> None:
    global CHECKS
    if not ok:
        raise AssertionError(f"FAIL {name}")
    CHECKS += 1
    print(f"PASS {name}")


def main() -> None:
    payloads = {
        "/repositories/101": REPO,
        "/repositories/102": REPO_GPL,
        "/repos/acme-ejemplo/proyecto-pruebas/issues?state=all&sort=comments&direction=desc&per_page=50": ISSUES,
        "rate_limit": RATE_OK,
    }
    runner = fixture_runner(payloads)
    tmp = Path(tempfile.mkdtemp(prefix="gh_fetch_selftest_"))
    try:
        # --- parsing
        full_name, licence = gh_fetch.repo_record(REPO)
        check("repository payload: full_name and spdx licence", (full_name, licence) == ("acme-ejemplo/proyecto-pruebas", "MIT"))
        check("repository payload without a licence object", gh_fetch.repo_record({"full_name": "a/b"}) == ("a/b", None))
        try:
            gh_fetch.repo_record({"id": 1})
            check("repository payload without full_name fails loud", False)
        except ValueError:
            check("repository payload without full_name fails loud", True)

        # --- one issue per repository, by seeded priority
        for lang in ("es", "de"):
            want = sorted((it for it in ISSUES if "pull_request" not in it),
                          key=lambda it: (derive_seed("pool", f"101|{it['number']}"), it["number"]))
            usable = [it for it in want
                      if 300 <= len(gh_fetch.issue_text(it)) <= 6000
                      and gh_fetch.is_language(gh_fetch.issue_text(it), lang)
                      and gh_fetch.is_technical(gh_fetch.issue_text(it))]
            chosen = gh_fetch.select_issue(101, ISSUES, lang)
            check(f"select_issue({lang}): first usable issue by seeded priority, number {chosen['number']}",
                  chosen is not None and chosen["number"] == usable[0]["number"])
        check("select_issue: the pull request is never chosen",
              gh_fetch.select_issue(101, ISSUES, "es")["number"] != 900)
        check("select_issue: a null body is handled, not chosen",
              gh_fetch.select_issue(101, [ISSUES[-1]], "es") is None)
        check("select_issue: an English issue does not pass the Spanish check",
              gh_fetch.select_issue(101, [ISSUES[2]], "es") is None)
        check("select_issue: a too-short issue is dropped",
              gh_fetch.select_issue(101, [ISSUES[1]], "es") is None)
        check("select_issue: the German issue is usable for de",
              gh_fetch.select_issue(101, [ISSUES[5]], "de")["number"] == 905)

        # --- the technical markers, one per branch
        check("technical: fenced code block", gh_fetch.is_technical("texto\n```\ncode\n```"))
        check("technical: stack trace", gh_fetch.is_technical("x\n    at Foo.bar(f.js:1:2)"))
        check("technical: error output", gh_fetch.is_technical("algo\nValueError: bad input"))
        check("technical: command line", gh_fetch.is_technical("hola\n$ npm run build"))
        check("technical: version string", gh_fetch.is_technical("uso la version 3.10.4 del gestor"))
        check("technical: plain prose is not technical",
              not gh_fetch.is_technical("Hola a todos, queria preguntar una cosa sencilla sobre el proyecto."))

        # --- text assembly and the length window
        text = gh_fetch.issue_text({"title": "  Titulo  ", "body": " Cuerpo \n"})
        check("issue_text: title, blank line, stripped body", text == "Titulo\n\nCuerpo")
        check("issue_text: title only when the body is empty",
              gh_fetch.issue_text({"title": "Titulo", "body": None}) == "Titulo")
        long_title = "x" * 7000
        check("select_issue: 300..6,000 character window",
              gh_fetch.select_issue(101, [{"number": 1, "title": long_title, "body": None}], "es") is None)

        # --- end to end, per language, resumable, licence-checked
        stats = gh_fetch.fetch_language("es", [102, 101], tmp, target=1, runner=runner)
        rows = [json.loads(line) for line in (tmp / "gh_issues_es.jsonl").read_text(encoding="utf-8").splitlines()]
        check("fetch_language: one issue written for es", len(rows) == 1 and stats["kept"] == 1)
        check("fetch_language: record fields",
              sorted(rows[0]) == ["body", "created_at", "full_name", "html_url", "license", "number", "repo_id", "title"])
        check("fetch_language: licence recorded from the API", rows[0]["license"] == "MIT")
        check("fetch_language: the GPL repository is dropped, the run goes on",
              stats["licence_dropped"] == 1 and stats["attempted"] == 2 and rows[0]["repo_id"] == 101)
        tried = (tmp / "gh_tried_es.txt").read_text(encoding="utf-8").split()
        check("fetch_language: both attempted repositories are recorded as tried",
              tried == ["102", "101"])
        stats2 = gh_fetch.fetch_language("es", [101, 102], tmp, target=1, runner=runner)
        check("fetch_language: resumable, nothing attempted at target",
              stats2["attempted"] == 0 and stats2["held"] == 1 and stats2["tried_before"] == 2)
        gh_fetch.fetch_language("de", [101], tmp, target=1, runner=runner)
        rows_de = [json.loads(line) for line in (tmp / "gh_issues_de.jsonl").read_text(encoding="utf-8").splitlines()]
        check("fetch_language: a German issue is kept in its own file",
              len(rows_de) == 1 and rows_de[0]["number"] == 905)
        check("fetch_language: the issues file is appended to, not rewritten",
              (tmp / "gh_issues_es.jsonl").read_text(encoding="utf-8").count("\n") == 1)

        # --- the API argument shapes the network run will use
        gh_fetch.fetch_language("fr", [101], tmp, target=1, runner=runner)
        check("gh api: repository resolved by id", "/repositories/101" in CALLS)
        check("gh api: issues listed with state=all&per_page=50",
              "/repos/acme-ejemplo/proyecto-pruebas/issues?state=all&sort=comments&direction=desc&per_page=50" in CALLS)

        # --- rate limit
        low = fixture_runner({"/repositories/101": REPO, "rate_limit": RATE_LOW})
        slept = []
        gh_fetch.wait_for_quota(low, sleeper=slept.append)
        check("rate limit: sleeps when the core quota is under 100",
              len(slept) == 1 and slept[0] > 0)
        high = fixture_runner({"rate_limit": RATE_OK})
        slept2 = []
        gh_fetch.wait_for_quota(high, sleeper=slept2.append)
        check("rate limit: no sleep on a healthy quota", slept2 == [])
        check("rate limit: the quota is read from the core resource",
              gh_fetch.core_quota(high) == (4999, 0))

        # --- an API failure is counted, and a run of failures stops the language
        broken = fixture_runner({"rate_limit": RATE_OK})
        stats3 = gh_fetch.fetch_language("it", [999], tmp, target=1, runner=broken)
        check("api error: counted, run continues", stats3["api_error"] == 1 and stats3["kept"] == 0)
        check("api error: the failed repository is still marked tried",
              (tmp / "gh_tried_it.txt").read_text(encoding="utf-8").split() == ["999"])
        try:
            gh_fetch.fetch_language("it", list(range(900, 930)), tmp, target=1, runner=broken)
            check("api error: a run of failures stops the language", False)
        except RuntimeError:
            check("api error: a run of failures stops the language", True)
    finally:
        shutil.rmtree(tmp)
    print(f"{CHECKS}/{CHECKS} checks passed")


if __name__ == "__main__":
    main()
