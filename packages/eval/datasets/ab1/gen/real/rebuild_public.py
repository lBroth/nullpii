# SPDX-License-Identifier: Apache-2.0
"""Rebuild the gold from the published file by re-fetching the GitHub issues.

    python gen/real/rebuild_public.py [--in data/ab1-public.jsonl] [--meta data/ab1-public.meta.json]
                                      [--out ab1.jsonl] [--pause 1.0]

Reads `data/ab1-public.jsonl`, fetches every issue it needs through the GitHub REST API
(`GET https://api.github.com/repos/<owner>/<repo>/issues/<number>`), rebuilds the carrier text
`title + "\\n\\n" + body` with the builder's own normalisation (`carriers.issue_text`, imported from
`gen/`, not copied), fills the `segments` of each GitHub document and checks it against `text_sha256`.
The result is written to `--out` in the gold's key order (`text` restored, `segments` and
`text_sha256` dropped).

An issue edited or deleted after the fetch date (2026-10-24, `carrier.revision`) rebuilds differently:
that is not an error. Such a document is written with whatever text the issue now gives (literals
only, when the issue has disappeared) and reported by id — never its text.

The fetch is one replaceable function (`fetch_issue`); `rebuild()` takes it as an argument, so the
whole script runs offline against a fake fetcher (see checks/test_publish.py).

Prints counts, ids, lengths and hashes only — never document or issue text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carriers import issue_text, read_jsonl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_IN = ROOT / "data" / "ab1-public.jsonl"
DEFAULT_OUT = ROOT / "ab1.jsonl"

API_URL = "https://api.github.com/repos/{owner}/{repo}/issues/{number}"
USER_AGENT = "ab1-rebuild"
TIMEOUT = 30.0
RETRIES = 4          # retries after the first call, for 403/429 and transport errors
BACKOFF = 2.0        # seconds, doubled per retry
MAX_BACKOFF = 60.0


class IssueGone(RuntimeError):
    """The issue is not there any more (404, or a payload without an issue)."""


def parse_row(row: str) -> tuple[str, str, int]:
    """`<owner>/<repo>#<number>` (the carrier row) -> (owner, repo, number)."""
    repo_part, _, num = row.rpartition("#")
    owner, _, repo = repo_part.partition("/")
    if not (owner and repo and num.isdigit()):
        raise ValueError(f"unusable carrier row {row!r}")
    return owner, repo, int(num)


def fetch_issue(owner: str, repo: str, number: int, token: str | None = None,
                sleeper=time.sleep, opener=urllib.request.urlopen) -> dict:
    """Fetch one issue (never a pull request) through the GitHub REST API.

    This is the only function that touches the network; it is replaceable, so every test runs offline.
    Retries with backoff on 403/429 (honouring `Retry-After`) and on transport errors, raises
    `IssueGone` for a missing issue and `urllib.error.HTTPError` for anything else that persists.
    """
    url = API_URL.format(owner=owner, repo=repo, number=number)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    delay = BACKOFF
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, headers=headers)
        try:
            with opener(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as err:
            if err.code == 404:
                raise IssueGone(f"HTTP 404 for issue {owner}/{repo}#{number}") from err
            if err.code in (403, 429) and attempt < RETRIES - 1:
                wait = err.headers.get("Retry-After") if err.headers else None
                pause = min(MAX_BACKOFF, float(wait)) if wait else delay
                print(f"  HTTP {err.code} on {owner}/{repo}#{number}: waiting {pause:.1f}s", flush=True)
                sleeper(pause)
                delay = min(MAX_BACKOFF, delay * 2)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            if attempt == RETRIES - 1:
                raise
            print(f"  {type(err).__name__} on {owner}/{repo}#{number}: waiting {delay:.1f}s", flush=True)
            sleeper(delay)
            delay = min(MAX_BACKOFF, delay * 2)
    if not isinstance(payload, dict) or "pull_request" in payload:
        raise IssueGone(f"no issue for {owner}/{repo}#{number}")
    return {"title": payload.get("title") or "", "body": payload.get("body") or ""}


def join_segments(segments: list[dict], ctext: str) -> str:
    parts = []
    for seg in segments:
        if "carrier" in seg:
            a, b = seg["carrier"]
            parts.append(ctext[a:b])
        else:
            parts.append(seg["text"])
    return "".join(parts)


def meta_path_of(public: Path) -> Path:
    return public.parent / f"{public.stem}.meta.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rebuild(public: Path, meta_path: Path, out: Path, fetcher=fetch_issue,
            token: str | None = None, pause: float = 1.0, sleeper=time.sleep,
            verbose: bool = True) -> dict:
    """Rebuild the gold from the published file; return the run's counts."""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    rows = read_jsonl(public)

    issues: dict[tuple[str, str, int], dict | None] = {}
    fetched = 0
    for row in rows:
        if "segments" not in row:
            continue
        key = parse_row(row["carrier"]["row"])
        if key in issues:
            continue
        if fetched and pause:
            sleeper(pause)  # a pause between requests
        fetched += 1
        try:
            got = fetcher(*key, token=token)
            if verbose:
                print(f"  fetched {key[0]}/{key[1]}#{key[2]}: title {len(got.get('title') or '')}, "
                      f"body {len(got.get('body') or '')} chars", flush=True)
        except IssueGone as err:
            print(f"  gone: {err}", flush=True)
            got = None
        except Exception as err:  # a persistent API error is also a change: reported, not fatal
            print(f"  {type(err).__name__} on {key[0]}/{key[1]}#{key[2]}", flush=True)
            got = None
        issues[key] = got

    stats = {"documents": 0, "rebuilt": 0, "changed": 0, "gone": 0, "issues": len(issues)}
    changed_ids: list[str] = []
    gone_ids: list[str] = []
    out_rows: list[dict] = []
    for row in rows:
        if "segments" in row:
            got = issues[parse_row(row["carrier"]["row"])]
            ctext = issue_text(got["title"], got["body"]) if got else ""
            text = join_segments(row["segments"], ctext)
            stats["documents"] += 1
            if got is None:
                stats["gone"] += 1
                gone_ids.append(row["id"])
            elif hashlib.sha256(text.encode("utf-8")).hexdigest() == row["text_sha256"]:
                stats["rebuilt"] += 1
            else:
                stats["changed"] += 1
                changed_ids.append(row["id"])
        else:
            text = row["text"]
        # the gold's key order, so an unchanged run reproduces the source byte for byte
        out_rows.append({"id": row["id"], "split": row["split"], "kind": row["kind"],
                         "lang": row["lang"], "origin": row["origin"], "carrier": row["carrier"],
                         "text": text, "items": row["items"]})

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    whole = sha256_file(out) == meta["source_sha256"]
    print(f"documents: {len(out_rows)}; GitHub documents rebuilt: {stats['rebuilt']} "
          f"(issues fetched: {stats['issues']})", flush=True)
    print(f"changed: {stats['changed']} {sorted(changed_ids)}", flush=True)
    print(f"gone: {stats['gone']} {sorted(gone_ids)}", flush=True)
    print(f"whole file matches the source sha256: {'yes' if whole else 'no'} "
          f"({sha256_file(out)[:16]})", flush=True)
    stats["whole_file_matches"] = whole
    stats["changed_ids"] = sorted(changed_ids)
    stats["gone_ids"] = sorted(gone_ids)
    return stats


def main(argv: list[str] | None = None, fetcher=fetch_issue) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="src", default=str(DEFAULT_IN))
    ap.add_argument("--meta", default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    args = ap.parse_args(argv)
    src = Path(args.src)
    rebuild(src, Path(args.meta) if args.meta else meta_path_of(src), Path(args.out),
            fetcher=fetcher, token=args.token, pause=args.pause)


if __name__ == "__main__":
    main()
