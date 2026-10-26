# SPDX-License-Identifier: Apache-2.0
"""Annotated document model: text plus non-overlapping items, with offset-safe edits."""
from __future__ import annotations

import base64
import itertools
import json
import re
import urllib.parse
from dataclasses import dataclass, field

MUST_MASK = "MUST_MASK"
MUST_KEEP = "MUST_KEEP"
AMBIGUOUS = "AMBIGUOUS"
CLASSES = (MUST_MASK, MUST_KEEP, AMBIGUOUS)

SLOT_RE = re.compile(r"«(\w+)»")
_UIDS = itertools.count(1)  # process-wide unique item ids (never exported)


@dataclass(eq=False)
class V:
    """A value to place in text, optionally annotated."""
    text: str
    cls: str | None = None
    category: str | None = None
    kind: str | None = None
    enc_of: "V | None" = None
    uid: int | None = None  # set when placed in a doc
    meta: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return self.text


def MM(text: str, category: str, kind: str, **meta) -> V:
    return V(text, MUST_MASK, category, kind, meta=meta)


def KP(text: str, kind: str) -> V:
    return V(text, MUST_KEEP, kind, kind)


def AM(text: str, kind: str) -> V:
    return V(text, AMBIGUOUS, kind, kind)


def P(text: str) -> V:
    """Plain (unannotated) text."""
    return V(text)


@dataclass
class Hook:
    """Encoded-copy hook: inserting render(rng) at the anchor adds an encoded copy of a value."""
    anchor: str
    render: object  # Callable[[random.Random], Doc]
    label: str
    escaped: bool = False
    endline: bool = False  # append render() as a new last line (gutter-aware), ignoring the anchor


@dataclass
class Item:
    start: int
    end: int
    cls: str
    category: str
    kind: str
    uid: int
    origin: str  # injected | template | carrier_pass | keep_pass | encoded
    enc_of_uid: int | None = None


class OverlapError(ValueError):
    pass


class Doc:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.items: list[Item] = []
        self.anchors: dict[str, int] = {}
        self.hooks: list = []          # encoded-copy hooks
        self.expected: dict[int, str] = {}   # uid -> exact text the item must cover
        self.vobj: dict[int, V] = {}

    # ---------------------------------------------------------------- building
    @staticmethod
    def _uid() -> int:
        return next(_UIDS)

    def add(self, *parts) -> "Doc":
        for p in parts:
            if p is None:
                continue
            if isinstance(p, V):
                self.add_value(p)
            elif isinstance(p, Doc):
                self.extend(p)
            elif isinstance(p, (list, tuple)):
                self.add(*p)
            else:
                self.text += str(p)
        return self

    def add_value(self, v: V) -> int | None:
        start = len(self.text)
        self.text += v.text
        if v.cls is None or not v.text:
            return None
        enc = None
        if v.enc_of is not None:
            enc = v.enc_of.uid
            if enc is None:
                raise ValueError("encoded copy placed before its original")
        uid = self._uid()
        if v.cls == MUST_MASK:
            origin = "encoded" if enc else "injected"
        else:
            origin = "template"
        self.items.append(Item(start, len(self.text), v.cls, v.category, v.kind, uid, origin, enc))
        v.uid = uid
        self.expected[uid] = v.text
        self.vobj[uid] = v
        return uid

    def fmt(self, template: str, **slots) -> "Doc":
        pos = 0
        for m in SLOT_RE.finditer(template):
            self.text += template[pos:m.start()]
            name = m.group(1)
            if name not in slots:
                raise KeyError(f"missing slot {name!r} in template")
            self.add(slots[name])
            pos = m.end()
        self.text += template[pos:]
        return self

    def extend(self, other: "Doc") -> "Doc":
        self.insert(len(self.text), other)
        return self

    def insert(self, pos: int, other: "Doc") -> None:
        for it in self.items:
            if it.start < pos < it.end:
                raise OverlapError(f"insert at {pos} splits item {it}")
        n = len(other.text)
        for it in self.items:
            if it.start >= pos:
                it.start += n
                it.end += n
        for k, a in self.anchors.items():
            if a >= pos:
                self.anchors[k] = a + n
        for it in other.items:
            self.items.append(Item(it.start + pos, it.end + pos, it.cls, it.category, it.kind,
                                   it.uid, it.origin, it.enc_of_uid))
        self.expected.update(other.expected)
        self.vobj.update(other.vobj)
        for k, a in other.anchors.items():
            self.anchors[k] = a + pos
        self.hooks.extend(other.hooks)
        self.text = self.text[:pos] + other.text + self.text[pos:]

    def replace(self, start: int, end: int, other: "Doc") -> None:
        for it in self.items:
            if it.start < end and start < it.end:
                raise OverlapError(f"replace [{start},{end}) touches item {it}")
        n = end - start
        for it in self.items:
            if it.start >= end:
                it.start -= n
                it.end -= n
        for k, a in self.anchors.items():
            if a >= end:
                self.anchors[k] = a - n
            elif a > start:
                self.anchors[k] = start
        self.text = self.text[:start] + self.text[end:]
        self.insert(start, other)

    def overlaps(self, start: int, end: int) -> bool:
        return any(it.start < end and start < it.end for it in self.items)

    def annotate(self, start: int, end: int, cls: str, category: str, kind: str, origin: str) -> bool:
        if start >= end or self.overlaps(start, end):
            return False
        uid = self._uid()
        self.items.append(Item(start, end, cls, category, kind, uid, origin))
        self.expected[uid] = self.text[start:end]
        return True

    def anchor(self, name: str) -> None:
        self.anchors[name] = len(self.text)

    # ---------------------------------------------------------------- output
    def check(self) -> None:
        its = sorted(self.items, key=lambda x: (x.start, x.end))
        for a, b in zip(its, its[1:]):
            if b.start < a.end:
                raise OverlapError(f"overlap {a} / {b}: {self.text[a.start:a.end]!r} {self.text[b.start:b.end]!r}")
        uids = {it.uid for it in its}
        for it in its:
            if not (0 <= it.start < it.end <= len(self.text)):
                raise ValueError(f"bad offsets {it}")
            if self.text[it.start:it.end] != self.expected[it.uid]:
                raise ValueError(f"value mismatch {it}: {self.text[it.start:it.end]!r} != {self.expected[it.uid]!r}")
            if it.enc_of_uid is not None and it.enc_of_uid not in uids:
                raise ValueError(f"dangling encoded_of {it}")

    def finalize(self) -> list[dict]:
        self.check()
        its = sorted(self.items, key=lambda x: (x.start, x.end))
        index = {it.uid: i for i, it in enumerate(its)}
        return [{
            "start": it.start, "end": it.end, "class": it.cls, "category": it.category, "kind": it.kind,
            "encoded_of": index[it.enc_of_uid] if it.enc_of_uid is not None else None,
        } for it in its]

    def mm_items(self) -> list[Item]:
        return [it for it in self.items if it.cls == MUST_MASK]


# ------------------------------------------------------------------ transforms

def transform(doc: Doc, encode_char) -> Doc:
    """Apply a per-character escape to a doc, mapping item offsets and expected values."""
    out = []
    pos_map = [0] * (len(doc.text) + 1)
    n = 0
    for i, ch in enumerate(doc.text):
        pos_map[i] = n
        e = encode_char(ch)
        out.append(e)
        n += len(e)
    pos_map[len(doc.text)] = n
    res = Doc("".join(out))
    for it in doc.items:
        res.items.append(Item(pos_map[it.start], pos_map[it.end], it.cls, it.category, it.kind, it.uid,
                              it.origin, it.enc_of_uid))
    for uid, txt in doc.expected.items():
        res.expected[uid] = "".join(encode_char(c) for c in txt)
    res.vobj = dict(doc.vobj)
    for k, a in doc.anchors.items():
        res.anchors[k] = pos_map[a]
    res.hooks = [Hook(h.anchor, (lambda rng, h=h: transform(h.render(rng), encode_char)), h.label, True) for h in doc.hooks]
    return res


def _json_char(ch: str) -> str:
    return json.dumps(ch, ensure_ascii=False)[1:-1]


def json_escape(doc: Doc) -> Doc:
    """JSON-string-escape a fragment (without the surrounding quotes)."""
    return transform(doc, _json_char)


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def urlenc(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def with_gutter(doc: Doc, first_line: int = 1, width: int = 6, sep: str = "\t") -> Doc:
    """Prefix each line with a cat -n style line number. Items must not span lines."""
    for it in doc.items:
        if "\n" in doc.text[it.start:it.end]:
            raise ValueError("multi-line item in gutter doc")
    lines = doc.text.split("\n")
    spans = []
    out = []
    pos = 0
    outlen = 0
    for i, line in enumerate(lines):
        prefix = f"{first_line + i:>{width}}{sep}"
        spans.append((pos, pos + len(line), outlen + len(prefix)))
        piece = prefix + line + ("\n" if i < len(lines) - 1 else "")
        out.append(piece)
        outlen += len(piece)
        pos += len(line) + 1

    def mp(p: int) -> int:
        for ls, le, ns in spans:
            if ls <= p <= le:
                return ns + (p - ls)
        raise ValueError(p)

    res = Doc("".join(out))
    for it in doc.items:
        res.items.append(Item(mp(it.start), mp(it.end), it.cls, it.category, it.kind, it.uid, it.origin,
                              it.enc_of_uid))
    res.expected = dict(doc.expected)
    res.vobj = dict(doc.vobj)
    for k, a in doc.anchors.items():
        res.anchors[k] = mp(a)
    res.hooks = list(doc.hooks)
    return res
