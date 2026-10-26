# SPDX-License-Identifier: Apache-2.0
"""Generic encoded-copy hooks (used when a template or injection has no context-specific one).

The encoded copy is appended as a new last line in a form that occurs in that kind of traffic:
a URL query string (URL-encoded) or a base64 value (kubectl / echo | base64 / debug header).
"""
from __future__ import annotations

import random

import keepvals as K
from doc import KP, MUST_MASK, Doc, Hook, V
from tplutil import can_urlenc, enc_v, frag

SEARCH_URLS = ["https://api.hubapi.com/crm/v3/objects/contacts/search", "https://api.intercom.io/contacts/search",
               "https://api.stripe.com/v1/customers/search", "https://api.sendgrid.com/v3/marketing/contacts/search"]
PII_CATS = {"email", "person", "phone", "address", "iban", "card", "account", "national_id", "passport", "driver_license", "url"}

LINK_WORD = {"en": "Link", "it": "Link", "de": "Link", "fr": "Lien", "es": "Enlace"}
B64_WORD = {"en": "in base64", "it": "in base64", "de": "base64-kodiert", "fr": "en base64", "es": "en base64"}


COMMENT = {"py": "# ", "sh": "# ", "yaml": "# ", "toml": "# ", "ini": "# ", "env": "# ", "js": "// ", "sql": "-- ", "doc": ""}


def _how(orig: V) -> str | None:
    if orig.category == "secret":
        return "base64"
    return "urlencoded" if can_urlenc(orig) else None


def _render(kind: str, lang: str, orig: V, rng: random.Random, style: str = "sh") -> Doc:
    """One line (no trailing newline) carrying the encoded copy of orig."""
    how = _how(orig)
    e = enc_v(orig, how)
    url = KP(rng.choice(SEARCH_URLS), "public_url")
    if kind == "shell":
        if how == "base64":
            return frag("$ echo -n \"$", orig.meta.get("var", "TOKEN"), "\" | base64   # ", e)
        return frag("$ curl -s \"", url, "?query=", e, "\" | jq '.total'")
    if kind == "log":
        ts = KP(K.log_ts(rng), "date")
        if how == "base64":
            return frag(ts, " DEBUG auth: outgoing header X-Auth-Token-B64=", e)
        return frag(ts, " INFO  http: GET ", url, "?query=", e, " -> ", KP("200", "http_status"))
    if kind in ("file", "tool_json"):
        c = COMMENT.get(style, "# ")
        if how == "base64":
            return frag(c, "base64 (for the k8s Secret): ", e)
        return frag(c, "lookup: ", url, "?query=", e)
    if kind in ("prompt", "ticket"):
        if how == "base64":
            return frag("(", B64_WORD[lang], ": ", e, ")")
        return frag(LINK_WORD[lang], ": ", url, "?query=", e)
    raise ValueError(kind)


def generic_hooks(doc: Doc, kind: str, lang: str, style: str = "sh") -> list[Hook]:
    """One hook per eligible MUST_MASK value, appending its encoded copy as a new last line."""
    if kind == "tool_json" or style in ("json", "csv"):
        return []
    hooks = []
    seen = set()
    present = {it.uid for it in doc.items}
    for uid, v in sorted(doc.vobj.items()):
        if v.cls != MUST_MASK or v.enc_of is not None or v.text in seen or uid not in present:
            continue
        if "\n" in v.text or len(v.text) < 4 or _how(v) is None:
            continue
        seen.add(v.text)
        hooks.append(Hook(f"generic_{uid}", (lambda rng, v=v: _render(kind, lang, v, rng, style)), f"generic_{kind}_{_how(v)}",
                          endline=True))
    return hooks
