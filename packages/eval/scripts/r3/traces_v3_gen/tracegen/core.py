# SPDX-License-Identifier: Apache-2.0
"""Segment model: every piece of a document is a Seg; gold values and
distractors are tagged Segs whose offsets are fixed when the final text is
assembled from the insertion structure (never by searching the text)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Union

GOLD_LABELS = (
    "private_person",
    "private_email",
    "private_phone",
    "private_address",
    "private_date",
    "private_url",
    "private_ip",
    "private_mac",
    "account_number",
    "secret",
    "private_passport",
    "private_driver_license",
    "private_vehicle_id",
    "private_geolocation",
)
GOLD_SET = frozenset(GOLD_LABELS)

DISTRACTOR_CLASSES = (
    "machine_timestamp",
    "public_url",
    "reserved_ip",
    "placeholder",
    "identifier",
    "public_entity",
)
DISTRACTOR_SET = frozenset(DISTRACTOR_CLASSES)


@dataclass(frozen=True, slots=True)
class Seg:
    """A run of text. `label` marks a gold value, `cls` a distractor."""

    text: str
    label: str | None = None
    cls: str | None = None

    def __post_init__(self) -> None:
        if self.label is not None and self.cls is not None:
            raise ValueError("segment cannot be both gold and distractor")
        if self.label is not None and self.label not in GOLD_SET:
            raise ValueError(f"invalid gold label {self.label!r}")
        if self.cls is not None and self.cls not in DISTRACTOR_SET:
            raise ValueError(f"invalid distractor class {self.cls!r}")
        if self.tagged:
            if not self.text:
                raise ValueError("empty tagged segment")
            if self.text != self.text.strip():
                raise ValueError(f"tagged segment has outer whitespace: {self.label or self.cls}")

    @property
    def tagged(self) -> bool:
        return self.label is not None or self.cls is not None


Frag = list  # list[Seg]
Part = Union[str, Seg, list, tuple, None]


def F(*parts: Part) -> list[Seg]:
    """Flatten strings, Segs and nested lists into a fragment."""
    out: list[Seg] = []

    def rec(p: Part) -> None:
        if p is None:
            return
        if isinstance(p, str):
            if p:
                out.append(Seg(p))
        elif isinstance(p, Seg):
            out.append(p)
        elif isinstance(p, (list, tuple)):
            for q in p:
                rec(q)
        elif isinstance(p, (int, float)):
            out.append(Seg(str(p)))
        else:
            raise TypeError(f"cannot place {type(p).__name__} in a fragment")

    for p in parts:
        rec(p)
    return out


_SLOT = re.compile(r"⟦(\w+)⟧")


def T(fmt: str, **kw: Part) -> list[Seg]:
    """Fill ⟦name⟧ slots of `fmt` with strings, Segs or fragments."""
    out: list[Seg] = []
    used: set[str] = set()
    pos = 0
    for m in _SLOT.finditer(fmt):
        out.extend(F(fmt[pos:m.start()]))
        key = m.group(1)
        if key not in kw:
            raise KeyError(f"slot {key!r} not provided")
        used.add(key)
        out.extend(F(kw[key]))
        pos = m.end()
    out.extend(F(fmt[pos:]))
    unused = set(kw) - used
    if unused:
        raise KeyError(f"unused slot values: {sorted(unused)}")
    return out


def J(sep: Part, items: Iterable[Part]) -> list[Seg]:
    """Join parts with a separator."""
    out: list[Seg] = []
    first = True
    for it in items:
        if not first:
            out.extend(F(sep))
        out.extend(F(it))
        first = False
    return out


def lines(*rows: Part, end: str = "\n") -> list[Seg]:
    """One row per line, each terminated by a newline."""
    out: list[Seg] = []
    for r in rows:
        out.extend(F(r))
        out.append(Seg(end))
    return F(out)


def plain_text(frag: list[Seg]) -> str:
    return "".join(s.text for s in frag)


def map_text(frag: list[Seg], fn: Callable[[str], str]) -> list[Seg]:
    """Apply a per-character-compatible transform (e.g. JSON escaping) to
    every segment; tags are preserved and the transformed value is what the
    document will contain."""
    return [Seg(fn(s.text), s.label, s.cls) for s in frag if s.text]


def json_escape(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)[1:-1]


def esc_json(frag: list[Seg]) -> list[Seg]:
    return map_text(frag, json_escape)


def rstrip_nl(frag: list[Seg]) -> list[Seg]:
    """Remove trailing newlines/spaces from the trailing plain segments."""
    out = list(frag)
    while out and not out[-1].tagged:
        t = out[-1].text.rstrip()
        if t:
            out[-1] = Seg(t)
            break
        out.pop()
    return out


def lstrip_nl(frag: list[Seg]) -> list[Seg]:
    out = list(frag)
    while out and not out[0].tagged:
        t = out[0].text.lstrip("\n")
        if t:
            out[0] = Seg(t)
            break
        out.pop(0)
    return out


def ensure_nl(frag: list[Seg]) -> list[Seg]:
    frag = rstrip_nl(frag)
    return frag + [Seg("\n")]


PrefixFn = Callable[[int], list]


def prefix_lines(frag: list[Seg], first: Union[str, PrefixFn], rest: Union[str, PrefixFn, None] = None,
                 blank: str | None = None) -> list[Seg]:
    """Prefix every line of `frag`.

    `first` is used for the first line and `rest` (default: `first`) for the
    following ones; either can be a function of the 1-based line number that
    returns a fragment (which may contain tagged segments). A prefix that has
    to go inside a multi-line tagged value is merged into that value's text,
    untagged, so tagged regions never overlap.
    """
    if rest is None:
        rest = first

    def pfx(n: int, is_blank: bool) -> list[Seg]:
        f = first if n == 1 else rest
        res = F(f(n)) if callable(f) else F(f)
        if is_blank:
            if blank is not None:
                return F(blank)
            if not callable(f):
                return F(plain_text(res).rstrip())
        return res

    out: list[Seg] = []
    at_bol = True
    line_no = 0
    for seg in frag:
        text = seg.text
        if not seg.tagged:
            buf: list[str] = []
            i = 0
            while i < len(text):
                if at_bol:
                    line_no += 1
                    is_blank = text[i] == "\n"
                    if buf:
                        out.append(Seg("".join(buf)))
                        buf = []
                    out.extend(pfx(line_no, is_blank))
                    at_bol = False
                ch = text[i]
                buf.append(ch)
                if ch == "\n":
                    at_bol = True
                i += 1
            if buf:
                out.append(Seg("".join(buf)))
            continue
        # tagged segment
        if at_bol:
            line_no += 1
            out.extend(pfx(line_no, False))
            at_bol = False
        if "\n" not in text:
            out.append(seg)
            continue
        pieces = text.split("\n")
        rebuilt = [pieces[0]]
        for p in pieces[1:]:
            line_no += 1
            rebuilt.append("\n" + plain_text(pfx(line_no, p == "")) + p)
        out.append(Seg("".join(rebuilt), seg.label, seg.cls))
    return merge_plain(out)


def merge_plain(frag: list[Seg]) -> list[Seg]:
    out: list[Seg] = []
    for s in frag:
        if not s.text:
            continue
        if out and not s.tagged and not out[-1].tagged:
            out[-1] = Seg(out[-1].text + s.text)
        else:
            out.append(s)
    return out


@dataclass(slots=True)
class Assembled:
    text: str
    spans: list  # list[dict]
    regions: list  # list[dict]
    span_values: list  # parallel to spans: the inserted text
    region_values: list


def assemble(frag: list[Seg]) -> Assembled:
    """Concatenate segments, recording each tagged segment's offsets as it is
    placed into the text."""
    parts: list[str] = []
    spans: list[dict] = []
    regions: list[dict] = []
    sv: list[str] = []
    rv: list[str] = []
    pos = 0
    for s in frag:
        n = len(s.text)
        if s.label is not None:
            spans.append({"start": pos, "end": pos + n, "label": s.label})
            sv.append(s.text)
        elif s.cls is not None:
            regions.append({"start": pos, "end": pos + n, "class": s.cls})
            rv.append(s.text)
        parts.append(s.text)
        pos += n
    return Assembled("".join(parts), spans, regions, sv, rv)


class InvariantError(AssertionError):
    pass


def check_document(a: Assembled) -> None:
    """Spec invariants for one document; raises InvariantError."""
    text = a.text
    for sp, val in zip(a.spans, a.span_values):
        if sp["label"] not in GOLD_SET:
            raise InvariantError(f"invalid label {sp['label']!r}")
        if not (0 <= sp["start"] < sp["end"] <= len(text)):
            raise InvariantError(f"span out of range {sp}")
        if text[sp["start"]:sp["end"]] != val:
            raise InvariantError(f"span text mismatch at {sp}")
    for rg, val in zip(a.regions, a.region_values):
        if rg["class"] not in DISTRACTOR_SET:
            raise InvariantError(f"invalid distractor class {rg['class']!r}")
        if not (0 <= rg["start"] < rg["end"] <= len(text)):
            raise InvariantError(f"region out of range {rg}")
        if text[rg["start"]:rg["end"]] != val:
            raise InvariantError(f"region text mismatch at {rg}")
    marks = sorted([(s["start"], s["end"], "g") for s in a.spans]
                   + [(r["start"], r["end"], "d") for r in a.regions])
    max_end_any = -1
    max_end_gold = -1
    for start, end, kind in marks:
        if kind == "g" and start < max_end_any:
            raise InvariantError(f"gold span {(start, end)} overlaps an earlier span or region")
        if kind == "d" and start < max_end_gold:
            raise InvariantError(f"region {(start, end)} overlaps a gold span")
        max_end_any = max(max_end_any, end)
        if kind == "g":
            max_end_gold = max(max_end_gold, end)


# ---------------------------------------------------------------- tabular helpers


def _cells(rows: list) -> tuple[list, list, list]:
    frs = [[F(c) for c in row] for row in rows]
    texts = [[plain_text(c) for c in row] for row in frs]
    ncol = max(len(r) for r in rows)
    widths = [max((len(t[i]) for t in texts if i < len(t)), default=0) for i in range(ncol)]
    return frs, texts, widths


def table(rows: list, gap: int = 2, right: tuple = ()) -> list[Seg]:
    """Whitespace-aligned columns (docker ps, kubectl get, ls -l ...).
    Cells may be strings, Segs or fragments; `right` lists right-aligned columns."""
    frs, texts, widths = _cells(rows)
    out: list[Seg] = []
    for row, trow in zip(frs, texts):
        for i, (c, t) in enumerate(zip(row, trow)):
            pad = widths[i] - len(t)
            if i in right:
                out.append(Seg(" " * pad))
                out.extend(c)
                if i < len(row) - 1:
                    out.append(Seg(" " * gap))
            else:
                out.extend(c)
                if i < len(row) - 1:
                    out.append(Seg(" " * (pad + gap)))
        out.append(Seg("\n"))
    return merge_plain(out)


def grid(header: list, rows: list, style: str = "psql", footer: str | None = None) -> list[Seg]:
    """Bordered result tables: 'psql', 'mysql' or 'md'."""
    frs, texts, widths = _cells([header] + rows)
    out: list[Seg] = []

    def emit_row(cells, tws, lead, sep, tail):
        out.append(Seg(lead))
        for i, (c, t) in enumerate(zip(cells, tws)):
            if i:
                out.append(Seg(sep))
            out.extend(c)
            out.append(Seg(" " * (widths[i] - len(t))))
        out.append(Seg(tail + "\n"))

    if style == "psql":
        emit_row(frs[0], texts[0], " ", " | ", "")
        out.append(Seg("-" + "-+-".join("-" * w for w in widths) + "-\n"))
        for c, t in zip(frs[1:], texts[1:]):
            emit_row(c, t, " ", " | ", "")
        out.append(Seg(footer if footer is not None else f"({len(rows)} row{'s' if len(rows) != 1 else ''})\n"))
    elif style == "mysql":
        rule = "+" + "+".join("-" * (w + 2) for w in widths) + "+\n"
        out.append(Seg(rule))
        emit_row(frs[0], texts[0], "| ", " | ", " |")
        out.append(Seg(rule))
        for c, t in zip(frs[1:], texts[1:]):
            emit_row(c, t, "| ", " | ", " |")
        out.append(Seg(rule))
        out.append(Seg(footer if footer is not None else f"{len(rows)} row{'s' if len(rows) != 1 else ''} in set (0.00 sec)\n"))
    elif style == "md":
        emit_row(frs[0], texts[0], "| ", " | ", " |")
        out.append(Seg("|" + "|".join("-" * (w + 2) for w in widths) + "|\n"))
        for c, t in zip(frs[1:], texts[1:]):
            emit_row(c, t, "| ", " | ", " |")
    else:
        raise ValueError(style)
    # trailing pad spaces before the line end are harmless; keep tagged segments intact
    return merge_plain(out)


def numbered(frag: list[Seg], start: int = 1, width: int = 4, sep: str = "→") -> list[Seg]:
    """`cat -n`-like line numbers (rendering artefacts, untagged)."""
    return prefix_lines(frag, lambda n: F(f"{n + start - 1:>{width}}{sep}"))
