# SPDX-License-Identifier: Apache-2.0
r"""Phase A, AB-1: fetch the real it/de/fr/es GitHub issues of the candidate repositories.

    python gen/real/gh_fetch.py [--candidates DIR] [--out DIR] [--target 60] [--langs it,de,fr,es]

This script talks to the network through `gh api` only, and only when run by hand: it was written
and tested offline (see gen/real/gh_fetch_selftest.py, which drives `fetch_language` with a fake
runner and the JSON fixtures in gen/real/fixtures/). Phase A does not run it.

What it does, per language, walking cache/real/gh_candidates_<lang>.txt in priority order:
  1. `gh api /repositories/<id>` resolves the repository: full name and the licence the API
     reports now. An issue is kept only when that licence is still one of LICENCES (the candidate
     list was filtered on the dataset's metadata snapshot, which can be stale).
  2. `gh api "/repos/<owner>/<repo>/issues?state=all&sort=comments&direction=desc&per_page=50"` lists the repository's issues,
     newest first; entries carrying a `pull_request` key are pull requests and are skipped.
  3. At most one issue per repository is kept: the first, by the seeded priority
     `derive_seed("pool", "<repo_id>|<number>")` (ascending, as in the carrier pool), whose text
     `title + "\\n\\n" + body` (both stripped) is 300..6,000 characters after the builder's carrier
     normalisation, passes the language check for that language (`is_language` in
     gen/real/wildchat_select.py: the builder's `is_english` idea with that language's stop words,
     no non-Latin script) and looks technical. Technical means at least one of:
       T1 a fenced code block (``` or ~~~);
       T2 a stack trace or error output (Python traceback, `at pkg.Class.method(File:12)`,
          `panic:`, `XxxError:`/`XxxException:`, a line opening with error/errore/erreur/fehler);
       T3 command lines: a line starting with a shell prompt (`$`, `>`, `#`, `user@host:...`) or
          with a known tool or package manager (git, docker, npm, pip, apt-get, kubectl, …);
       T4 version strings: `v?\d+\.\d+\.\d+`.
  4. The kept issue is appended to cache/real/gh_issues_<lang>.jsonl as
     `{repo_id, full_name, license, number, html_url, created_at, title, body}`.

Resumable: every repository the run finishes with is appended to cache/real/gh_tried_<lang>.txt
and skipped by later runs; a language stops when it holds TARGET (60) issues or the candidates run
out. `gh api rate_limit` is polled every 25 calls and before the first one: when the core quota is
under 100 the run sleeps until the reset.

Prints counts only. Never prints issue text, names or addresses.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import ROOT, derive_seed  # noqa: E402
from wildchat_select import FENCE_RE, STACK_RE, is_language, normalise  # noqa: E402

LANGS = ("it", "de", "fr", "es")
LICENCES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "CC0-1.0", "Unlicense",
            "MPL-2.0", "CC-BY-4.0"}
TARGET = 60
EXCERPT_MIN = 300
EXCERPT_MAX = 6000
RATE_FLOOR = 100
RATE_EVERY = 25
MAX_SLEEP = 3600
MAX_CONSECUTIVE_ERRORS = 10

CMD_RE = re.compile(
    r"^\s*(?:\$|>|#|[\w.-]+@[\w.-]+:[^\n]*[$#])\s*\S"
    r"|^\s*(?:sudo|apt|apt-get|yum|brew|npm|npx|yarn|pnpm|pip|pip3|python|python3|node|java|mvn|"
    r"gradle|composer|bundle|gem|cargo|go|dotnet|docker|docker-compose|kubectl|helm|terraform|"
    r"systemctl|service|chmod|chown|curl|wget|make|cmake|git|psql|mysql|redis-cli|sqlite3|"
    r"set|export)\s+\S", re.M)
VERSION_RE = re.compile(r"\bv?\d+\.\d+\.\d+")

DEFAULT_CANDIDATES = ROOT / "cache" / "real"
DEFAULT_OUT = ROOT / "cache" / "real"


def is_technical(text: str) -> bool:
    return bool(FENCE_RE.search(text) or STACK_RE.search(text) or CMD_RE.search(text)
                or VERSION_RE.search(text))


def issue_text(issue: dict) -> str:
    title = (issue.get("title") or "").strip()
    body = (issue.get("body") or "").strip()
    return normalise(f"{title}\n\n{body}" if body else title)


def select_issue(repo_id: int, issues: list[dict], lang: str) -> dict | None:
    """The first issue by seeded priority whose text passes the length, language and technical rules."""
    usable = [it for it in issues if "pull_request" not in it]
    usable.sort(key=lambda it: (derive_seed("pool", f"{repo_id}|{it['number']}"), it["number"]))
    for issue in usable:
        text = issue_text(issue)
        if not (EXCERPT_MIN <= len(text) <= EXCERPT_MAX):
            continue
        if not is_language(text, lang):
            continue
        if not is_technical(text):
            continue
        return issue
    return None


def run_gh(args: list[str], runner=subprocess.run):
    """One `gh api` call; the only network access of this script."""
    proc = runner(["gh", "api", *args], check=True, capture_output=True)
    return json.loads(proc.stdout.decode("utf-8"))


def core_quota(runner=subprocess.run) -> tuple[int, int]:
    payload = run_gh(["rate_limit"], runner)
    core = payload["resources"]["core"]
    return int(core["remaining"]), int(core["reset"])


def wait_for_quota(runner=subprocess.run, sleeper=time.sleep) -> None:
    """Sleep until the core quota resets when it is under RATE_FLOOR (at most MAX_SLEEP at a time)."""
    remaining, reset = core_quota(runner)
    if remaining < RATE_FLOOR:
        pause = min(MAX_SLEEP, max(0, reset - int(time.time())) + 5)
        print(f"  core quota {remaining}: sleeping {pause}s", flush=True)
        sleeper(pause)


def repo_record(repo: dict) -> tuple[str, str | None]:
    full_name = repo.get("full_name")
    if not full_name:
        raise ValueError("repository payload without full_name")
    license_obj = repo.get("license") or {}
    return full_name, license_obj.get("spdx_id")


def read_ids(path: Path) -> list[int]:
    if not path.exists():
        return []
    return [int(line) for line in path.read_text(encoding="utf-8").split() if line.strip()]


def fetch_language(lang: str, candidates: list[int], outdir: Path, target: int = TARGET,
                   runner=subprocess.run, sleeper=time.sleep) -> collections.Counter:
    """Fetch issues for one language until `target` are held or the candidates run out."""
    stats = collections.Counter()
    issues_path = outdir / f"gh_issues_{lang}.jsonl"
    tried_path = outdir / f"gh_tried_{lang}.txt"
    outdir.mkdir(parents=True, exist_ok=True)
    have = 0
    if issues_path.exists():
        with issues_path.open(encoding="utf-8") as fh:
            have = sum(1 for _ in fh)
    tried = set(read_ids(tried_path))
    stats["tried_before"] = len(tried)
    errors = 0
    calls = 0
    with issues_path.open("a", encoding="utf-8") as out, tried_path.open("a", encoding="utf-8") as triedfh:
        for repo_id in candidates:
            if have >= target:
                break
            if repo_id in tried:
                continue
            calls += 1
            if calls == 1 or calls % RATE_EVERY == 0:
                wait_for_quota(runner, sleeper)
            stats["attempted"] += 1
            triedfh.write(f"{repo_id}\n")  # attempted, so never tried again
            triedfh.flush()
            try:
                repo = run_gh([f"/repositories/{repo_id}"], runner)
                full_name, license_id = repo_record(repo)
                stats["resolved"] += 1
                if license_id not in LICENCES:
                    stats["licence_dropped"] += 1
                    continue
                issues = run_gh([f"/repos/{full_name}/issues?state=all&sort=comments&direction=desc&per_page=50"], runner)
                stats["issues_listed"] += len(issues)
            except (subprocess.CalledProcessError, ValueError, KeyError, TypeError):
                stats["api_error"] += 1
                errors += 1
                if errors >= MAX_CONSECUTIVE_ERRORS:
                    raise RuntimeError(f"{lang}: {errors} API calls in a row failed, stopping")
                continue
            errors = 0
            issue = select_issue(repo_id, issues, lang)
            if issue is None:
                stats["no_usable_issue"] += 1
                continue
            row = {"repo_id": repo_id, "full_name": full_name, "license": license_id,
                   "number": issue["number"], "html_url": issue["html_url"],
                   "created_at": issue["created_at"], "title": (issue.get("title") or "").strip(),
                   "body": (issue.get("body") or "").strip()}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            have += 1
            stats["kept"] += 1
    stats["held"] = have
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default=str(DEFAULT_CANDIDATES))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--target", type=int, default=TARGET)
    ap.add_argument("--langs", default=",".join(LANGS))
    args = ap.parse_args()
    cand_dir = Path(args.candidates)
    outdir = Path(args.out)
    print(f"{'lang':>4} {'candidates':>10} {'tried':>7} {'attempted':>9} {'resolved':>8} "
          f"{'licence':>7} {'no issue':>8} {'errors':>6} {'kept':>5} {'held':>5}")
    for lang in args.langs.split(","):
        path = cand_dir / f"gh_candidates_{lang}.txt"
        if not path.exists():
            raise SystemExit(f"no candidate file {path}")
        cands = read_ids(path)
        stats = fetch_language(lang, cands, outdir, args.target)
        print(f"{lang:>4} {len(cands):>10} {stats['tried_before']:>7} {stats['attempted']:>9} "
              f"{stats['resolved']:>8} {stats['licence_dropped']:>7} {stats['no_usable_issue']:>8} "
              f"{stats['api_error']:>6} {stats['kept']:>5} {stats['held']:>5}")


if __name__ == "__main__":
    main()
