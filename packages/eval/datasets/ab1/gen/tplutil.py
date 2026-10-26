# SPDX-License-Identifier: Apache-2.0
"""Helpers shared by the templates: JSON serialisation of annotated fragments, file-read wrappers,
and encoded-copy hooks."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

import keepvals as K
from doc import KP, MM, P, V, Doc, Hook, b64, json_escape, urlenc, with_gutter


def frag(*parts) -> Doc:
    d = Doc()
    d.add(*parts)
    return d


def jdump(obj, indent: int | None = 2, level: int = 0) -> Doc:
    """Serialise dict/list/str/int/bool/None/V/Doc to JSON; V and Doc leaves are JSON strings."""
    d = Doc()
    nl = "\n" if indent is not None else ""
    pad = " " * (indent * (level + 1)) if indent is not None else ""
    end_pad = " " * (indent * level) if indent is not None else ""
    sep = ", " if indent is None else ","
    if isinstance(obj, dict):
        if not obj:
            return d.add("{}")
        d.add("{" + nl)
        for i, (k, v) in enumerate(obj.items()):
            d.add(pad + '"' + k + '": ')
            d.extend(jdump(v, indent, level + 1))
            d.add((sep if i < len(obj) - 1 else "") + nl)
        d.add(end_pad + "}")
        return d
    if isinstance(obj, list):
        if not obj:
            return d.add("[]")
        d.add("[" + nl)
        for i, v in enumerate(obj):
            d.add(pad)
            d.extend(jdump(v, indent, level + 1))
            d.add((sep if i < len(obj) - 1 else "") + nl)
        d.add(end_pad + "]")
        return d
    if isinstance(obj, bool):
        return d.add("true" if obj else "false")
    if obj is None:
        return d.add("null")
    if isinstance(obj, (int, float)):
        return d.add(str(obj))
    if isinstance(obj, str):
        obj = P(obj)
    if isinstance(obj, V):
        obj = frag(obj)
    if isinstance(obj, Doc):
        d.add('"')
        d.extend(json_escape(obj))
        d.add('"')
        return d
    raise TypeError(type(obj))


def file_read(ctx, body: Doc, path: V | Doc | str) -> Doc:
    """Wrap file content the way agent tools return it: raw, cat -n gutter, or OpenHands view header."""
    r = ctx.rng.random()
    multiline_item = any("\n" in body.text[it.start:it.end] for it in body.items)
    if r < 0.4 or multiline_item:
        return body
    g = with_gutter(body)
    if r < 0.75:
        return g
    d = Doc()
    d.add("Here's the result of running `cat -n` on ", path, ":\n")
    d.extend(g)
    return d


def home_path(ctx, p, rest: str, mac: bool | None = None) -> Doc:
    """/Users/<user>/<rest> or /home/<user>/<rest>; the user is MUST_MASK, the rest MUST_KEEP path."""
    mac = ctx.rng.random() < 0.5 if mac is None else mac
    d = Doc()
    d.add("/Users/" if mac else "/home/")
    d.add(ctx.user(p))
    d.add(KP("/" + rest, "path"))
    return d


# ------------------------------------------------------------------ encoded-copy hooks

def add_hook(doc: Doc, orig: V, render: Callable[[random.Random, V], Doc], label: str) -> None:
    """Register an encoded-copy hook inserted at the current end of doc (anchor) if selected."""
    if orig.cls != "MUST_MASK":
        return
    name = f"hook{len(doc.hooks)}_{len(doc.text)}"
    doc.anchor(name)
    doc.hooks.append(Hook(name, lambda rng, o=orig: render(rng, o), label))


def enc_v(orig: V, how: str) -> V:
    text = b64(orig.text) if how == "base64" else urlenc(orig.text)
    return V(text, "MUST_MASK", orig.category, f"{how}:{orig.kind}", enc_of=orig)


def can_urlenc(orig: V) -> bool:
    return urlenc(orig.text) != orig.text


def render_query_line(prefix: str, base_url: str, param: str, suffix: str = "\n"):
    def r(rng: random.Random, orig: V) -> Doc:
        how = "urlencoded" if can_urlenc(orig) else "base64"
        d = Doc()
        d.add(prefix, KP(base_url, "public_url"), f"?{param}=", enc_v(orig, how), suffix)
        return d
    return r


def render_b64_line(fmt_before: str, fmt_after: str = "\n"):
    def r(rng: random.Random, orig: V) -> Doc:
        d = Doc()
        d.add(fmt_before, enc_v(orig, "base64"), fmt_after)
        return d
    return r


def apply_hook(doc: Doc, rng: random.Random, endline_inserter=None) -> str | None:
    if not doc.hooks:
        return None
    h = rng.choice(doc.hooks)
    frag_doc = h.render(rng)
    if h.endline:
        endline_inserter(doc, frag_doc)
        return h.label
    pos = doc.anchors[h.anchor]
    if h.escaped:
        doc.insert(pos, frag_doc)
        return h.label
    at_end = pos == len(doc.text)
    if at_end and doc.text and not doc.text.endswith("\n"):
        # appended after the last line: open a new line instead of closing one
        if frag_doc.text.endswith("\n"):
            frag_doc = trim_trailing_newline(frag_doc)
        frag_doc = frag("\n", frag_doc)
    elif pos > 0 and doc.text[pos - 1] != "\n":
        frag_doc = frag("\n", trim_trailing_newline(frag_doc)) if frag_doc.text.endswith("\n") else frag_doc
    doc.insert(pos, frag_doc)
    return h.label


def trim_trailing_newline(d: Doc) -> Doc:
    if not d.text.endswith("\n"):
        return d
    for it in d.items:
        if it.end == len(d.text):
            return d
    d.text = d.text[:-1]
    return d


API_HOSTS = ["https://api.stripe.com/v1/customers/search", "https://api.sendgrid.com/v3/marketing/contacts/search",
             "https://api.mailgun.net/v3/lists/members", "https://api.hubapi.com/crm/v3/objects/contacts/search",
             "https://graph.microsoft.com/v1.0/users", "https://api.intercom.io/contacts/search"]


def api_base(rng: random.Random) -> str:
    return rng.choice(API_HOSTS)
