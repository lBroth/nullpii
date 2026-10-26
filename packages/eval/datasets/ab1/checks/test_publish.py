# SPDX-License-Identifier: Apache-2.0
"""Offline tests for the publish / rebuild pair.

    .venv/bin/python -I checks/test_publish.py

Three offline fetchers drive the whole `gen/real/rebuild_public.py` script against a published file
built in a scratch directory from the real gold and the local issue pool:
  1. the local pool itself        -> all 72 documents rebuilt, whole file sha256 == source_sha256;
  2. one issue with an edited body -> exactly that document reported as changed;
  3. one issue returning 404       -> exactly that document reported as gone, the run finishes.

Never prints document or issue text: ids, counts and hashes only.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp_test_publish"
SCRIPTS = ROOT / "gen" / "real"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pool_issues() -> dict[tuple[str, str, int], dict]:
    """The local issue pool as `(owner, repo, number) -> {title, body}` (never printed)."""
    issues = {}
    for lang in ("it", "de", "fr", "es"):
        for row in read_jsonl(ROOT / "cache" / "real" / f"gh_issues_{lang}.jsonl"):
            owner, repo = row["full_name"].split("/", 1)
            issues[(owner, repo, int(row["number"]))] = {"title": row["title"], "body": row["body"]}
    return issues


def edited(issue: dict) -> dict:
    """The same issue with one character of its body changed (what an edit after the fetch looks like)."""
    body = issue["body"]
    n = len(body) // 2
    if len(body) < 2:
        raise ValueError("issue body too short to edit")
    return {"title": issue["title"], "body": body[:n] + ("X" if body[n] != "X" else "Y") + body[n + 1:]}


def fetcher_from(issues: dict, edit: tuple | None = None, missing: tuple | None = None,
                 gone_cls=Exception):
    def fetch(owner, repo, number, token=None):
        key = (owner, repo, number)
        if key == missing:
            raise gone_cls(f"HTTP 404 for issue {owner}/{repo}#{number}")
        issue = issues[key]
        return edited(issue) if key == edit else dict(issue)
    return fetch


def main() -> int:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    failures = []

    def check(name: str, expected, found) -> None:
        ok = expected == found
        print(f"{'PASS' if ok else 'FAIL'}  {name}  —  expected {expected!r}, found {found!r}", flush=True)
        if not ok:
            failures.append(name)

    publish = load("ab1_publish", SCRIPTS / "publish.py")
    rebuild = load("ab1_rebuild", SCRIPTS / "rebuild_public.py")

    public = TMP / "ab1-public.jsonl"
    meta_path = TMP / "ab1-public.meta.json"
    meta = publish.publish(ROOT / "data" / "ab1.jsonl", ROOT / "cache" / "real", public, meta_path)

    check("publish: github documents", 72, meta["github_documents"])
    check("publish: rows", 1200, len(read_jsonl(public)))
    check("publish: meta public_sha256 matches the file", meta["public_sha256"], sha256_file(public))
    check("publish: deterministic (matches data/ab1-public.jsonl)",
          sha256_file(ROOT / "data" / "ab1-public.jsonl"), sha256_file(public))
    check("publish: no text on a GitHub document", 0,
          sum(1 for r in read_jsonl(public) if "segments" in r and "text" in r))
    check("publish: every GitHub document has segments and a hash", 72,
          sum(1 for r in read_jsonl(public) if "segments" in r and "text_sha256" in r))
    issues = pool_issues()
    source_sha = meta["source_sha256"]
    gh_rows = [r for r in read_jsonl(public) if "segments" in r]

    def pool_text(key: tuple) -> str:
        issue = issues[key]
        return publish.issue_text(issue["title"], issue["body"])

    def joined(row: dict) -> str:
        return publish.join_segments(row["segments"], pool_text(rebuild.parse_row(row["carrier"]["row"])))

    check("publish: joining the segments from the local pool reproduces every document text "
          "(sha256 match)", 72,
          sum(1 for r in gh_rows if hashlib.sha256(joined(r).encode()).hexdigest() == r["text_sha256"]))
    check("publish: carrier + literal characters equal the sum of the document texts", 0,
          sum(len(joined(r)) for r in gh_rows) - (meta["carrier_chars"] + meta["literal_chars"]))
    check("publish: every segment is a carrier range or a non-empty literal", 0,
          sum(1 for r in gh_rows for s in r["segments"]
              if not (("carrier" in s and "text" not in s and 0 <= s["carrier"][0] < s["carrier"][1])
                      or ("text" in s and "carrier" not in s and s["text"]))))

    # 1. the pool itself: everything rebuilds, the whole file equals the source
    out1 = TMP / "rebuilt-pool.jsonl"
    stats1 = rebuild.rebuild(public, meta_path, out1, fetcher=fetcher_from(issues), pause=0.0)
    check("rebuild/pool: documents", 72, stats1["documents"])
    check("rebuild/pool: rebuilt", 72, stats1["rebuilt"])
    check("rebuild/pool: changed", ([], 0), (stats1["changed_ids"], stats1["changed"]))
    check("rebuild/pool: gone", ([], 0), (stats1["gone_ids"], stats1["gone"]))
    check("rebuild/pool: whole file sha256 == source_sha256", True, stats1["whole_file_matches"])
    check("rebuild/pool: file sha256 == source_sha256", source_sha, sha256_file(out1))

    # 2. one issue edited after the fetch: exactly that document is reported
    edit_key = rebuild.parse_row(gh_rows[0]["carrier"]["row"])
    edit_id = gh_rows[0]["id"]
    out2 = TMP / "rebuilt-edited.jsonl"
    stats2 = rebuild.rebuild(public, meta_path, out2,
                             fetcher=fetcher_from(issues, edit=edit_key), pause=0.0)
    check("rebuild/edited: documents", 72, stats2["documents"])
    check("rebuild/edited: changed ids (exactly the edited document)", [edit_id], stats2["changed_ids"])
    check("rebuild/edited: rebuilt", 71, stats2["rebuilt"])
    check("rebuild/edited: gone", [], stats2["gone_ids"])
    check("rebuild/edited: whole file differs from the source", False, stats2["whole_file_matches"])
    doc = next(r for r in read_jsonl(out2) if r["id"] == edit_id)
    was = publish.join_segments(gh_rows[0]["segments"], pool_text(edit_key))
    check("rebuild/edited: the reported document is written with the issue's new text",
          [len(was), 1], [len(doc["text"]), sum(1 for a, b in zip(was, doc["text"]) if a != b)])
    check("rebuild/edited: the 71 others carry their original text (sha256 match)", 71,
          sum(1 for r in gh_rows[1:]
              if hashlib.sha256(next(x["text"] for x in read_jsonl(out2) if x["id"] == r["id"])
                                .encode()).hexdigest() == r["text_sha256"]))

    # 3. one issue gone (404): reported, the run still finishes
    gone_key = rebuild.parse_row(gh_rows[1]["carrier"]["row"])
    gone_id = gh_rows[1]["id"]
    out3 = TMP / "rebuilt-gone.jsonl"
    stats3 = rebuild.rebuild(public, meta_path, out3,
                             fetcher=fetcher_from(issues, missing=gone_key,
                                                  gone_cls=rebuild.IssueGone), pause=0.0)
    check("rebuild/gone: documents", 72, stats3["documents"])
    check("rebuild/gone: gone ids (exactly the missing issue's document)", [gone_id], stats3["gone_ids"])
    check("rebuild/gone: rebuilt", 71, stats3["rebuilt"])
    check("rebuild/gone: changed", [], stats3["changed_ids"])
    check("rebuild/gone: every document still written", 1200, len(read_jsonl(out3)))
    gone_row = next(r for r in read_jsonl(out3) if r["id"] == gone_id)
    check("rebuild/gone: the gone document kept its literal characters only",
          len(publish.join_segments(gh_rows[1]["segments"], "")), len(gone_row["text"]))
    check("rebuild/gone: the gone document kept its carrier record", [True, True],
          [gone_row["carrier"] == gh_rows[1]["carrier"], "text" in gone_row and "segments" not in gone_row])

    shutil.rmtree(TMP)
    print(f"{'FAILED' if failures else 'OK'}: {len(failures)} failing check(s) "
          f"{failures if failures else ''}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
