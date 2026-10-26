# SPDX-License-Identifier: Apache-2.0
"""Fictional MUST_MASK value generators (people, contacts, ids, network, personal URLs, passwords).

All values are generated here from the open lists in lists/ and a caller-supplied seeded RNG.
"""
from __future__ import annotations

import ipaddress
import random
import string
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from common import LISTS, read_lines, read_tsv

COUNTRY_OF_LANG = {"en": ["us", "gb"], "it": ["it"], "de": ["de"], "fr": ["fr"], "es": ["es"]}
LANG_OF_COUNTRY = {"us": "en", "gb": "en", "it": "it", "de": "de", "fr": "fr", "es": "es"}
HEX = "0123456789abcdef"
ALNUM = string.ascii_letters + string.digits
KNOWN_TEST_CARDS = {"4111111111111111", "4242424242424242", "5555555555554444", "378282246310005",
                    "4012888888881881", "5105105105105100", "6011111111111117", "4000056655665556"}


# ------------------------------------------------------------------ lists

@lru_cache(maxsize=None)
def names(lang: str, which: str) -> tuple[str, ...]:
    return tuple(read_lines(LISTS / "names" / lang / f"{which}.txt"))


@lru_cache(maxsize=None)
def streets(country: str) -> tuple[str, ...]:
    return tuple(read_lines(LISTS / "streets" / f"{country}.txt"))


@lru_cache(maxsize=None)
def postal(country: str) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(r) for r in read_tsv(LISTS / "postal" / f"{country}.tsv"))


@lru_cache(maxsize=None)
def handmade_tsv(name: str) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(r) for r in read_tsv(LISTS / "handmade" / name))


@lru_cache(maxsize=None)
def handmade_lines(name: str) -> tuple[str, ...]:
    return tuple(read_lines(LISTS / "handmade" / name))


def lang_table(name: str) -> dict[str, list[str]]:
    return {r[0]: r[1].split("|") for r in handmade_tsv(name)}


def blocklist() -> frozenset[str]:
    p = LISTS.parent / "gen" / "blocklist.txt"
    return frozenset(read_lines(p)) if p.exists() else frozenset()


BLOCK = blocklist()


def fold(s: str, lang: str = "") -> str:
    """ASCII-fold a name for usernames / e-mail local parts."""
    if lang == "de":
        s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        s = s.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s if c.isascii() and (c.isalnum() or c in " -'")).replace("'", "")


# ------------------------------------------------------------------ people

@dataclass
class Person:
    given: str
    family: str
    gender: str  # m | f
    lang: str
    country: str

    @property
    def full(self) -> str:
        return f"{self.given} {self.family}"


def person(rng: random.Random, lang: str, country: str | None = None) -> Person:
    country = country or rng.choice(COUNTRY_OF_LANG[lang])
    gender = rng.choice("mf")
    for _ in range(50):
        g = rng.choice(names(lang, "given_male" if gender == "m" else "given_female"))
        f = rng.choice(names(lang, "surnames"))
        if g != f and f"{g} {f}" not in BLOCK:
            return Person(g, f, gender, lang, country)
    raise RuntimeError("could not draw a non-blocked person")


def username(rng: random.Random, p: Person) -> str:
    g, f = fold(p.given, p.lang).lower().replace(" ", ""), fold(p.family, p.lang).lower().replace(" ", "")
    g, f = g.replace("-", ""), f.replace("-", "")
    forms = [g, g[0] + f, f + g[0], f"{g}.{f}", f"{g}{f}", f"{g}_{f}", g + str(rng.randint(1, 99)), f[:6] + g[:2], g + f[0]]
    for _ in range(20):
        u = rng.choice(forms)
        if len(u) >= 4 and u not in BLOCK:
            return u
    return g + f


def handle(rng: random.Random, p: Person) -> str:
    u = username(rng, p).replace(".", "").replace("_", "-")
    return rng.choice([u, u + str(rng.randint(70, 2005)), u + "-dev", "the" + u, u.replace("-", "")])


def _weighted(rng: random.Random, rows) -> str:
    return rng.choices([r[1] for r in rows], [float(r[2]) for r in rows])[0]


def company_name(rng: random.Random, lang: str) -> str:
    fam = rng.choice(names(lang, "surnames"))
    word = rng.choice(lang_table("company_words.tsv")[lang])
    suf = rng.choice(lang_table("company_suffix.tsv")[lang])
    return f"{fam} {word} {suf}"


def company_domain(rng: random.Random, lang: str, country: str) -> str:
    fam = fold(rng.choice(names(lang, "surnames")), lang).lower().replace(" ", "")
    word = fold(rng.choice(lang_table("company_words.tsv")[lang]), lang).lower().replace(" ", "")
    tld = {"us": "com", "gb": "co.uk", "it": "it", "de": "de", "fr": "fr", "es": "es"}[country]
    return rng.choice([f"{fam}-{word}.{tld}", f"{fam}{word}.{tld}", f"{fam}.{tld}", f"{fam}-{word[:4]}.{tld}"])


def email(rng: random.Random, p: Person, work: bool | None = None) -> str:
    g = fold(p.given, p.lang).lower().replace(" ", "").replace("-", "")
    f = fold(p.family, p.lang).lower().replace(" ", "").replace("-", "")
    if work is None:
        work = rng.random() < 0.35
    for _ in range(30):
        if work:
            dom = company_domain(rng, p.lang, p.country)
            local = rng.choice([f"{g}.{f}", f"{g[0]}.{f}", f"{g}", f"{g[0]}{f}", f"{f}"])
        else:
            dom = _weighted(rng, [r for r in handmade_tsv("email_domains.tsv") if r[0] == p.country])
            n = str(rng.randint(1, 99)) if rng.random() < 0.5 else str(rng.randint(1960, 2006))
            local = rng.choice([f"{g}.{f}{n}", f"{g}{f}{n}", f"{g}.{f}", f"{g[0]}{f}{n}", f"{g}_{f}", f"{f}.{g}{n}",
                                f"{g}{n}", f"{g}.{f[0]}{n}"])
        e = f"{local}@{dom}"
        if e not in BLOCK:
            return e
    raise RuntimeError("email draw exhausted")


# ------------------------------------------------------------------ phones

def _d(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def phone(rng: random.Random, country: str) -> str:
    for _ in range(30):
        p = _phone(rng, country)
        if p not in BLOCK:
            return p
    raise RuntimeError("phone draw exhausted")


def _phone(rng: random.Random, country: str) -> str:
    r = rng.random()
    if country == "us":
        area = str(rng.randint(2, 9)) + _d(rng, 2)
        while area[1:] == "11":
            area = str(rng.randint(2, 9)) + _d(rng, 2)
        ex, ln = str(rng.randint(2, 9)) + _d(rng, 2), _d(rng, 4)
        return rng.choice([f"+1 ({area}) {ex}-{ln}", f"({area}) {ex}-{ln}", f"{area}-{ex}-{ln}", f"+1-{area}-{ex}-{ln}",
                           f"+1{area}{ex}{ln}", f"{area}.{ex}.{ln}"])
    if country == "gb":
        if r < 0.6:
            m = "7" + str(rng.choice([4, 5, 7, 8, 9])) + _d(rng, 2)
            rest = _d(rng, 6)
            return rng.choice([f"0{m} {rest}", f"+44 {m} {rest}", f"+44 (0){m} {rest}", f"0{m}{rest}"])
        area, rest = rng.choice([("20", 8), ("161", 7), ("121", 7), ("113", 7), ("131", 7), ("117", 7)])
        num = _d(rng, rest)
        sp = f"{num[:4]} {num[4:]}" if rest == 8 else f"{num[:3]} {num[3:]}"
        return rng.choice([f"0{area} {sp}", f"+44 {area} {sp}"])
    if country == "it":
        if r < 0.65:
            pre = str(rng.choice(list(range(320, 350)) + list(range(360, 369)) + list(range(380, 394))))
            rest = _d(rng, 7)
            return rng.choice([f"+39 {pre} {rest[:3]} {rest[3:]}", f"{pre} {rest}", f"{pre}-{rest[:3]}-{rest[3:]}",
                               f"+39{pre}{rest}", f"{pre} {rest[:3]} {rest[3:]}"])
        area = rng.choice(["02", "06", "011", "055", "051", "081", "010", "041", "045"])
        rest = _d(rng, 10 - len(area))
        return rng.choice([f"+39 {area} {rest}", f"{area} {rest}", f"{area}/{rest}", f"+39 {area} {rest[:4]} {rest[4:]}"])
    if country == "de":
        if r < 0.6:
            pre = rng.choice(["151", "152", "157", "160", "162", "170", "171", "172", "175", "176", "177", "178", "179"])
            rest = _d(rng, 8 if pre.startswith("15") else 7)
            return rng.choice([f"+49 {pre} {rest}", f"0{pre} {rest}", f"+49 (0){pre} {rest}", f"0{pre}/{rest}",
                               f"0{pre}-{rest}"])
        area = rng.choice(["30", "40", "89", "221", "69", "711", "211", "341"])
        rest = _d(rng, 10 - len(area))
        return rng.choice([f"+49 {area} {rest}", f"0{area} {rest}", f"0{area}/{rest}", f"+49 {area} {rest[:3]} {rest[3:]}"])
    if country == "fr":
        first = rng.choice(["6", "7"]) if r < 0.6 else rng.choice(["1", "2", "3", "4", "5", "9"])
        rest = _d(rng, 8)
        pairs = " ".join(rest[i:i + 2] for i in range(0, 8, 2))
        return rng.choice([f"0{first} {pairs}", f"+33 {first} {pairs}", f"+33 (0){first} {pairs}", f"0{first}{rest}",
                           f"0{first}.{pairs.replace(' ', '.')}", f"+33{first}{rest}"])
    if country == "es":
        if r < 0.6:
            num = rng.choice(["6", "7"]) + _d(rng, 8)
        else:
            num = "9" + rng.choice(["1", "3", "5", "6", "8"]) + _d(rng, 7)
        return rng.choice([f"+34 {num[:3]} {num[3:6]} {num[6:]}", f"{num[:3]} {num[3:5]} {num[5:7]} {num[7:]}",
                           f"{num}", f"+34{num}", f"{num[:3]} {num[3:6]} {num[6:]}", f"(+34) {num}"])
    raise ValueError(country)


# ------------------------------------------------------------------ addresses

@dataclass
class Address:
    line: str          # single-line form
    street: str
    number: str
    postcode: str
    city: str
    region: str
    country: str


def address(rng: random.Random, country: str) -> Address:
    for _ in range(30):
        a = _address(rng, country)
        if a.line not in BLOCK:
            return a
    raise RuntimeError("address draw exhausted")


def _address(rng: random.Random, country: str) -> Address:
    st = rng.choice(streets(country))
    pc, place, a1n, a1c, a2n, a2c = rng.choice(postal(country))
    num = str(rng.choices([rng.randint(1, 30), rng.randint(31, 250), rng.randint(251, 2999)], [5, 4, 2])[0])
    if country == "us":
        num = str(rng.randint(10, 9899))
        apt = rng.choice(["", "", "", f", Apt {rng.randint(1, 30)}{rng.choice('ABCD')}", f" #{rng.randint(100, 999)}"])
        line = f"{num} {st}{apt}, {place}, {a1c} {pc}"
    elif country == "gb":
        flat = rng.choice(["", "", "", f"Flat {rng.randint(1, 20)}, "])
        line = f"{flat}{num} {st}, {place} {pc}"
    elif country == "it":
        sep = rng.choice([" ", ", "])
        prov = a2c if a2c and len(a2c) == 2 else ""
        tail = rng.choice([f" ({prov})", f" {prov}", ""]) if prov else ""
        line = f"{st}{sep}{num}, {pc} {place}{tail}"
    elif country == "de":
        st2 = st.replace("straße", "str.") if rng.random() < 0.2 else st
        line = f"{st2} {num}, {pc} {place}"
    elif country == "fr":
        st2 = st[0].lower() + st[1:] if rng.random() < 0.5 else st
        bis = rng.choice(["", "", "", " bis", " ter"])
        line = f"{num}{bis} {st2}, {pc} {place}"
    elif country == "es":
        piso = rng.choice(["", "", f", {rng.randint(1, 9)}º {rng.choice('ABCD')}", f", {rng.randint(1, 9)}º{rng.choice(['Izq', 'Dcha', 'A', 'B'])}"])
        st2 = st.replace("Calle ", "C/ ") if rng.random() < 0.25 else st
        line = f"{st2}, {num}{piso}, {pc} {place}"
    else:
        raise ValueError(country)
    return Address(line, st, num, pc, place, a1n, country)


# ------------------------------------------------------------------ ids

def luhn_check_digit(body: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def luhn_ok(num: str) -> bool:
    digits = [int(c) for c in num if c.isdigit()]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def card(rng: random.Random) -> tuple[str, str]:
    brand = rng.choices(["visa", "mastercard", "amex", "discover"], [5, 4, 1.5, 0.5])[0]
    for _ in range(50):
        if brand == "visa":
            body = "4" + _d(rng, 14)
        elif brand == "mastercard":
            body = (str(rng.randint(51, 55)) + _d(rng, 13)) if rng.random() < 0.8 else (str(rng.randint(2221, 2720)) + _d(rng, 11))
        elif brand == "amex":
            body = rng.choice(["34", "37"]) + _d(rng, 12)
        else:
            body = "6011" + _d(rng, 11)
        num = body + luhn_check_digit(body)
        if num in KNOWN_TEST_CARDS or len(set(num)) < 5 or num in BLOCK:
            continue
        sep = rng.choice([" ", " ", "-", ""])
        if brand == "amex":
            fmt = f"{num[:4]}{sep}{num[4:10]}{sep}{num[10:]}"
        else:
            fmt = sep.join(num[i:i + 4] for i in range(0, 16, 4))
        return brand, fmt
    raise RuntimeError("card draw exhausted")


def iban_check(country: str, bban: str) -> str:
    s = bban + country + "00"
    n = "".join(str(int(c, 36)) for c in s)
    return f"{98 - int(n) % 97:02d}"


def iban_ok(iban: str) -> bool:
    s = iban.replace(" ", "")
    s = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in s)) % 97 == 1


_CIN_ODD = [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23]


def it_cin(abi_cab_conto: str) -> str:
    total = 0
    for k, ch in enumerate(abi_cab_conto):
        v = int(ch) if ch.isdigit() else ord(ch) - 65
        total += _CIN_ODD[v] if k % 2 == 0 else v
    return chr(65 + total % 26)


def fr_rib_key(bank: str, branch: str, account: str) -> str:
    return f"{97 - (89 * int(bank) + 15 * int(branch) + 3 * int(account)) % 97:02d}"


def es_dc(entity: str, office: str, account: str) -> str:
    w = [1, 2, 4, 8, 5, 10, 9, 7, 3, 6]

    def dc(ten: str) -> str:
        v = 11 - sum(int(a) * b for a, b in zip(ten, w)) % 11
        return "0" if v == 11 else "1" if v == 10 else str(v)
    return dc("00" + entity + office) + dc(account)


def iban(rng: random.Random, country: str) -> str:
    for _ in range(30):
        cc, bban = _bban(rng, country)
        full = cc + iban_check(cc, bban) + bban
        if full in BLOCK:
            continue
        if rng.random() < 0.55:
            return " ".join(full[i:i + 4] for i in range(0, len(full), 4))
        return full
    raise RuntimeError("iban draw exhausted")


def _bban(rng: random.Random, country: str) -> tuple[str, str]:
    if country == "it":
        abi, cab, conto = _d(rng, 5), _d(rng, 5), _d(rng, 12)
        return "IT", it_cin(abi + cab + conto) + abi + cab + conto
    if country == "de":
        return "DE", str(rng.randint(1, 8)) + _d(rng, 7) + _d(rng, 10)
    if country == "fr":
        bank, branch, acc = _d(rng, 5), _d(rng, 5), _d(rng, 11)
        return "FR", bank + branch + acc + fr_rib_key(bank, branch, acc)
    if country == "es":
        ent, off, acc = _d(rng, 4), _d(rng, 4), _d(rng, 10)
        return "ES", ent + off + es_dc(ent, off, acc) + acc
    if country in ("gb", "us"):
        return "GB", rng.choice(handmade_lines("gb_bank_codes.txt")) + _d(rng, 6) + _d(rng, 8)
    raise ValueError(country)


_CF_ODD = {**{str(i): v for i, v in enumerate([1, 0, 5, 7, 9, 13, 15, 17, 19, 21])},
           **{chr(65 + i): v for i, v in enumerate(_CIN_ODD)}}
_CF_EVEN = {**{str(i): i for i in range(10)}, **{chr(65 + i): i for i in range(26)}}
_CF_MONTH = "ABCDEHLMPRST"


def _cf_part(s: str, is_name: bool) -> str:
    s = fold(s).upper().replace(" ", "").replace("-", "")
    cons = [c for c in s if c.isalpha() and c not in "AEIOU"]
    vows = [c for c in s if c in "AEIOU"]
    if is_name and len(cons) >= 4:
        cons = [cons[0], cons[2], cons[3]]
    return "".join((cons + vows + ["X", "X", "X"])[:3])


def cf_check(cf15: str) -> str:
    total = sum(_CF_ODD[c] if i % 2 == 0 else _CF_EVEN[c] for i, c in enumerate(cf15))
    return chr(65 + total % 26)


def codice_fiscale(rng: random.Random, p: Person, year: int, month: int, day: int) -> str:
    code = rng.choice(handmade_tsv("it_belfiore.tsv"))[0]
    d = day + (40 if p.gender == "f" else 0)
    cf15 = _cf_part(p.family, False) + _cf_part(p.given, True) + f"{year % 100:02d}" + _CF_MONTH[month - 1] + f"{d:02d}" + code
    return cf15 + cf_check(cf15)


def cf_ok(cf: str) -> bool:
    return len(cf) == 16 and cf_check(cf[:15]) == cf[15]


DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def es_dni(rng: random.Random) -> str:
    n = rng.randint(10_000_000, 79_999_999)
    return f"{n:08d}{DNI_LETTERS[n % 23]}"


def es_nie(rng: random.Random) -> str:
    p = rng.choice("XYZ")
    n = rng.randint(0, 9_999_999)
    return f"{p}{n:07d}{DNI_LETTERS[int(str('XYZ'.index(p)) + f'{n:07d}') % 23]}"


def dni_ok(s: str) -> bool:
    s = s.replace("-", "")
    if s[0] in "XYZ":
        s = str("XYZ".index(s[0])) + s[1:]
    return DNI_LETTERS[int(s[:-1]) % 23] == s[-1]


def fr_nir(rng: random.Random, p: Person, year: int, month: int) -> str:
    sex = "1" if p.gender == "m" else "2"
    dept = rng.choice(["75", "69", "13", "31", "33", "59", "67", "44", "06", "92", "93", "94"])
    commune, order = f"{rng.randint(1, 350):03d}", f"{rng.randint(1, 999):03d}"
    body = f"{sex}{year % 100:02d}{month:02d}{dept}{commune}{order}"
    key = f"{97 - int(body) % 97:02d}"
    if rng.random() < 0.5:
        return f"{body[0]} {body[1:3]} {body[3:5]} {body[5:7]} {body[7:10]} {body[10:13]} {key}"
    return body + key


def nir_ok(s: str) -> bool:
    s = s.replace(" ", "")
    return 97 - int(s[:13]) % 97 == int(s[13:])


def de_steuer_id(rng: random.Random) -> str:
    while True:
        digits = list("0123456789")
        rng.shuffle(digits)
        if digits[0] == "0":
            continue
        first10 = digits[:9]
        dup = rng.choice(first10)
        first10 = first10 + [dup]
        rest = first10[1:]
        rng.shuffle(rest)
        first10 = [first10[0]] + rest
        s = "".join(first10)
        return s + de_steuer_check(s)


def de_steuer_check(s10: str) -> str:
    product = 10
    for ch in s10:
        total = (int(ch) + product) % 10
        if total == 0:
            total = 10
        product = (total * 2) % 11
    check = 11 - product
    return "0" if check == 10 else str(check)


def steuer_ok(s: str) -> bool:
    s = s.replace(" ", "")
    return len(s) == 11 and de_steuer_check(s[:10]) == s[10]


def us_ssn(rng: random.Random) -> str:
    area = rng.choice([a for a in range(1, 900) if a != 666])
    return f"{area:03d}-{rng.randint(1, 99):02d}-{rng.randint(1, 9999):04d}"


def gb_nino(rng: random.Random) -> str:
    first_ok = [c for c in string.ascii_uppercase if c not in "DFIQUV"]
    second_ok = [c for c in string.ascii_uppercase if c not in "DFIOQUV"]
    while True:
        pre = rng.choice(first_ok) + rng.choice(second_ok)
        if pre not in ("BG", "GB", "NK", "KN", "TN", "NT", "ZZ"):
            break
    d = _d(rng, 6)
    suf = rng.choice("ABCD")
    return rng.choice([f"{pre} {d[:2]} {d[2:4]} {d[4:]} {suf}", f"{pre}{d}{suf}"])


def national_id(rng: random.Random, p: Person, birth: tuple[int, int, int]) -> tuple[str, str]:
    y, m, d = birth
    c = p.country
    if c == "it":
        return "it_codice_fiscale", codice_fiscale(rng, p, y, m, d)
    if c == "es":
        return ("es_dni", es_dni(rng)) if rng.random() < 0.8 else ("es_nie", es_nie(rng))
    if c == "fr":
        return "fr_nir", fr_nir(rng, p, y, m)
    if c == "de":
        return "de_steuer_id", de_steuer_id(rng)
    if c == "us":
        return "us_ssn", us_ssn(rng)
    if c == "gb":
        return "gb_nino", gb_nino(rng)
    raise ValueError(c)


def passport(rng: random.Random, country: str) -> str:
    U = string.ascii_uppercase
    if country == "it":
        return rng.choice(["YA", "YB", "YC", "AA", "YD"]) + _d(rng, 7)
    if country == "de":
        alpha = "CFGHJKLMNPRTVWXYZ0123456789"
        return rng.choice("CFGHJK") + "".join(rng.choice(alpha) for _ in range(8))
    if country == "fr":
        return _d(rng, 2) + "".join(rng.choice(U) for _ in range(2)) + _d(rng, 5)
    if country == "es":
        return "".join(rng.choice(U) for _ in range(3)) + _d(rng, 6)
    if country == "us":
        return rng.choice(["", rng.choice(U)]) + _d(rng, 9 if rng.random() < 0.6 else 8)
    if country == "gb":
        return _d(rng, 9)
    raise ValueError(country)


def driver_license(rng: random.Random, p: Person, birth: tuple[int, int, int]) -> str:
    U = string.ascii_uppercase
    c = p.country
    if c == "it":
        return rng.choice(["U1", "MI", "RM", "TO", "NA", "BO"]) + _d(rng, 7) + rng.choice(U)
    if c == "de":
        return rng.choice(U) + _d(rng, 3) + "".join(rng.choice(U + string.digits) for _ in range(5)) + _d(rng, 2)
    if c == "fr":
        return _d(rng, 12) if rng.random() < 0.5 else _d(rng, 2) + "".join(rng.choice(U) for _ in range(2)) + _d(rng, 5)
    if c == "es":
        return es_dni(rng)
    if c == "us":
        return rng.choice([rng.choice(U) + _d(rng, 7), _d(rng, 9), _d(rng, 8), rng.choice(U) + _d(rng, 12)])
    if c == "gb":
        y, m, d = birth
        sur = fold(p.family).upper().replace(" ", "").replace("-", "")[:5].ljust(5, "9")
        mm = m + (50 if p.gender == "f" else 0)
        ini = (fold(p.given).upper()[:1] + "9")
        return f"{sur}{str(y)[2]}{mm:02d}{d:02d}{str(y)[3]}{ini}{rng.randint(0, 9)}{rng.choice(U)}{rng.choice(U)}"
    raise ValueError(c)


def account_number(rng: random.Random, lang: str) -> tuple[str, str]:
    kind = rng.choice(["customer_id", "customer_id", "user_account", "bank_account", "stripe_customer", "contract"])
    if kind == "customer_id":
        return kind, rng.choice([f"CUST-{_d(rng, 7)}", f"C{_d(rng, 8)}", f"{rng.choice(['CL', 'KD', 'CLI', 'CN'])}-{_d(rng, 6)}",
                                 f"{_d(rng, 4)}-{_d(rng, 6)}", _d(rng, 9)])
    if kind == "user_account":
        return kind, rng.choice([f"ACC-{_d(rng, 8)}", f"U{_d(rng, 9)}", f"usr_{''.join(rng.choice(ALNUM) for _ in range(12))}",
                                 _d(rng, 10)])
    if kind == "bank_account":
        return kind, rng.choice([_d(rng, 10), _d(rng, 12), f"{_d(rng, 4)} {_d(rng, 4)} {_d(rng, 4)}"])
    if kind == "stripe_customer":
        return kind, "cus_" + "".join(rng.choice(ALNUM) for _ in range(14))
    return kind, rng.choice([f"CTR-{rng.randint(2019, 2026)}-{_d(rng, 6)}", f"{rng.choice(['VT', 'AB', 'CT'])}{_d(rng, 9)}"])


def birth_date(rng: random.Random) -> tuple[int, int, int]:
    return rng.randint(1950, 2004), rng.randint(1, 12), rng.randint(1, 28)


# ------------------------------------------------------------------ network

DOC_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")]


def public_ipv4(rng: random.Random) -> str:
    while True:
        a = ipaddress.IPv4Address(rng.getrandbits(32))
        if a.is_global and not a.is_multicast and not any(a in n for n in DOC_NETS if n.version == 4):
            s = str(a)
            if s.split(".")[-1] not in ("0", "255") and s not in BLOCK:
                return s


def public_ipv6(rng: random.Random) -> str:
    while True:
        prefix = rng.choice([0x2001, 0x2003, 0x2a00, 0x2a01, 0x2a02, 0x2600, 0x2607, 0x2804, 0x2c0f, 0x2400])
        if prefix == 0x2001:
            second = rng.choice([0x0470, 0x067c, 0x41d0, 0x0bc8, 0x1620])
        else:
            second = rng.getrandbits(16)
        groups = [prefix, second] + [rng.getrandbits(16) for _ in range(6)]
        if rng.random() < 0.5:
            groups[4:7] = [0, 0, 0]
        a = ipaddress.IPv6Address(":".join(f"{g:x}" for g in groups))
        if a.is_global and not any(a in n for n in DOC_NETS if n.version == 6):
            return a.compressed


def public_ip(rng: random.Random, v6_share: float = 0.15) -> str:
    return public_ipv6(rng) if rng.random() < v6_share else public_ipv4(rng)


def private_ipv4(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.45:
        return f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(2, 254)}"
    if r < 0.75:
        return f"192.168.{rng.randint(0, 10)}.{rng.randint(2, 254)}"
    if r < 0.95:
        return f"172.{rng.randint(16, 31)}.{rng.randint(0, 255)}.{rng.randint(2, 254)}"
    return f"169.254.{rng.randint(1, 254)}.{rng.randint(1, 254)}"


def doc_ip(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.85:
        net = rng.choice(["192.0.2", "198.51.100", "203.0.113"])
        return f"{net}.{rng.randint(1, 254)}"
    return f"2001:db8:{rng.getrandbits(16):x}::{rng.randint(1, 255):x}"


def mac(rng: random.Random) -> str:
    b = [rng.getrandbits(8) for _ in range(6)]
    b[0] &= 0xFE  # unicast
    if rng.random() < 0.7:
        b[0] &= 0xFD  # universally administered
    style = rng.random()
    if style < 0.6:
        return ":".join(f"{x:02x}" for x in b)
    if style < 0.8:
        return "-".join(f"{x:02X}" for x in b)
    if style < 0.9:
        return ":".join(f"{x:02X}" for x in b)
    h = "".join(f"{x:02x}" for x in b)
    return f"{h[:4]}.{h[4:8]}.{h[8:]}"


# ------------------------------------------------------------------ personal URLs and secrets

def personal_url(rng: random.Random, p: Person) -> str:
    h = handle(rng, p)
    g = fold(p.given, p.lang).lower().replace(" ", "")
    f = fold(p.family, p.lang).lower().replace(" ", "")
    tld = {"us": "com", "gb": "co.uk", "it": "it", "de": "de", "fr": "fr", "es": "es"}[p.country]
    return rng.choice([
        f"https://github.com/{h}", f"https://www.linkedin.com/in/{g}-{f}-{rng.randint(10, 999)}",
        f"https://www.linkedin.com/in/{g}{f}", f"https://x.com/{h.replace('-', '_')}", f"https://twitter.com/{h.replace('-', '')}",
        f"https://{g}{f}.dev", f"https://{g}-{f}.{tld}", f"https://www.{f}{g[0]}.{tld}/about", f"https://medium.com/@{h}",
        f"https://gitlab.com/{h}", f"https://mastodon.social/@{h.replace('-', '')}", f"https://{h}.github.io",
        f"https://www.instagram.com/{g}.{f}", f"https://{g}{f}.me",
    ])


WORDS = ["sunflower", "tiger", "orange", "falcon", "marmalade", "coffee", "winter", "harbor", "violet", "rocket", "pepper",
         "maple", "cobalt", "garden", "silver", "nebula", "biscotti", "dolomiti", "sommer", "bretzel", "soleil", "playa"]


def password(rng: random.Random, p: Person | None = None) -> str:
    for _ in range(30):
        style = rng.random()
        if style < 0.35:
            w = rng.choice(WORDS)
            w = w.capitalize() if rng.random() < 0.6 else w
            pw = w + str(rng.randint(10, 2026)) + rng.choice("!@#$%&*?.")
        elif style < 0.5 and p is not None:
            g = fold(p.given).lower().replace(" ", "").replace("-", "")
            pw = g.capitalize() + rng.choice([".", "_", "#", "@"]) + str(rng.randint(1970, 2010)) + rng.choice("!?$")
        elif style < 0.8:
            alphabet = ALNUM + "!#$%&*+-=?@^_"
            pw = "".join(rng.choice(alphabet) for _ in range(rng.randint(12, 22)))
        else:
            pw = "".join(rng.choice(ALNUM) for _ in range(rng.randint(16, 32)))
        if pw not in BLOCK and not pw.lower().startswith(("password", "changeme", "admin")):
            return pw
    raise RuntimeError("password draw exhausted")


def session_cookie(rng: random.Random) -> tuple[str, str]:
    name = rng.choice(["sessionid", "session", "connect.sid", "JSESSIONID", "PHPSESSID", "_app_session", "laravel_session",
                       "__Secure-next-auth.session-token"])
    if name == "JSESSIONID":
        v = "".join(rng.choice("0123456789ABCDEF") for _ in range(32))
    elif name == "PHPSESSID":
        v = "".join(rng.choice("abcdefghijklmnopqrstuv0123456789") for _ in range(26))
    elif name == "connect.sid":
        v = "s%3A" + "".join(rng.choice(ALNUM + "-_") for _ in range(32)) + "." + "".join(rng.choice(ALNUM) for _ in range(43))
    else:
        v = "".join(rng.choice(ALNUM) for _ in range(rng.choice([32, 40, 64])))
    return name, v


def hex_token(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(HEX) for _ in range(n))
