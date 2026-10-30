# SPDX-License-Identifier: Apache-2.0
"""Captures in parts, and how they are put together for `score`.

Every capture of texts (AB-1, R3, PIIMB, the round trip) runs on one
shard of its group: the whole group (`1/1`, the default) or a contiguous
run of its texts, in the order they are captured, balanced by characters,
so a CI job each can capture a long group within its time limit. Shard k
of n holds the rows with between (k-1)/n and k/n of the group's
characters ahead of them.

A part is a directory `parts/<group>-<preset>-<k>-of-<n>/` of the work
directory holding what the capture wrote (checkpoints, PIIMB spans or the
round trip's counts) and, once the capture finished and its output was
checked, PART.json: which shard, and how many rows of each set the shard
and the whole group hold. `assemble` puts the parts together where
`score` reads them, only when every shard of a group is there, each once,
with every row of each set once; anything else is an error naming the
part, never a row.

`--limit` (dry runs only) keeps the first rows of each set; the work
directory and every part it writes are marked, and `assemble` refuses
them, so a limited capture is never scored."""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pipeline import artifact, settings

PART_MARKER = "PART.json"
LIMIT_MARKER = "LIMITED.json"
CHECKPOINT_GROUPS = ("ab1", "r3")
PIIMB_GROUP = "piimb"
ROUNDTRIP_GROUP = "roundtrip"
TEXT_GROUPS = (*CHECKPOINT_GROUPS, PIIMB_GROUP, ROUNDTRIP_GROUP)
ROUNDTRIP_FILE = "roundtrip.json"
SHARD_PATTERN = re.compile(r"([1-9][0-9]*)/([1-9][0-9]*)")


class PartError(Exception):
    """The parts of a capture are not every row of its group, once."""


@dataclass(frozen=True)
class Shard:
    """Shard `index` (from 1) of `count`."""

    index: int
    count: int

    def __post_init__(self) -> None:
        if not 1 <= self.index <= self.count:
            raise ValueError(f"shard {self.index} of {self.count}: a shard is 1 to its count")

    @classmethod
    def parse(cls, text: str) -> Shard:
        m = SHARD_PATTERN.fullmatch(text)
        if m is None:
            raise ValueError(f"--shard {text!r}: give K/N, shard K of N, from 1")
        return cls(int(m.group(1)), int(m.group(2)))

    @property
    def label(self) -> str:
        return f"{self.index}-of-{self.count}"


WHOLE = Shard(1, 1)


def shard_of(before: int, total: int, count: int) -> int:
    """The shard (from 1) of a row with `before` of the group's `total`
    characters ahead of it."""
    if total == 0:
        return 1
    return min(count, before * count // total + 1)


def part_name(group: str, preset: str, shard: Shard) -> str:
    return f"{group}-{preset}-{shard.label}"


def _rows(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield line, json.loads(line)


def select(full: Path, out: Path, shard: Shard, limit: int | None = None) -> tuple[dict[str, int], dict[str, int]]:
    """Write to `out` the rows of the texts `full` that are in `shard`,
    after keeping the first `limit` rows of each set when given. Returns
    the rows of each set in the shard and in the whole (limited) group.
    `out` appears whole or not at all."""
    kept: list[tuple[str, int]] = []
    seen: Counter[str] = Counter()
    for _, row in _rows(full):
        seen[row["dataset"]] += 1
        if limit is None or seen[row["dataset"]] <= limit:
            kept.append((row["dataset"], len(row["text"])))
    total = sum(n for _, n in kept)
    totals: Counter[str] = Counter(d for d, _ in kept)
    mine: list[bool] = []
    before = 0
    for _, n in kept:
        mine.append(shard_of(before, total, shard.count) == shard.index)
        before += n
    rows: Counter[str] = Counter()
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f"{out.name}.{os.getpid()}.partial")
    seen.clear()
    position = 0
    with partial.open("w", encoding="utf-8") as f:
        for line, row in _rows(full):
            seen[row["dataset"]] += 1
            if limit is not None and seen[row["dataset"]] > limit:
                continue
            if mine[position]:
                f.write(line if line.endswith("\n") else line + "\n")
                rows[row["dataset"]] += 1
            position += 1
    os.replace(partial, out)
    return {d: rows[d] for d in totals if rows[d]}, dict(totals)


# A part's own output ---------------------------------------------------------------

def checkpoint_file(preset: str, dataset: str) -> str:
    return f"{settings.tool_name(preset)}-{dataset}.jsonl"


def piimb_file(preset: str) -> str:
    return f"piimb-{preset}.jsonl"


def rows_by_set(path: Path) -> dict[str, int]:
    """The rows of each set of a spans file whose rows name their set."""
    return dict(Counter(row["dataset"] for _, row in _rows(path)))


def expected_files(group: str, preset: str, rows: dict[str, int]) -> set[str]:
    if group in CHECKPOINT_GROUPS:
        return {checkpoint_file(preset, d) for d in rows}
    if group == PIIMB_GROUP:
        return {piimb_file(preset)} if rows else set()
    return {ROUNDTRIP_FILE}


def check_output(part: Path, group: str, preset: str, rows: dict[str, int]) -> None:
    """Raise unless `part` holds exactly the files its capture writes, each
    offsets, labels, scores or counts only, with a row for every text of
    the shard."""
    expected = expected_files(group, preset, rows)
    present = {p.name for p in part.iterdir() if p.name != PART_MARKER}
    if present != expected:
        raise PartError(f"{part.name}: holds {sorted(present)}, its capture writes {sorted(expected)}")
    if group in CHECKPOINT_GROUPS:
        for dataset, n in rows.items():
            got = artifact.check_spans(part / checkpoint_file(preset, dataset))
            if got != n:
                raise PartError(f"{part.name}: {got} rows of {dataset} captured for {n} texts")
    elif group == PIIMB_GROUP and rows:
        path = part / piimb_file(preset)
        artifact.check_spans(path)
        if rows_by_set(path) != rows:
            raise PartError(f"{part.name}: the PIIMB rows captured are not one per text of the shard")
    elif group == ROUNDTRIP_GROUP:
        result = artifact.check_roundtrip(json.loads((part / ROUNDTRIP_FILE).read_text(encoding="utf-8")))
        if result["docs"] != sum(rows.values()):
            raise PartError(f"{part.name}: the round trip ran on {result['docs']} texts for {sum(rows.values())}")


def write_marker(part: Path, group: str, preset: str, shard: Shard, rows: dict[str, int],
                 totals: dict[str, int], limit: int | None) -> None:
    """PART.json, last: a part without it is a capture that did not finish."""
    marker = {"group": group, "preset": preset, "shard": [shard.index, shard.count],
              "rows": rows, "totals": totals, "limit": limit}
    (part / PART_MARKER).write_text(json.dumps(marker, indent=1, sort_keys=True) + "\n", encoding="utf-8")


# Putting the parts together ---------------------------------------------------------

@dataclass(frozen=True)
class Part:
    path: Path
    group: str
    preset: str
    shard: Shard
    rows: dict[str, int]
    totals: dict[str, int]
    limit: int | None


def read_parts(parts: Path) -> list[Part]:
    """Every finished part under `parts`; a part without PART.json, or one
    whose directory name is not its marker's, is an error."""
    found = []
    for path in sorted(p for p in parts.iterdir() if p.is_dir()) if parts.is_dir() else []:
        marker = path / PART_MARKER
        if not marker.is_file():
            raise PartError(f"{path.name}: no {PART_MARKER}, its capture did not finish (capture it again, or --resume)")
        m = json.loads(marker.read_text(encoding="utf-8"))
        part = Part(path, m["group"], m["preset"], Shard(*m["shard"]), m["rows"], m["totals"], m["limit"])
        if path.name != part_name(part.group, part.preset, part.shard):
            raise PartError(f"{path.name}: its {PART_MARKER} says {part_name(part.group, part.preset, part.shard)}")
        found.append(part)
    return found


def _complete(group: str, preset: str, parts: list[Part]) -> list[Part]:
    """The parts of one capture, in shard order, when they are all of its
    shards, once, and their rows add up to the group's; else raise."""
    name = f"{group} {preset}"
    if any(p.limit is not None for p in parts):
        raise PartError(f"{name}: a limited capture (a dry run) is never scored")
    counts = {p.shard.count for p in parts}
    if len(counts) != 1:
        raise PartError(f"{name}: parts of different splits ({sorted(counts)} shards)")
    count = counts.pop()
    have = sorted(p.shard.index for p in parts)
    missing = sorted(set(range(1, count + 1)) - set(have))
    if missing:
        raise PartError(f"{name}: shard {', '.join(map(str, missing))} of {count} not captured")
    if len({json.dumps(p.totals, sort_keys=True) for p in parts}) != 1:
        raise PartError(f"{name}: the parts were cut from different texts")
    added: Counter[str] = Counter()
    for p in parts:
        added.update(p.rows)
    if dict(added) != {d: n for d, n in parts[0].totals.items() if n}:
        raise PartError(f"{name}: the shards do not hold every row of the group once")
    return sorted(parts, key=lambda p: p.shard.index)


def _concat(sources: list[Path], target: Path, keyed_by_set: bool) -> None:
    """`target`, the rows of `sources` in order; a row of a set and index
    seen twice is an error. Only a regular file is ever replaced."""
    if target.is_symlink():
        raise PartError(f"{target} is a link, not an output of the parts: remove it")
    seen: set[tuple[str, int]] = set()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.{os.getpid()}.partial")
    with partial.open("w", encoding="utf-8") as out:
        for source in sources:
            for line, row in _rows(source):
                key = (row["dataset"] if keyed_by_set else "", int(row["idx"]))
                if key in seen:
                    raise PartError(f"{target.name}: a row captured twice, in {source.parent.name}")
                seen.add(key)
                out.write(line if line.endswith("\n") else line + "\n")
    os.replace(partial, target)


def _merge_roundtrip(parts: list[Part], target: Path) -> None:
    results = [json.loads((p.path / ROUNDTRIP_FILE).read_text(encoding="utf-8")) for p in parts]
    failing: dict[str, list[int]] = {}
    for r in results:
        for dataset, idx in r["failing_idx"].items():
            failing.setdefault(dataset, []).extend(idx)
    merged = {
        "docs": sum(r["docs"] for r in results),
        "masked": sum(r["masked"] for r in results),
        "roundtrip_failures": sum(r["roundtrip_failures"] for r in results),
        "failing_idx": failing,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact.check_roundtrip(merged)) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Targets:
    """Where `score` reads each capture."""

    checkpoints: Path
    spans: Path
    roundtrip: Path


def assemble(parts_dir: Path, targets: Targets) -> list[tuple[str, str]]:
    """Put every capture's parts together in `targets`; returns the
    (group, preset) of each. Raises naming any capture whose parts are not
    every row of its group once."""
    by_capture: dict[tuple[str, str], list[Part]] = {}
    for part in read_parts(parts_dir):
        by_capture.setdefault((part.group, part.preset), []).append(part)
    for (group, preset), parts in sorted(by_capture.items()):
        ordered = _complete(group, preset, parts)
        if group in CHECKPOINT_GROUPS:
            for dataset in ordered[0].totals:
                name = checkpoint_file(preset, dataset)
                sources = [p.path / name for p in ordered if p.rows.get(dataset)]
                _concat(sources, targets.checkpoints / name, keyed_by_set=False)
        elif group == PIIMB_GROUP:
            sources = [p.path / piimb_file(preset) for p in ordered if p.rows]
            _concat(sources, targets.spans / piimb_file(preset), keyed_by_set=True)
        else:
            _merge_roundtrip(ordered, targets.roundtrip)
    return sorted(by_capture)
