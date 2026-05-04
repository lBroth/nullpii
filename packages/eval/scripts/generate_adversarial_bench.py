#!/usr/bin/env python3
"""Generate adversarial edge-case bench dataset.

Six categories of adversarial PII patterns the headline matrix doesn't
cover. Each category has ~80 samples with planted PII spans annotated
to nullpii's 8-category schema.

Categories:
  1. typo_pii — single-char typos in PII (`gmial.com`, transposed digits)
  2. unicode_obf — homoglyph (Cyrillic а/о for Latin), zero-width chars
  3. whitespace_obf — `g i a n l u c a @ g m a i l . c o m`
  4. encoding_obf — base64/URL-encoded/HTML-entity wrapped PII
  5. decoys — non-PII patterns that look like PII (`localhost:5432`,
     `0.0.0.0`, `x@y.z`, MAC `00:00:00:00:00:00`)
  6. code_pii — credentials in code comments / docstrings / config

Output schema matches `nullpii-bench.jsonl`:
  `{id, locale, subset, text, spans}`

Used to detect regressions on adversarial robustness — orthogonal to
the public-dataset PII benches.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SEED = 1337


# Source PII pool — clean values to corrupt
NAMES = [
    "Gianluca Rossi", "Marie Dubois", "Hans Schmidt", "John Smith",
    "Yuki Tanaka", "Carlos García", "Olga Petrov", "Ahmed Hassan",
    "Sophie Martin", "Mario Bianchi", "Elena Romano", "Klaus Weber",
]
EMAILS = [
    "alice@acme.com", "bob.jones@company.io", "user.123@gmail.com",
    "admin@internal.corp", "info@startup.dev", "j.smith@university.edu",
]
PHONES = [
    "+1 555 234 5678", "+39 333 1234567", "+44 7700 900000",
    "+33 6 12 34 56 78", "+49 30 12345678",
]
SECRETS = [
    "AKIA1234567890ABCDEF", "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
    "sk-ant-api03-aBcDeFg012345678901234567890123456789AA",
    "sk_live_4eC39HqLyjWDarjtT1zdp7dc",
]
ADDRESSES = [
    "via Roma 45 Milano",
    "221B Baker Street London",
    "1600 Pennsylvania Avenue Washington",
    "Champs-Élysées 75 Paris",
]
ACCOUNT_NUMBERS = [
    "IT60X0542811101000000123456",  # IBAN
    "123-45-6789",  # SSN
    "4532015112830366",  # credit card
]


def _typo(s: str) -> str:
    if len(s) < 4:
        return s
    rng = random.Random(SEED)
    i = rng.randrange(1, len(s) - 1)
    # swap with neighbour
    return s[:i] + s[i + 1] + s[i] + s[i + 2:]


def _homoglyph(s: str) -> str:
    repl = {"a": "а", "o": "о", "e": "е", "p": "р", "c": "с"}  # latin → cyrillic
    return "".join(repl.get(ch.lower(), ch) for ch in s)


def _zero_width(s: str) -> str:
    rng = random.Random(SEED + 1)
    out = []
    for ch in s:
        out.append(ch)
        if rng.random() < 0.15:
            out.append("​")  # ZWSP
    return "".join(out)


def _whitespace_split(s: str) -> str:
    return " ".join(list(s))


def _build(text: str, spans: list[tuple[str, int, int]]) -> dict:
    return {
        "text": text,
        "spans": [{"label": l, "start": s, "end": e} for l, s, e in spans],
    }


def _typo_samples() -> list[dict]:
    rng = random.Random(SEED)
    out = []
    for _ in range(80):
        choice = rng.choice([("private_email", EMAILS), ("private_phone", PHONES),
                             ("account_number", ACCOUNT_NUMBERS), ("secret", SECRETS)])
        label, pool = choice
        original = rng.choice(pool)
        corrupted = _typo(original)
        prefix = rng.choice([
            "Please contact ", "Send to ", "Update record: ", "Reach out at ",
        ])
        suffix = " for details."
        text = f"{prefix}{corrupted}{suffix}"
        start = len(prefix)
        end = start + len(corrupted)
        out.append(_build(text, [(label, start, end)]))
    return out


def _unicode_samples() -> list[dict]:
    rng = random.Random(SEED + 2)
    out = []
    for _ in range(80):
        choice = rng.choice([
            ("private_email", EMAILS),
            ("private_person", NAMES),
            ("private_address", ADDRESSES),
        ])
        label, pool = choice
        original = rng.choice(pool)
        # Alternate homoglyph + zero-width
        if rng.random() < 0.5:
            corrupted = _homoglyph(original)
        else:
            corrupted = _zero_width(original)
        prefix = rng.choice([
            "Customer info: ", "Profile: ", "On file: ", "From record: ",
        ])
        text = f"{prefix}{corrupted} (active)."
        start = len(prefix)
        end = start + len(corrupted)
        out.append(_build(text, [(label, start, end)]))
    return out


def _whitespace_samples() -> list[dict]:
    rng = random.Random(SEED + 3)
    out = []
    for _ in range(80):
        choice = rng.choice([
            ("private_email", EMAILS),
            ("private_phone", PHONES),
            ("account_number", ACCOUNT_NUMBERS),
        ])
        label, pool = choice
        original = rng.choice(pool)
        corrupted = _whitespace_split(original)
        prefix = "Detected pattern: "
        suffix = " — verify match."
        text = f"{prefix}{corrupted}{suffix}"
        start = len(prefix)
        end = start + len(corrupted)
        out.append(_build(text, [(label, start, end)]))
    return out


def _encoding_samples() -> list[dict]:
    import base64
    import urllib.parse
    rng = random.Random(SEED + 4)
    out = []
    for _ in range(80):
        choice = rng.choice([
            ("private_email", EMAILS),
            ("secret", SECRETS),
        ])
        label, pool = choice
        original = rng.choice(pool)
        scheme = rng.choice(["base64", "url", "html_entity"])
        if scheme == "base64":
            corrupted = base64.b64encode(original.encode()).decode()
        elif scheme == "url":
            corrupted = urllib.parse.quote(original)
        else:
            corrupted = "".join(f"&#{ord(c)};" for c in original[:20]) + original[20:]
        prefix = f"({scheme}-encoded) "
        text = f"{prefix}{corrupted}"
        start = len(prefix)
        end = start + len(corrupted)
        out.append(_build(text, [(label, start, end)]))
    return out


def _decoy_samples() -> list[dict]:
    """Non-PII patterns that look like PII — should NOT be flagged."""
    rng = random.Random(SEED + 5)
    decoys = [
        "localhost:5432", "0.0.0.0", "127.0.0.1", "127.0.0.1:8080",
        "x@y.z", "test@test.test", "noreply@noreply",
        "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff",
        "00000000-0000-0000-0000-000000000000",  # zero UUID
        "GET /api/v1", "POST /users/{id}", "+1 (555) 555-5555",  # 555 fake
        "192.168.0.1", "10.0.0.0/24",
        "DELETE FROM users WHERE id = 0",
    ]
    out = []
    for _ in range(80):
        decoy = rng.choice(decoys)
        wrappers = [
            f"In docs: example uses {decoy} as placeholder.",
            f"// {decoy} is the dev default",
            f"DEFAULT_VALUE = {decoy}",
            f"Connection string template: {decoy}",
        ]
        text = rng.choice(wrappers)
        # No PII spans — empty
        out.append(_build(text, []))
    return out


def _code_pii_samples() -> list[dict]:
    rng = random.Random(SEED + 6)
    templates = [
        ("# api_key={secret}\nimport requests", "secret", "{secret}"),
        ("api_key = '{secret}'", "secret", "{secret}"),
        ("export ANTHROPIC_API_KEY={secret}", "secret", "{secret}"),
        ("config = {{'token': '{secret}', 'env': 'prod'}}", "secret", "{secret}"),
        ("# Author: {name} <{email}>", "private_person+private_email", "{name}|{email}"),
        ("'''Owner: {name}, contact {email}.'''", "private_person+private_email", "{name}|{email}"),
        ("# DB: postgres password is REDACTED — see secret {secret}", "secret", "{secret}"),
    ]
    out = []
    for _ in range(80):
        tpl, kind, _ = rng.choice(templates)
        secret = rng.choice(SECRETS)
        name = rng.choice(NAMES)
        email = rng.choice(EMAILS)
        text = tpl.format(secret=secret, name=name, email=email)
        spans: list[tuple[str, int, int]] = []
        for token, label in [(secret, "secret"), (name, "private_person"), (email, "private_email")]:
            idx = text.find(token)
            if idx >= 0:
                spans.append((label, idx, idx + len(token)))
        out.append(_build(text, spans))
    return out


SUBSETS: dict[str, callable] = {
    "typo_pii": _typo_samples,
    "unicode_obf": _unicode_samples,
    "whitespace_obf": _whitespace_samples,
    "encoding_obf": _encoding_samples,
    "decoys": _decoy_samples,
    "code_pii": _code_pii_samples,
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for subset, gen in SUBSETS.items():
        for i, sample in enumerate(gen()):
            rows.append({
                "id": f"{subset}_{i:04d}",
                "locale": "mixed",
                "subset": subset,
                "text": sample["text"],
                "spans": sample["spans"],
            })

    with args.out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} samples to {args.out}")
    by_subset = {}
    span_count = 0
    for r in rows:
        by_subset[r["subset"]] = by_subset.get(r["subset"], 0) + 1
        span_count += len(r["spans"])
    for s, n in by_subset.items():
        print(f"  {s}: {n} samples")
    print(f"total spans: {span_count}")


if __name__ == "__main__":
    main()
