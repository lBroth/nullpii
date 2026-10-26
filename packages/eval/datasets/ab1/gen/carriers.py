# SPDX-License-Identifier: Apache-2.0
"""Carrier pool: candidate texts from the pinned carrier datasets, and excerpt cutting.

Two pools, both deterministic:
  - cache/pool.jsonl, built from the two English parquet datasets (SWE-rebench trajectories and
    openhands-feedback sessions) by `build_pool()`;
  - cache/pool_real.jsonl, built from the phase-A real pools (cache/real/wildchat_<lang>.jsonl and
    cache/real/gh_issues_<lang>.jsonl) by `build_real_pool()`.
Every candidate gets a priority derived from the master seed and its carrier id; a bucket holds
the candidates in priority order, so the build walks them best first.
"""
from __future__ import annotations

import collections
import heapq
import json
import re
from pathlib import Path

import pyarrow.parquet as pq

from common import (CACHE, EXCERPT_MAX, EXCERPT_MIN, FB_DATASET, FB_PARQUET, FB_REVISION,
                    GH_ISSUES_DATASET, GH_ISSUES_REVISION, REAL_LANGS, SWE_DATASET, SWE_PARQUET,
                    SWE_REVISION, WILDCHAT_DATASET, WILDCHAT_REVISION, derive_seed)

POOL_PATH = CACHE / "pool.jsonl"
REAL_POOL_PATH = CACHE / "pool_real.jsonl"
REAL_DIR = CACHE / "real"
KEEP_PER_BUCKET = 1200
MAX_FIELD_CHARS = 80_000

TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\)|^\s+at [\w$.<>]+ ?\(.*:\d+(?::\d+)?\)$|^panic: ", re.M)
LOGLINE_RE = re.compile(
    r"^.{0,60}\b(?:DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b[:\] ]", re.M)
CD_PREFIX_RE = re.compile(r"^\s*cd\s+\S+\s*&&\s*")
VIEW_HEADER_RE = re.compile(r"^Here's the result of running `cat -n` on (\S+):\n")
ISSUE_RE = re.compile(r"<issue_description>\n?(.*?)\n?</issue_description>", re.S)

CONFIG_EXT = {"toml", "ini", "cfg", "yaml", "yml", "json", "env", "conf", "xml", "properties", "lock", "sh", "txt"}
CONFIG_NAMES = {"Dockerfile", "Makefile", "Procfile", "Pipfile", "tox.ini", "setup.cfg", "pyproject.toml",
                ".env", ".env.example", "docker-compose.yml", "requirements.txt", "MANIFEST.in", ".gitignore"}
SOURCE_EXT = {"py", "js", "ts", "tsx", "jsx", "go", "rb", "java", "c", "h", "cpp", "rs", "php", "pyx", "kt", "scala", "cs", "swift", "sql", "html", "css"}
DOC_EXT = {"md", "rst"}
EN_STOP = {"the", "and", "to", "of", "is", "in", "it", "that", "this", "for", "with", "be", "on", "not", "you", "are", "can", "should", "when", "from", "have", "if", "but", "use"}
NON_EN_STOP = {"el", "la", "de", "que", "los", "las", "una", "por", "para", "und", "der", "die", "das", "ist", "nicht", "les", "des", "est", "une", "pour", "il", "che", "di", "per", "non", "sono", "del"}


def file_subtype(path: str) -> str | None:
    name = path.rstrip("/").rsplit("/", 1)[-1]
    if name in CONFIG_NAMES or name.startswith(".env") or name.startswith("Dockerfile"):
        return "config"
    if "." not in name:
        return None
    ext = name.rsplit(".", 1)[-1].lower()
    if ext in CONFIG_EXT:
        return "config"
    if ext in SOURCE_EXT:
        return "source"
    if ext in DOC_EXT:
        return "doc"
    return None


def shell_subtype(command: str) -> str:
    c = CD_PREFIX_RE.sub("", command.strip())
    c = re.sub(r"^(?:[A-Z_]+=\S+\s+)+", "", c)
    first = c.split()[0] if c.split() else ""
    two = " ".join(c.split()[:2])
    if two.startswith("git diff") or two.startswith("git show"):
        return "git_diff"
    if two.startswith("git log"):
        return "git_log"
    if first == "git":
        return "git_other"
    if re.search(r"\bpytest\b|\bunittest\b|\btox\b|\bnosetests\b|npm (?:run )?test|\bjest\b|yarn test|go test", c):
        return "test_run"
    if re.search(r"\bpip3? install\b|\bpoetry (?:install|add)\b|npm (?:install|i|ci)\b|yarn add|apt-get|\bconda install", c):
        return "install"
    if first in ("ls", "find", "tree", "du", "stat"):
        return "listing"
    if first in ("grep", "rg", "ag", "egrep"):
        return "grep"
    if first in ("curl", "wget", "http"):
        return "http"
    if first in ("env", "printenv", "export", "set"):
        return "env"
    if first in ("docker", "kubectl", "docker-compose", "podman", "helm"):
        return "container"
    if first in ("python", "python3", "node", "bash", "sh", "make", "npm", "./manage.py"):
        return "script"
    return "other"


def is_file_dump_command(command: str) -> str | None:
    c = CD_PREFIX_RE.sub("", command.strip())
    m = re.match(r"^(?:cat|head(?: -n ?\d+)?|tail(?: -n ?\d+)?|sed -n '?[\d,]+p'?)\s+([^\s|;&>]+)\s*$", c)
    if not m:
        return None
    return file_subtype(m.group(1))


CODEISH_LINE = re.compile(r"^\s*(?:File \"|at |[>$#|+\-@]|\w+Error\b|\w+Exception\b|[\[{}\]()]|```|\d+[:\t])|[;{}()=<>]\s*$|^\s{4,}")
NON_LATIN = re.compile("[\u0370-\u03FF\u0400-\u052F\u0590-\u06FF\u0900-\u0DFF\u0E00-\u0FFF\u1100-\u11FF\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF]")


def prose_of(text: str) -> str:
    """The natural-language lines of a message (code, log and traceback lines removed)."""
    out, fence = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence or CODEISH_LINE.search(line):
            continue
        out.append(line)
    return "\n".join(out)


def is_english(text: str) -> bool:
    if len(NON_LATIN.findall(text)) > 2:
        return False
    prose = prose_of(text)
    words = re.findall("[a-zA-Z\u00C0-\u00FF]+", prose.lower())
    if len(words) < 25:
        return False
    en = sum(w in EN_STOP for w in words)
    other = sum(w in NON_EN_STOP for w in words)
    return en >= 0.08 * len(words) and other < max(2, en / 6)


def looks_like_log(text: str) -> bool:
    return bool(TRACEBACK_RE.search(text)) or len(LOGLINE_RE.findall(text)) >= 3


class Pool:
    def __init__(self) -> None:
        self.heaps: dict[tuple[str, str], list] = {}

    def add(self, kind: str, sub: str, cand: dict) -> None:
        if len(cand["field_text"]) > MAX_FIELD_CHARS:
            return
        key = (kind, sub)
        heap = self.heaps.setdefault(key, [])
        prio = -derive_seed("pool", cand["cid"])
        item = (prio, cand["cid"], cand)
        if len(heap) < KEEP_PER_BUCKET:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)

    def dump(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as fh:
            for key in sorted(self.heaps):
                for _, _, cand in sorted(self.heaps[key], key=lambda x: (-x[0], x[1])):
                    fh.write(json.dumps({"kind": key[0], "sub": key[1], **cand}, ensure_ascii=False) + "\n")


def _cand(dataset: str, revision: str, row: str, text: str, group: str) -> dict:
    return {"cid": f"{dataset}|{row}", "dataset": dataset, "revision": revision, "row": row,
            "field_text": text, "group": group}


def scan_swe(pool: Pool) -> None:
    pf = pq.ParquetFile(SWE_PARQUET)
    for rg in range(pf.metadata.num_row_groups):
        table = pf.read_row_group(rg, columns=["trajectory_id", "repo", "trajectory"]).to_pylist()
        for rec in table:
            scan_swe_trajectory(pool, rec)
        print("swe row group", rg, "done", flush=True)


def scan_swe_trajectory(pool: Pool, rec: dict) -> None:
    tid, repo, traj = rec["trajectory_id"], rec["repo"], rec["trajectory"]
    calls: dict[str, tuple[str, dict]] = {}
    user_seen = False
    for mi, msg in enumerate(traj):
        role = msg["role"]
        if role == "user" and not user_seen:
            user_seen = True
            content = msg["content"] or ""
            m = ISSUE_RE.search(content)
            if m and len(m.group(1).strip()) >= EXCERPT_MIN:
                row = f"{tid}/trajectory[{mi}].content"
                c = _cand(SWE_DATASET, SWE_REVISION, row, content, repo)
                c["span"] = [m.start(1), m.end(1)]
                pool.add("ticket", "issue", c)
            continue
        if role == "assistant" and msg["tool_calls"]:
            for ti, tc in enumerate(msg["tool_calls"]):
                fn = tc["function"]
                try:
                    args = json.loads(fn["arguments"])
                except (json.JSONDecodeError, TypeError):
                    args = {}
                calls[tc["id"]] = (fn["name"], args)
                raw = fn["arguments"] or ""
                if fn["name"] in ("str_replace_editor", "execute_bash") and EXCERPT_MIN <= len(raw) <= EXCERPT_MAX:
                    sub = fn["name"] + ":" + str(args.get("command", ""))[:12] if fn["name"] == "str_replace_editor" else "execute_bash"
                    row = f"{tid}/trajectory[{mi}].tool_calls[{ti}].function.arguments"
                    pool.add("tool_json", sub, _cand(SWE_DATASET, SWE_REVISION, row, raw, repo))
            continue
        if role != "tool":
            continue
        name, args = calls.get(msg["tool_call_id"], (msg["name"], {}))
        content = msg["content"] or ""
        if len(content) < EXCERPT_MIN:
            continue
        row = f"{tid}/trajectory[{mi}].content"
        if name == "str_replace_editor" and args.get("command") == "view":
            m = VIEW_HEADER_RE.match(content)
            sub = file_subtype(args.get("path", "")) if m else None
            if sub:
                pool.add("file", sub, _cand(SWE_DATASET, SWE_REVISION, row, content, repo))
            continue
        if name == "execute_bash":
            command = args.get("command", "")
            if looks_like_log(content):
                pool.add("log", "bash", _cand(SWE_DATASET, SWE_REVISION, row, content, repo))
                continue
            fsub = is_file_dump_command(command)
            if fsub:
                pool.add("file", fsub + "_cat", _cand(SWE_DATASET, SWE_REVISION, row, content, repo))
                continue
            c = _cand(SWE_DATASET, SWE_REVISION, row, content, repo)
            c["command"] = command
            pool.add("shell", shell_subtype(command), c)


def scan_feedback(pool: Pool) -> None:
    table = pq.read_table(FB_PARQUET).to_pylist()
    for ri, rec in enumerate(table):
        group = f"fb{ri}"
        for si, step in enumerate(rec["trajectory"]):
            content = step["content"] or ""
            src, action, obs = step["source"], step["action"], step["observation"]
            row = f"{ri}/trajectory[{si}].content"
            if src == "user" and action == "message":
                if len(content.strip()) >= EXCERPT_MIN and is_english(content):
                    pool.add("prompt", "user_message", _cand(FB_DATASET, FB_REVISION, row, content, group))
                continue
            if src == "agent" and action in ("run", "run_ipython", "edit", "write") and step["extras"]:
                raw = step["extras"]
                if EXCERPT_MIN <= len(raw) <= EXCERPT_MAX:
                    try:
                        json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    xrow = f"{ri}/trajectory[{si}].extras"
                    pool.add("tool_json", "fb:" + action, _cand(FB_DATASET, FB_REVISION, xrow, raw, group))
                continue
            if obs == "run" and len(content) >= EXCERPT_MIN:
                try:
                    command = json.loads(step["extras"] or "{}").get("command", "")
                except json.JSONDecodeError:
                    command = ""
                if looks_like_log(content):
                    pool.add("log", "fb_run", _cand(FB_DATASET, FB_REVISION, row, content, group))
                    continue
                fsub = is_file_dump_command(command)
                if fsub:
                    pool.add("file", "fb_" + fsub + "_cat", _cand(FB_DATASET, FB_REVISION, row, content, group))
                    continue
                c = _cand(FB_DATASET, FB_REVISION, row, content, group)
                c["command"] = command
                pool.add("shell", "fb_" + shell_subtype(command), c)
                continue
            if obs == "run_ipython" and len(content) >= EXCERPT_MIN and looks_like_log(content):
                pool.add("log", "fb_ipython", _cand(FB_DATASET, FB_REVISION, row, content, group))


def build_pool() -> None:
    pool = Pool()
    scan_feedback(pool)
    scan_swe(pool)
    pool.dump(POOL_PATH)


def load_pool() -> list[dict]:
    with POOL_PATH.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


# ------------------------------------------------------------------ phase-A real pools

def normalise(text: str) -> str:
    """The carrier normalisation: strip leading newlines and trailing whitespace, otherwise verbatim."""
    return text.lstrip("\n\r").rstrip()


def issue_text(title: str, body: str) -> str:
    """A GitHub issue as the carrier text, built as gen/real/gh_fetch.py built it."""
    title, body = (title or "").strip(), (body or "").strip()
    return normalise(f"{title}\n\n{body}" if body else title)


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def real_candidates() -> list[dict]:
    """Every selected phase-A candidate: WildChat first user turns (prompts) and GitHub issues (tickets)."""
    out: list[dict] = []
    for lang in REAL_LANGS:
        for row in read_jsonl(REAL_DIR / f"wildchat_{lang}.jsonl"):
            row_id = f"{row['conversation_hash']}/turn{row['turn_index']}"
            out.append({"kind": "prompt", "sub": f"wildchat:{lang}", "cid": f"{WILDCHAT_DATASET}|{row_id}",
                        "dataset": WILDCHAT_DATASET, "revision": WILDCHAT_REVISION, "row": row_id,
                        "field_text": normalise(row["text"]), "group": row["conversation_hash"], "lang": lang})
        for row in read_jsonl(REAL_DIR / f"gh_issues_{lang}.jsonl"):
            row_id = f"{row['full_name']}#{row['number']}"
            out.append({"kind": "ticket", "sub": f"gh_issue:{lang}", "cid": f"{GH_ISSUES_DATASET}|{row_id}",
                        "dataset": GH_ISSUES_DATASET, "revision": GH_ISSUES_REVISION, "row": row_id,
                        "field_text": issue_text(row.get("title", ""), row.get("body", "")),
                        "group": row["full_name"], "lang": lang, "url": row["html_url"], "license": row["license"]})
    return out


def build_real_pool() -> None:
    """Write cache/pool_real.jsonl: one bucket per (kind, source and language), best priority first."""
    buckets: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for cand in real_candidates():
        buckets[(cand["kind"], cand["sub"])].append(cand)
    with REAL_POOL_PATH.open("w", encoding="utf-8") as fh:
        for key in sorted(buckets):
            for cand in sorted(buckets[key], key=lambda c: (derive_seed("pool", c["cid"]), c["cid"])):
                fh.write(json.dumps(cand, ensure_ascii=False) + "\n")


def load_real_pool() -> list[dict]:
    if not REAL_POOL_PATH.exists():
        build_real_pool()
    return read_jsonl(REAL_POOL_PATH)


def line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def cut_excerpt(text: str, lo: int, hi: int, rng, target: int) -> tuple[int, int] | None:
    """Pick [start, end) inside text[lo:hi] on line boundaries, EXCERPT_MIN..EXCERPT_MAX chars, ~target long."""
    seg = text[lo:hi]
    starts = [s for s in line_starts(seg)]
    # end positions: before each '\n' and the segment end
    ends = [s - 1 for s in starts[1:]] + [len(seg)]
    n = len(starts)
    order = list(range(n))
    rng.shuffle(order)
    for si in order[: max(8, n)]:
        s = starts[si]
        best = None
        for ei in range(si, n):
            e = ends[ei]
            ln = e - s
            if ln > EXCERPT_MAX:
                break
            if ln >= EXCERPT_MIN:
                best = (s, e)
                if ln >= target:
                    break
        if best:
            s, e = best
            # strip leading/trailing blank lines but keep line boundaries
            while s < e and seg[s] == "\n":
                s += 1
            while e > s and seg[e - 1] in "\n\r":
                e -= 1
            if e - s >= EXCERPT_MIN and (s == 0 or seg[s - 1] == "\n") and (e == len(seg) or seg[e] in "\r\n"):
                return lo + s, lo + e
    return None


if __name__ == "__main__":
    build_pool()
    build_real_pool()
