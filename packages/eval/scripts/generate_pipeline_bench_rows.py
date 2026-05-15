#!/usr/bin/env python3
"""Generate `nullpii-bench` rows that exercise the Node-runtime pipeline
layers over the bare ONNX model.

Each category targets one or more of:
  - Recognizer pack (regex with anchors + validators)
  - Chunking (inputs > GLiNER's 384-subword window)
  - Adversarial normalize (URL %XX, HTML entity, Unicode homoglyph,
    base64-wrapped, multi-layer encoding stack)
  - `base64-detector` (`data:` / `Authorization: Basic …`)
  - Validator-pass score 0.99998 (IBAN mod-97 / Luhn / codice fiscale)

Deterministic: seeded RNG, fixed corpus templates. Re-running the
script gives byte-identical output.

Usage:
  python packages/eval/scripts/generate_pipeline_bench_rows.py \
    --out packages/eval/datasets/nullpii-bench.jsonl --append
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import string
from pathlib import Path
from typing import Callable
from urllib.parse import quote

# ─── Deterministic RNG ────────────────────────────────────────────────
RNG = random.Random(20260515)


# ─── Helpers ──────────────────────────────────────────────────────────
def rand_alnum(n: int) -> str:
    return "".join(RNG.choices(string.ascii_letters + string.digits, k=n))


def rand_upper(n: int) -> str:
    return "".join(RNG.choices(string.ascii_uppercase + string.digits, k=n))


def aws_access_key() -> str:
    return "AKIA" + "".join(RNG.choices(string.ascii_uppercase + string.digits, k=16))


def github_pat() -> str:
    return "ghp_" + "".join(RNG.choices(string.ascii_letters + string.digits, k=36))


def stripe_live() -> str:
    return "sk_live_" + "".join(RNG.choices(string.ascii_letters + string.digits, k=24))


def slack_token() -> str:
    prefix = RNG.choice(["xoxb", "xoxa", "xoxp", "xoxs"])
    return f"{prefix}-{RNG.randint(10**9, 10**10-1)}-{rand_alnum(14)}"


def gcp_api_key() -> str:
    return "AIza" + "".join(RNG.choices(string.ascii_letters + string.digits + "_-", k=35))


def luhn_card() -> str:
    """Generate a 16-digit Luhn-valid card-shaped number."""
    base = [RNG.randint(0, 9) for _ in range(15)]
    s = 0
    for i, d in enumerate(reversed(base)):
        if i % 2 == 0:
            x = d * 2
            if x > 9:
                x -= 9
            s += x
        else:
            s += d
    check = (10 - (s % 10)) % 10
    return "".join(map(str, base)) + str(check)


def make_iban_it() -> str:
    """Italian IBAN with valid mod-97 check."""
    # IT + 2-digit checksum + 1 letter + 5 digits ABI + 5 digits CAB + 12 digits conto
    body = "A" + "".join(RNG.choices(string.digits, k=22))
    target = body + "IT00"

    def num(s: str) -> int:
        return int("".join(str(ord(c) - 55) if c.isalpha() else c for c in s))

    remainder = num(target) % 97
    check = 98 - remainder
    return f"IT{check:02d}{body}"


def encode_email_pct(email: str) -> str:
    return email.replace("@", "%40").replace(".", "%2E")


def encode_email_entity(email: str) -> str:
    return "".join(f"&#{ord(c)};" for c in email)


def encode_email_base64(email: str) -> str:
    return base64.b64encode(email.encode()).decode()


def encode_email_double_url(email: str) -> str:
    once = quote(email, safe="")
    return quote(once, safe="")


# ─── Categories ───────────────────────────────────────────────────────
SAMPLES: list[dict] = []


def add_sample(text: str, spans: list[tuple[int, int, str]], category: str) -> None:
    span_dicts = [
        {"label": lbl, "start": st, "end": en} for st, en, lbl in spans
    ]
    SAMPLES.append({"text": text, "spans": span_dicts, "category": category})


# A. Pure-secret in JSON / log context — recognizer pack wins
SECRETS_TEMPLATES = [
    'ERROR 2024-03-15T08:42:11Z [auth] failed to verify, token={k} reason=expired',
    '{{"service":"upload","credentials":{{"aws_access_key":"{k}"}}}}',
    'POST /api/v1/keys/rotate -> old={k} status=204',
    'deploy.env\\nAWS_ACCESS_KEY_ID={k}\\nREGION=eu-west-1',
    'curl -H "X-Token: {k}" https://api.internal/v1/resources',
]


def gen_pure_secret() -> None:
    secret_gens: list[tuple[Callable[[], str], str]] = [
        (aws_access_key, "secret"),
        (github_pat, "secret"),
        (stripe_live, "secret"),
        (slack_token, "secret"),
        (gcp_api_key, "secret"),
    ]
    n = 25
    for _ in range(n):
        gen, label = RNG.choice(secret_gens)
        tmpl = RNG.choice(SECRETS_TEMPLATES)
        key = gen()
        text = tmpl.format(k=key)
        st = text.find(key)
        en = st + len(key)
        add_sample(text, [(st, en, label)], "pure-secret")


# B. Long-doc chunking — PII placed past the 384-subword window
LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt "
    "ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco "
    "laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in "
    "voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat "
    "cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. "
)


def gen_long_doc() -> None:
    n = 20
    for _ in range(n):
        padding_blocks = RNG.randint(6, 10)
        prefix = LOREM * padding_blocks
        kind = RNG.choice(["email", "phone", "card", "iban"])
        if kind == "email":
            user = rand_alnum(RNG.randint(4, 10)).lower()
            domain = RNG.choice(["acme.io", "example.com", "internal.corp", "company.dev"])
            pii = f"{user}@{domain}"
            label = "private_email"
        elif kind == "phone":
            pii = f"+39 333 {RNG.randint(1000000, 9999999)}"
            label = "private_phone"
        elif kind == "card":
            pii = luhn_card()
            label = "account_number"
        else:
            pii = make_iban_it()
            label = "account_number"
        text = f"{prefix}Please find the requested record below.\nIdentifier: {pii}\nEnd of section."
        st = text.find(pii)
        en = st + len(pii)
        add_sample(text, [(st, en, label)], "long-doc-chunking")


# C. Multi-layer adversarial encoding — preprocessor must decode + detect
def gen_multilayer_encoding() -> None:
    emails_pool = [
        "alice.smith@company.io",
        "bob.jones@example.com",
        "charlie@internal.corp",
        "ops-team@startup.dev",
        "j.smith@university.edu",
    ]
    n = 20
    for _ in range(n):
        email = RNG.choice(emails_pool)
        enc_kind = RNG.choice(["url-pct", "html-entity", "double-url"])
        if enc_kind == "url-pct":
            wrapped = encode_email_pct(email)
        elif enc_kind == "html-entity":
            wrapped = encode_email_entity(email)
        else:
            wrapped = encode_email_double_url(email)
        prose_tmpl = RNG.choice(
            [
                "Please forward to {w} as discussed.",
                "Customer contact: {w} (use this for support).",
                "Forward all replies to {w}, not the shared inbox.",
                "Direct line: {w}. Confirm receipt.",
            ]
        )
        text = prose_tmpl.format(w=wrapped)
        st = text.find(wrapped)
        en = st + len(wrapped)
        add_sample(text, [(st, en, "private_email")], "multi-layer-encoding")


# D. Base64-wrapped credential — base64 detector
def gen_base64_wrapped() -> None:
    n = 20
    creds: list[tuple[str, str]] = [
        ("user@acme.io", "private_email"),
        ("alice.smith@example.com", "private_email"),
        ("bob.jones@company.io", "private_email"),
        ("admin@internal.corp", "private_email"),
    ]
    for _ in range(n):
        pii, label = RNG.choice(creds)
        encoded = base64.b64encode(pii.encode()).decode()
        tmpl = RNG.choice(
            [
                "GET /api HTTP/1.1\nAuthorization: Basic {b}\nUser-Agent: app/1.0",
                'token payload (base64): {b}',
                '{{"creds":"{b}"}}',
                'Cookie: session={b}; Path=/',
            ]
        )
        text = tmpl.format(b=encoded)
        st = text.find(encoded)
        en = st + len(encoded)
        add_sample(text, [(st, en, label)], "base64-wrapped")


# E. Validator-pass disambiguation — Luhn / mod-97 / CF
def gen_validator_disambig() -> None:
    n = 15
    for _ in range(n):
        kind = RNG.choice(["iban-spaced", "card-luhn", "cf-italy"])
        if kind == "iban-spaced":
            iban = make_iban_it()
            # Insert a space every 4 chars to stress recognizer normalisation
            spaced = " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))
            tmpl = RNG.choice(
                [
                    "Bank account: {x}. Wire by Friday.",
                    "Settlement IBAN {x} confirmed.",
                    "Please remit to {x} attn. accounts payable.",
                ]
            )
            text = tmpl.format(x=spaced)
            st = text.find(spaced)
            en = st + len(spaced)
            add_sample(text, [(st, en, "account_number")], "validator-disambig")
        elif kind == "card-luhn":
            card = luhn_card()
            grouped = " ".join(card[i : i + 4] for i in range(0, 16, 4))
            tmpl = RNG.choice(
                [
                    "Charged card {x} for the renewal.",
                    "Payment method on file: {x}.",
                    "Card-on-file {x}, expires 12/27.",
                ]
            )
            text = tmpl.format(x=grouped)
            st = text.find(grouped)
            en = st + len(grouped)
            add_sample(text, [(st, en, "account_number")], "validator-disambig")
        else:
            cf = "RSSMRA80D15H501O"  # valid checksum example
            tmpl = RNG.choice(
                [
                    "Codice fiscale del contraente: {x}. Pratica chiusa.",
                    "CF lookup: {x} (Roma, 1980).",
                ]
            )
            text = tmpl.format(x=cf)
            st = text.find(cf)
            en = st + len(cf)
            add_sample(text, [(st, en, "account_number")], "validator-disambig")


# ─── CLI ──────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()

    gen_pure_secret()
    gen_long_doc()
    gen_multilayer_encoding()
    gen_base64_wrapped()
    gen_validator_disambig()

    print(f"generated {len(SAMPLES)} samples across 5 categories")
    from collections import Counter

    by_cat = Counter(s["category"] for s in SAMPLES)
    for cat, n in by_cat.most_common():
        print(f"  {cat}: {n}")

    mode = "a" if args.append else "w"
    with args.out.open(mode) as f:
        for s in SAMPLES:
            # Strip the `category` field — the bench loader ignores it
            # but consumers shouldn't see it as a label key.
            row = {"text": s["text"], "spans": s["spans"]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{'appended to' if args.append else 'wrote'} {args.out}")


if __name__ == "__main__":
    main()
