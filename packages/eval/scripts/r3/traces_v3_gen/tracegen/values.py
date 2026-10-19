# SPDX-License-Identifier: Apache-2.0
"""Raw value generators (strings) for every gold category. All values are
random; check digits are computed with tracegen.checkdigits."""

from __future__ import annotations

import base64
import datetime as dt
import json
import random
import string
import unicodedata
from dataclasses import dataclass, field

from . import checkdigits as cd
from .lists import (CITIES, COUNTRY_OF, FAMILY, GIVEN_F, GIVEN_M, MAIL_PROVIDERS, PASSWORD_WORDS, STREETS,
                    VIN_YEARS, WMIS)

ALNUM = string.ascii_letters + string.digits
B64 = string.ascii_letters + string.digits + "+/"
B64URL = string.ascii_letters + string.digits + "-_"
HEX = "0123456789abcdef"
UPPER = string.ascii_uppercase


def rand_str(rng: random.Random, alphabet: str, n: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


_DE_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def fold(s: str, locale: str = "") -> str:
    """ASCII folding used for usernames and e-mail local parts."""
    if locale == "de_DE":
        s = s.translate(_DE_FOLD)
    s = s.replace("ł", "l").replace("Ł", "L").replace("ı", "i")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if c in string.ascii_letters or c in " -'")


def slug(s: str, locale: str = "") -> str:
    return "".join(c for c in fold(s, locale).lower() if c.isalnum())


# ---------------------------------------------------------------- persona


@dataclass
class Address:
    street: str        # street with number, as written locally
    postcode: str
    city: str
    country: str       # ISO code
    region: str = ""
    extra: str = ""    # apartment / floor

    def oneline(self) -> str:
        c = self.country
        st = self.street + (f", {self.extra}" if self.extra else "")
        if c == "US":
            return f"{st}, {self.city}, {self.region} {self.postcode}"
        if c == "GB":
            return f"{st}, {self.city} {self.postcode}"
        if c == "IT":
            return f"{st}, {self.postcode} {self.city} ({self.region})"
        if c == "PT":
            return f"{st}, {self.postcode} {self.city}"
        return f"{st}, {self.postcode} {self.city}"

    def city_line(self) -> str:
        c = self.country
        if c == "US":
            return f"{self.city}, {self.region} {self.postcode}"
        if c == "GB":
            return f"{self.city} {self.postcode}"
        if c == "IT":
            return f"{self.postcode} {self.city} ({self.region})"
        return f"{self.postcode} {self.city}"


@dataclass
class Persona:
    locale: str
    given: str
    family: str
    female: bool
    birth: dt.date
    address: Address
    city_rec: tuple
    phone_digits: str          # national significant number, digits only
    phone_kind: str            # mobile / landline
    username_seed: int
    placeholder: bool = False  # a conventional example identity (no gold)
    extra: dict = field(default_factory=dict)

    @property
    def country(self) -> str:
        return COUNTRY_OF[self.locale]

    @property
    def full(self) -> str:
        return f"{self.given} {self.family}"

    @property
    def g_ascii(self) -> str:
        return slug(self.given, self.locale)

    @property
    def f_ascii(self) -> str:
        return slug(self.family, self.locale)

    def username(self, style: int | None = None) -> str:
        g, f = self.g_ascii, self.f_ascii
        styles = [f"{g[0]}{f}", f"{g}.{f}", f"{g}{f[0]}", f"{f}{g[0]}", f"{g}_{f}", f"{g}-{f}",
                  f"{g}{self.birth.year % 100:02d}", f"{f}.{g}", f"{g[0]}.{f}", f"{g}{f}"]
        idx = self.username_seed % len(styles) if style is None else style % len(styles)
        return styles[idx]

    def email_local(self, style: int | None = None) -> str:
        g, f = self.g_ascii, self.f_ascii
        styles = [f"{g}.{f}", f"{g[0]}{f}", f"{g}", f"{f}.{g}", f"{g[0]}.{f}", f"{g}{f}", f"{g}_{f}"]
        idx = (self.username_seed // 7) % len(styles) if style is None else style % len(styles)
        return styles[idx]


def _pick_family(rng: random.Random, locale: str, female: bool) -> str:
    fam = rng.choice(FAMILY[locale])
    if locale == "pl_PL" and female:
        for m, f in (("ski", "ska"), ("cki", "cka"), ("dzki", "dzka")):
            if fam.endswith(m):
                return fam[: -len(m)] + f
    if locale == "es_ES" and rng.random() < 0.55:
        fam2 = rng.choice(FAMILY[locale])
        if fam2 != fam:
            fam = f"{fam} {fam2}"
    return fam


def make_address(rng: random.Random, locale: str) -> tuple[Address, tuple]:
    rec = rng.choice(CITIES[locale])
    street = rng.choice(STREETS[locale])
    num = rng.randint(1, 180)
    country = COUNTRY_OF[locale]
    extra = ""
    region = ""
    if locale == "en_US":
        city, region, (lo, hi) = rec[0], rec[1], rec[2]
        st = f"{rng.randint(100, 9899)} {street}"
        pc = f"{rng.randint(lo, hi):05d}"
        if rng.random() < 0.2:
            pc += f"-{rng.randint(1000, 9999)}"
        if rng.random() < 0.35:
            extra = rng.choice(["Apt ", "Unit ", "#"]) + f"{rng.randint(1, 40)}{rng.choice(['', 'A', 'B', 'C'])}"
    elif locale == "en_GB":
        city = rec[0]
        outward = rng.choice(rec[1])
        pc = f"{outward} {rng.randint(1, 9)}{rand_str(rng, 'ABDEFGHJLNPQRSTUWXYZ', 2)}"
        st = f"{num} {street}"
        if rng.random() < 0.25:
            st = f"Flat {rng.randint(1, 24)}, {st}"
    elif locale == "it_IT":
        city, region, (lo, hi) = rec[0], rec[1], rec[2]
        pc = f"{rng.randint(lo, hi):05d}"
        st = f"{street} {num}" if rng.random() < 0.6 else f"{street}, {num}"
        if rng.random() < 0.15:
            st += rng.choice(["/A", "/B", " bis"])
    elif locale == "de_DE":
        city, (lo, hi) = rec[0], rec[2]
        pc = f"{rng.randint(lo, hi):05d}"
        st = f"{street} {num}{rng.choice(['', '', '', 'a', 'b'])}"
    elif locale == "fr_FR":
        city, (lo, hi) = rec[0], rec[2]
        pc = f"{rng.randint(lo, hi):05d}"
        if city in ("Paris", "Lyon", "Marseille"):
            pc = f"{lo // 100:03d}{rng.randint(1, hi - lo + 1):02d}"
        st = f"{num}{rng.choice(['', '', '', ' bis', ' ter'])} {street}"
    elif locale == "es_ES":
        city, (lo, hi) = rec[0], rec[2]
        pc = f"{rng.randint(lo, hi):05d}"
        st = f"{street} {num}" if rng.random() < 0.5 else f"{street}, {num}"
        if rng.random() < 0.6:
            extra = f"{rng.randint(1, 9)}º {rng.choice('ABCD')}"
    elif locale == "nl_NL":
        city, (lo, hi) = rec[0], rec[2]
        letters = rand_str(rng, "ABCEGHJKLMNPRTVWXZ", 2)
        pc = f"{rng.randint(lo, hi)} {letters}"
        st = f"{street} {num}{rng.choice(['', '', '', '-A', 'bis', ' hs'])}"
    elif locale == "pt_PT":
        city, (lo, hi) = rec[0], rec[2]
        pc = f"{rng.randint(lo, hi):04d}-{rng.randint(1, 999):03d}"
        st = f"{street}, {num}"
        if rng.random() < 0.5:
            extra = f"{rng.randint(1, 8)}º {rng.choice(['Esq', 'Dto', 'Frente'])}"
    elif locale == "pl_PL":
        city, (lo, hi) = rec[0], rec[2]
        pc = f"{rng.randint(lo, hi):02d}-{rng.randint(1, 999):03d}"
        st = f"{street} {num}" + (f"/{rng.randint(1, 80)}" if rng.random() < 0.6 else "")
    else:
        raise ValueError(locale)
    return Address(st, pc, city, country, region, extra), rec


def _phone_digits(rng: random.Random, locale: str, rec: tuple) -> tuple[str, str]:
    mobile = rng.random() < 0.7
    if locale == "it_IT":
        if mobile:
            return rng.choice(["32", "33", "34", "36", "38", "39"]) + str(rng.randint(0, 9)) + rand_str(rng, "0123456789", 7), "mobile"
        return rec[5] + rand_str(rng, "0123456789", 10 - len(rec[5])), "landline"
    if locale == "de_DE":
        if mobile:
            return rng.choice(["151", "152", "157", "160", "162", "170", "171", "172", "173", "174", "175", "176", "177", "178", "179"]) + rand_str(rng, "0123456789", rng.choice([7, 8])), "mobile"
        return rec[5][1:] + rand_str(rng, "123456789", 1) + rand_str(rng, "0123456789", rng.randint(5, 7)), "landline"
    if locale == "fr_FR":
        if mobile:
            return rng.choice("67") + rand_str(rng, "0123456789", 8), "mobile"
        return rec[5][1:] + rand_str(rng, "0123456789", 8), "landline"
    if locale == "es_ES":
        if mobile:
            return rng.choice("67") + rand_str(rng, "0123456789", 8), "mobile"
        return rec[5] + rand_str(rng, "0123456789", 9 - len(rec[5])), "landline"
    if locale == "nl_NL":
        if mobile:
            return "6" + rand_str(rng, "123456789", 1) + rand_str(rng, "0123456789", 7), "mobile"
        area = rec[5][1:]
        return area + rand_str(rng, "123456789", 1) + rand_str(rng, "0123456789", 9 - len(area) - 1), "landline"
    if locale == "pt_PT":
        if mobile:
            return rng.choice(["91", "92", "93", "96"]) + rand_str(rng, "0123456789", 7), "mobile"
        return rec[5] + rand_str(rng, "0123456789", 9 - len(rec[5])), "landline"
    if locale == "pl_PL":
        if mobile:
            return rng.choice("5678") + rand_str(rng, "0123456789", 8), "mobile"
        return rec[5] + rand_str(rng, "0123456789", 7), "landline"
    if locale == "en_US":
        npa = rng.choice(rec[5])
        nxx = f"{rng.randint(2, 9)}{rng.randint(0, 9)}{rng.randint(0, 9)}"
        if nxx == "555":
            nxx = "556"
        return npa + nxx + rand_str(rng, "0123456789", 4), "mobile" if mobile else "landline"
    if locale == "en_GB":
        if mobile:
            first = rng.choice(["71", "73", "74", "75", "77", "78", "79"])
            rest = rand_str(rng, "0123456789", 8)
            if first == "77" and rest.startswith("00900"):
                rest = "1" + rest[1:]
            return "7" + first[1] + rest, "mobile"
        area = rec[4][1:]
        body = rand_str(rng, "2345678", 1) + rand_str(rng, "0123456789", 10 - len(area) - 1)
        return area + body, "landline"
    raise ValueError(locale)


def make_persona(rng: random.Random, locale: str, *, min_year: int = 1952, max_year: int = 2004) -> Persona:
    female = rng.random() < 0.5
    given = rng.choice(GIVEN_F[locale] if female else GIVEN_M[locale])
    family = _pick_family(rng, locale, female)
    birth = dt.date(rng.randint(min_year, max_year), rng.randint(1, 12), rng.randint(1, 28))
    addr, rec = make_address(rng, locale)
    digits, kind = _phone_digits(rng, locale, rec)
    return Persona(locale, given, family, female, birth, addr, rec, digits, kind, rng.randint(0, 10_000))


# ---------------------------------------------------------------- personal values


def phone_format(p: Persona, rng: random.Random, intl: bool | None = None) -> str:
    d = p.phone_digits
    if intl is None:
        intl = rng.random() < 0.5
    loc = p.locale
    style = rng.randint(0, 2)
    if loc == "it_IT":
        if d.startswith("3"):
            nat = [f"{d[:3]} {d[3:6]} {d[6:]}", f"{d[:3]} {d[3:]}", d][style]
        else:
            nat = [f"{d[:len(p.city_rec[5])]} {d[len(p.city_rec[5]):]}", d, f"{d[:len(p.city_rec[5])]}-{d[len(p.city_rec[5]):]}"][style]
        return ("+39 " + nat) if intl else nat
    if loc == "de_DE":
        cut = 3 if p.phone_kind == "mobile" else len(p.city_rec[5]) - 1
        if intl:
            return [f"+49 {d[:cut]} {d[cut:]}", f"+49{d}", f"+49 ({d[:cut]}) {d[cut:]}"][style]
        return [f"0{d[:cut]} {d[cut:]}", f"0{d[:cut]}/{d[cut:]}", f"0{d[:cut]}-{d[cut:]}"][style]
    if loc == "fr_FR":
        pairs = " ".join(d[i:i + 2] for i in range(1, 9, 2))
        if intl:
            return [f"+33 {d[0]} {pairs}", f"+33{d}", f"+33 (0){d[0]} {pairs}"][style]
        nat = "0" + d
        return [" ".join(nat[i:i + 2] for i in range(0, 10, 2)), ".".join(nat[i:i + 2] for i in range(0, 10, 2)), nat][style]
    if loc == "es_ES":
        if intl:
            return [f"+34 {d[:3]} {d[3:6]} {d[6:]}", f"+34{d}", f"+34 {d[:3]} {d[3:5]} {d[5:7]} {d[7:]}"][style]
        return [f"{d[:3]} {d[3:6]} {d[6:]}", d, f"{d[:3]} {d[3:5]} {d[5:7]} {d[7:]}"][style]
    if loc == "nl_NL":
        if d.startswith("6"):
            if intl:
                return [f"+31 6 {d[1:]}", f"+316{d[1:]}", f"+31 (0)6 {d[1:]}"][style]
            return [f"06-{d[1:]}", f"06 {d[1:5]} {d[5:]}", f"06{d[1:]}"][style]
        cut = len(p.city_rec[5]) - 1
        if intl:
            return f"+31 {d[:cut]} {d[cut:]}"
        return [f"0{d[:cut]}-{d[cut:]}", f"0{d[:cut]} {d[cut:]}", f"0{d}"][style]
    if loc == "pt_PT":
        nat = [f"{d[:3]} {d[3:6]} {d[6:]}", d, f"{d[:3]}{d[3:6]}{d[6:]}"][style]
        return ("+351 " + nat) if intl else nat
    if loc == "pl_PL":
        if p.phone_kind == "mobile":
            nat = [f"{d[:3]} {d[3:6]} {d[6:]}", f"{d[:3]}-{d[3:6]}-{d[6:]}", d][style]
        else:
            nat = [f"{d[:2]} {d[2:5]} {d[5:7]} {d[7:]}", f"({d[:2]}) {d[2:5]}-{d[5:7]}-{d[7:]}", d][style]
        return ("+48 " + nat) if intl else nat
    if loc == "en_US":
        if intl:
            return [f"+1 {d[:3]} {d[3:6]} {d[6:]}", f"+1-{d[:3]}-{d[3:6]}-{d[6:]}", f"+1{d}"][style]
        return [f"({d[:3]}) {d[3:6]}-{d[6:]}", f"{d[:3]}-{d[3:6]}-{d[6:]}", f"{d[:3]}.{d[3:6]}.{d[6:]}"][style]
    if loc == "en_GB":
        if d.startswith("7"):
            if intl:
                return [f"+44 {d[:4]} {d[4:]}", f"+44{d}", f"+44 (0){d[:4]} {d[4:]}"][style]
            return [f"0{d[:4]} {d[4:]}", f"0{d}", f"0{d[:4]} {d[4:7]} {d[7:]}"][style]
        area = p.city_rec[4][1:]
        rest = d[len(area):]
        if len(rest) == 8:
            rest = f"{rest[:4]} {rest[4:]}"
        elif len(rest) == 7:
            rest = f"{rest[:3]} {rest[3:]}"
        return f"+44 {area} {rest}" if intl else f"0{area} {rest}"
    raise ValueError(loc)


def email_work(p: Persona, domain: str, style: int | None = None) -> str:
    return f"{p.email_local(style)}@{domain}"


def email_personal(p: Persona, rng: random.Random) -> str:
    prov = rng.choice(MAIL_PROVIDERS[p.locale])
    g, f = p.g_ascii, p.f_ascii
    local = rng.choice([f"{g}.{f}", f"{g}{f}{p.birth.year % 100:02d}", f"{g[0]}{f}{rng.randint(1, 99)}",
                        f"{f}.{g}", f"{g}_{f}{p.birth.year}", f"{g}{rng.randint(70, 99)}"])
    return f"{local}@{prov}"


MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
           "ottobre", "novembre", "dicembre"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
           "November", "Dezember"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"],
    "nl": ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
           "november", "december"],
    "pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
           "novembro", "dezembro"],
    "pl": ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
           "października", "listopada", "grudnia"],
}


def date_format(d: dt.date, fmt: str, lang: str = "en") -> str:
    if fmt == "iso":
        return d.isoformat()
    if fmt == "eu":
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    if fmt == "us":
        return f"{d.month:02d}/{d.day:02d}/{d.year}"
    if fmt == "de":
        return f"{d.day:02d}.{d.month:02d}.{d.year}"
    if fmt == "dash":
        return f"{d.day:02d}-{d.month:02d}-{d.year}"
    if fmt == "long":
        months = MONTHS.get(lang, MONTHS["en"])
        if lang == "en":
            return f"{months[d.month - 1]} {d.day}, {d.year}"
        if lang == "de":
            return f"{d.day}. {months[d.month - 1]} {d.year}"
        if lang in ("es", "pt"):
            return f"{d.day} de {months[d.month - 1]} de {d.year}"
        return f"{d.day} {months[d.month - 1]} {d.year}"
    if fmt == "short_en":
        return f"{d.day} {MONTHS['en'][d.month - 1][:3]} {d.year}"
    raise ValueError(fmt)


def date_fmt_for(locale: str, rng: random.Random) -> str:
    choices = {"en_US": ["us", "iso", "long"], "en_GB": ["eu", "iso", "long", "short_en"],
               "it_IT": ["eu", "iso", "long"], "de_DE": ["de", "iso", "long"], "fr_FR": ["eu", "iso", "long"],
               "es_ES": ["eu", "iso", "long"], "nl_NL": ["dash", "iso", "long"], "pt_PT": ["eu", "iso", "long"],
               "pl_PL": ["de", "iso", "long"]}
    return rng.choice(choices[locale])


LANG_OF_LOCALE = {"en_US": "en", "en_GB": "en", "it_IT": "it", "de_DE": "de", "fr_FR": "fr", "es_ES": "es",
                  "nl_NL": "nl", "pt_PT": "pt", "pl_PL": "pl"}


def random_date(rng: random.Random, y0: int, y1: int) -> dt.date:
    return dt.date(rng.randint(y0, y1), rng.randint(1, 12), rng.randint(1, 28))


# ---------------------------------------------------------------- network


def ipv4_private(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.45:
        return f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(2, 254)}"
    if r < 0.75:
        return f"192.168.{rng.randint(0, 255)}.{rng.randint(2, 254)}"
    return f"172.{rng.randint(16, 31)}.{rng.randint(0, 255)}.{rng.randint(2, 254)}"


_EXCLUDED_V4 = [(0, 8), (10, 8), (100, 64), (127, 8), (169, 254), (172, 16), (192, 168), (198, 18), (198, 19)]


def ipv4_public(rng: random.Random) -> str:
    while True:
        a = rng.randint(1, 223)
        b = rng.randint(0, 255)
        if a in (0, 10, 127) or a >= 224:
            continue
        if (a, b) in ((169, 254), (192, 168), (198, 18), (198, 19)) or (a == 172 and 16 <= b <= 31):
            continue
        if a == 100 and 64 <= b <= 127:
            continue
        c = rng.randint(0, 255)
        if (a, b, c) in ((192, 0, 2), (198, 51, 100), (203, 0, 113), (192, 0, 0), (192, 88, 99)):
            continue
        if (a, b) in ((8, 8), (1, 1), (9, 9)):
            continue
        return f"{a}.{b}.{c}.{rng.randint(1, 254)}"


def ipv6_addr(rng: random.Random) -> str:
    kind = rng.random()
    if kind < 0.4:
        prefix = rng.choice(["2a01", "2a02", "2a00", "2001:4860", "2600", "2604", "2a0e", "2003", "2a05"])
    elif kind < 0.75:
        prefix = "fd" + rand_str(rng, HEX, 2)
    else:
        prefix = "2" + rand_str(rng, "0123456789a", 1) + rand_str(rng, HEX, 2)
    if prefix.startswith("2001:db8"):
        prefix = "2a02"
    groups = prefix.split(":")
    while len(groups) < 4:
        groups.append(f"{rng.randint(0, 0xffff):x}")
    tail = [f"{rng.randint(0, 0xffff):x}" for _ in range(4)]
    if rng.random() < 0.5:
        return ":".join(groups) + "::" + ":".join(tail[: rng.randint(1, 3)])
    return ":".join(groups + tail)


def mac_addr(rng: random.Random, style: int | None = None) -> str:
    first = rng.randint(0, 255) & 0b11111100 | (0b10 if rng.random() < 0.3 else 0)
    if first == 0:
        first = 0x3c
    b = [first] + [rng.randint(0, 255) for _ in range(5)]
    if b[1:] == [255] * 5:
        b[1] = 0x12
    style = rng.randint(0, 3) if style is None else style
    if style == 0:
        return ":".join(f"{x:02x}" for x in b)
    if style == 1:
        return ":".join(f"{x:02X}" for x in b)
    if style == 2:
        return "-".join(f"{x:02X}" for x in b)
    h = "".join(f"{x:02x}" for x in b)
    return f"{h[:4]}.{h[4:8]}.{h[8:]}"


def city_latlon(locale: str, rec: tuple) -> tuple[float, float]:
    if locale == "en_GB":
        return rec[2], rec[3]
    return rec[3], rec[4]


def geo_pair(rng: random.Random, lat: float, lon: float, spread: float = 0.06) -> tuple[str, str]:
    la = lat + rng.uniform(-spread, spread)
    lo = lon + rng.uniform(-spread, spread)
    nd = rng.choice([4, 5, 6, 6, 7])
    return f"{la:.{nd}f}", f"{lo:.{nd}f}"


# ---------------------------------------------------------------- accounts / national ids

_IBAN_BANKS = {"NL": ["ABNA", "RABO", "INGB", "SNSB", "TRIO", "ASNB", "KNAB"],
               "GB": ["NWBK", "BARC", "LOYD", "HBUK", "MIDL", "MONZ", "SRLG"]}


def iban(rng: random.Random, country: str) -> str:
    digits = "0123456789"
    if country == "IT":
        abi, cab, acct = rand_str(rng, digits, 5), rand_str(rng, digits, 5), rand_str(rng, digits, 12)
        bban = cd.it_cin(abi, cab, acct) + abi + cab + acct
    elif country == "DE":
        bban = rand_str(rng, digits, 8) + rand_str(rng, digits, 10)
    elif country == "FR":
        bank, branch, acct = rand_str(rng, digits, 5), rand_str(rng, digits, 5), rand_str(rng, digits, 11)
        bban = bank + branch + acct + cd.fr_rib_key(bank, branch, acct)
    elif country == "ES":
        bank, branch, acct = rand_str(rng, digits, 4), rand_str(rng, digits, 4), rand_str(rng, digits, 10)
        bban = bank + branch + cd.es_dc(bank, branch, acct) + acct
    elif country == "NL":
        while True:
            acct = rand_str(rng, digits, 10)
            if cd.nl_account_valid(acct):
                break
        bban = rng.choice(_IBAN_BANKS["NL"]) + acct
    elif country == "GB":
        bban = rng.choice(_IBAN_BANKS["GB"]) + rand_str(rng, digits, 6) + rand_str(rng, digits, 8)
    elif country == "BE":
        first = rand_str(rng, digits, 10)
        bban = first + cd.be_account_check(first)
    elif country == "PT":
        first = rand_str(rng, digits, 19)
        bban = first + cd.pt_nib_check(first)
    elif country == "PL":
        bban = rand_str(rng, digits, 24)
    elif country == "AT":
        bban = rand_str(rng, digits, 16)
    elif country == "CH":
        bban = rand_str(rng, digits, 5) + rand_str(rng, digits, 12)
    else:
        raise ValueError(country)
    out = country + cd.iban_check_digits(country, bban) + bban
    assert cd.iban_valid(out)
    return out


def iban_print(s: str) -> str:
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


IBAN_COUNTRY_OF = {"US": "GB", "GB": "GB", "IT": "IT", "DE": "DE", "FR": "FR", "ES": "ES", "NL": "NL", "PT": "PT",
                   "PL": "PL"}


def card_number(rng: random.Random, brand: str | None = None) -> tuple[str, str]:
    brand = brand or rng.choice(["visa", "visa", "mastercard", "mastercard", "amex", "discover"])
    if brand == "visa":
        payload = "4" + rand_str(rng, "0123456789", 14)
    elif brand == "mastercard":
        if rng.random() < 0.7:
            payload = str(rng.randint(51, 55)) + rand_str(rng, "0123456789", 13)
        else:
            payload = str(rng.randint(2221, 2720)) + rand_str(rng, "0123456789", 11)
    elif brand == "amex":
        payload = rng.choice(["34", "37"]) + rand_str(rng, "0123456789", 12)
    elif brand == "discover":
        payload = "6011" + rand_str(rng, "0123456789", 11)
    else:
        raise ValueError(brand)
    num = payload + cd.luhn_check_digit(payload)
    if num.startswith(("4242424242", "4111111111", "5555555555", "4000056655", "3782822463")):
        return card_number(rng, brand)
    assert cd.luhn_valid(num)
    return num, brand


def card_format(num: str, rng: random.Random) -> str:
    sep = rng.choice([" ", " ", "-", ""])
    if len(num) == 15:
        return sep.join([num[:4], num[4:10], num[10:]])
    return sep.join(num[i:i + 4] for i in range(0, 16, 4))


def codice_fiscale(p: Persona) -> str:
    belfiore = p.city_rec[6] if p.locale == "it_IT" else "Z" + f"{(len(p.family) * 37) % 1000:03d}"
    return cd.codice_fiscale(p.family, p.given, p.birth, p.female, belfiore)


def steuer_id(rng: random.Random) -> str:
    while True:
        digits = list("0123456789")
        rng.shuffle(digits)
        chosen = digits[:9]
        dup = rng.choice(chosen)
        body = chosen + [dup]
        rng.shuffle(body)
        s = "".join(body)
        if s[0] == "0":
            continue
        out = s + cd.de_steuer_id_check(s)
        if cd.de_steuer_id_valid(out):
            return out


def fr_nir(p: Persona, rng: random.Random) -> str:
    dept = p.city_rec[1] if p.locale == "fr_FR" else "99"
    if dept == "99":
        commune = f"{rng.randint(100, 499):03d}"
    else:
        commune = f"{rng.randint(1, 400):03d}"
    body = f"{2 if p.female else 1}{p.birth.year % 100:02d}{p.birth.month:02d}{dept}{commune}{rng.randint(1, 999):03d}"
    return body + cd.fr_nir_key(body)


def fr_nir_print(n: str) -> str:
    return f"{n[0]} {n[1:3]} {n[3:5]} {n[5:7]} {n[7:10]} {n[10:13]} {n[13:]}"


def es_dni(rng: random.Random, nie: bool = False) -> str:
    if nie:
        pfx = rng.choice("XYZ")
        num = rng.randint(0, 9_999_999)
        full = int(str("XYZ".index(pfx)) + f"{num:07d}")
        return f"{pfx}{num:07d}{cd.es_dni_letter(full)}"
    n = rng.randint(1_000_000, 99_999_999)
    return f"{n:08d}{cd.es_dni_letter(n)}"


def nl_bsn(rng: random.Random) -> str:
    while True:
        first8 = rand_str(rng, "0123456789", 8)
        if first8[0] == "0":
            continue
        last = cd.nl_bsn_last_digit(first8)
        if last is not None:
            out = first8 + last
            if cd.nl_bsn_valid(out):
                return out


def uk_nino(rng: random.Random) -> str:
    while True:
        a = rng.choice([c for c in UPPER if c not in "DFIQUV"])
        b = rng.choice([c for c in UPPER if c not in "DFIOQUV"])
        if a + b in {"BG", "GB", "KN", "NK", "NT", "TN", "ZZ"}:
            continue
        d = rand_str(rng, "0123456789", 6)
        out = f"{a}{b}{d}{rng.choice('ABCD')}"
        if cd.uk_nino_valid(out):
            return out


def uk_nino_print(n: str) -> str:
    return f"{n[:2]} {n[2:4]} {n[4:6]} {n[6:8]} {n[8]}"


def us_ssn(rng: random.Random) -> str:
    while True:
        area = rng.randint(1, 899)
        if area == 666:
            continue
        out = f"{area:03d}-{rng.randint(1, 99):02d}-{rng.randint(1, 9999):04d}"
        if cd.us_ssn_valid(out) and not out.startswith(("078-05-1120", "123-45-6789")):
            return out


def pl_pesel(p: Persona, rng: random.Random) -> str:
    serial = f"{rng.randint(0, 999):03d}"
    sex = rng.choice("02468" if p.female else "13579")
    first10 = cd.pl_pesel_date_part(p.birth) + serial + sex
    return first10 + cd.pl_pesel_check(first10)


def pt_nif(rng: random.Random) -> str:
    first8 = rng.choice("123") + rand_str(rng, "0123456789", 7)
    return first8 + cd.pt_nif_check(first8)


def ch_ahv(rng: random.Random) -> str:
    first12 = "756" + rand_str(rng, "0123456789", 9)
    full = first12 + cd.ean13_check(first12)
    return f"{full[:3]}.{full[3:7]}.{full[7:11]}.{full[11:]}"


def national_id(p: Persona, rng: random.Random) -> tuple[str, str]:
    """(kind, value) for the persona's country."""
    c = p.country
    if c == "IT":
        return "codice_fiscale", codice_fiscale(p)
    if c == "DE":
        return "steuer_id", steuer_id(rng)
    if c == "FR":
        return "nir", fr_nir(p, rng)
    if c == "ES":
        return "dni", es_dni(rng, nie=rng.random() < 0.15)
    if c == "NL":
        return "bsn", nl_bsn(rng)
    if c == "GB":
        return "nino", uk_nino(rng)
    if c == "US":
        return "ssn", us_ssn(rng)
    if c == "PL":
        return "pesel", pl_pesel(p, rng)
    if c == "PT":
        return "nif", pt_nif(rng)
    raise ValueError(c)


CUSTOMER_STYLES = 6
EMPLOYEE_STYLES = 6


def customer_no(rng: random.Random, style: int | None = None) -> str:
    style = rng.randrange(CUSTOMER_STYLES) if style is None else style
    return [
        lambda: f"CUST-{rng.randint(10000, 9999999):07d}", lambda: f"C{rng.randint(100000, 999999)}",
        lambda: f"KD-{rng.randint(100000, 999999)}", lambda: f"CLI{rng.randint(2015, 2026)}{rng.randint(1000, 99999):05d}",
        lambda: f"{rng.randint(10_000_000, 99_999_999)}", lambda: f"ACC-{rand_str(rng, UPPER, 2)}{rng.randint(10000, 99999)}",
    ][style]()


def employee_no(rng: random.Random, style: int | None = None) -> str:
    style = rng.randrange(EMPLOYEE_STYLES) if style is None else style
    return [
        lambda: f"EMP{rng.randint(1000, 99999):05d}", lambda: f"E-{rng.randint(10000, 99999)}",
        lambda: f"{rng.randint(100000, 999999)}", lambda: f"PN{rng.randint(100000, 999999)}",
        lambda: f"MAT-{rng.randint(1000, 9999)}", lambda: f"HR{rng.randint(2010, 2026)}-{rng.randint(100, 999)}",
    ][style]()


# ---------------------------------------------------------------- documents / vehicles


def passport(rng: random.Random, country: str) -> str:
    d = "0123456789"
    if country == "IT":
        return rand_str(rng, UPPER, 2) + rand_str(rng, d, 7)
    if country == "DE":
        return rng.choice("CFGHJK") + rand_str(rng, "CFGHJKLMNPRTVWXYZ0123456789", 8)
    if country == "FR":
        return rand_str(rng, d, 2) + rand_str(rng, UPPER, 2) + rand_str(rng, d, 5)
    if country == "ES":
        return rand_str(rng, UPPER, 3) + rand_str(rng, d, 6)
    if country == "NL":
        return rand_str(rng, "ABCDEFGHIJKLMNPRSTUVWXYZ", 2) + rand_str(rng, "ABCDEFGHIJKLMNPRSTUVWXYZ0123456789", 6) + rng.choice(d)
    if country == "GB":
        return rand_str(rng, d, 9)
    if country == "US":
        return rng.choice([rand_str(rng, d, 9), rng.choice("ACEFGHJKLMNPRSTUVWXYZ") + rand_str(rng, d, 8)])
    if country == "PL":
        return rand_str(rng, UPPER, 2) + rand_str(rng, d, 7)
    if country == "PT":
        return rng.choice("CPN") + rand_str(rng, d, 6)
    raise ValueError(country)


def driver_license(p: Persona, rng: random.Random) -> str:
    c = p.country
    d = "0123456789"
    if c == "GB":
        fam = (p.f_ascii.upper() + "99999")[:5]
        y = p.birth.year
        month = p.birth.month + (50 if p.female else 0)
        inits = (p.g_ascii[:1] + "9").upper()[:2]
        return f"{fam}{(y // 10) % 10}{month:02d}{p.birth.day:02d}{y % 10}{inits}9{rand_str(rng, UPPER, 2)}"
    if c == "IT":
        return rand_str(rng, UPPER, 2) + rand_str(rng, d, 7) + rng.choice(UPPER)
    if c == "DE":
        return rng.choice("BFGHJKLMNSTWX") + rand_str(rng, d, 3) + rand_str(rng, UPPER + d, 6) + rng.choice(d)
    if c == "FR":
        return rand_str(rng, d, 12)
    if c == "ES":
        return es_dni(rng)
    if c == "NL":
        return rand_str(rng, d, 10)
    if c == "PL":
        return f"{rand_str(rng, d, 5)}/{rand_str(rng, d, 2)}/{rand_str(rng, d, 4)}"
    if c == "PT":
        return f"{rng.choice(['L', 'P', 'C', 'A'])}-{rand_str(rng, d, 7)} {rng.randint(1, 9)}"
    if c == "US":
        st = p.city_rec[1]
        if st == "CA":
            return rng.choice(UPPER) + rand_str(rng, d, 7)
        if st in ("TX",):
            return rand_str(rng, d, 8)
        if st == "WA":
            return "WDL" + rand_str(rng, UPPER + d, 9)
        if st == "IL":
            return rng.choice(UPPER) + rand_str(rng, d, 11)
        return rng.choice(UPPER) + rand_str(rng, d, 8)
    raise ValueError(c)


_PLATE_LET = "ABCDEFGHJKLMNPRSTVWXYZ"


def number_plate(rng: random.Random, country: str, rec: tuple | None = None) -> str:
    d = "0123456789"
    if country == "IT":
        return f"{rand_str(rng, _PLATE_LET, 2)}{rng.choice(['', ' '])}{rand_str(rng, d, 3)}{rng.choice(['', ' '])}{rand_str(rng, _PLATE_LET, 2)}"
    if country == "DE":
        code = rec[1] if rec else rng.choice(["B", "M", "HH", "K", "F", "S"])
        return f"{code}{rng.choice(['-', ' '])}{rand_str(rng, 'ABCDEFGHJKLMNPRSTUVWXYZ', rng.randint(1, 2))} {rng.randint(1, 9999)}"
    if country == "FR":
        return f"{rand_str(rng, _PLATE_LET, 2)}-{rand_str(rng, d, 3)}-{rand_str(rng, _PLATE_LET, 2)}"
    if country == "GB":
        age = rng.choice([f"{y:02d}" for y in list(range(15, 26)) + list(range(65, 76))])
        return f"{rand_str(rng, 'ABCDEFGHJKLMNOPRSTUVWXY', 2)}{age} {rand_str(rng, 'ABCDEFGHJKLMNOPRSTUVWXYZ', 3)}"
    if country == "ES":
        return f"{rand_str(rng, d, 4)} {rand_str(rng, 'BCDFGHJKLMNPRSTVWXYZ', 3)}"
    if country == "NL":
        return rng.choice([f"{rand_str(rng, 'GHJKLNPRSTXZ', 1)}-{rand_str(rng, d, 3)}-{rand_str(rng, 'BDFGHJKLNPRSTVXZ', 2)}",
                           f"{rand_str(rng, d, 2)}-{rand_str(rng, 'BDFGHJKLNPRSTVXZ', 3)}-{rng.choice(d)}"])
    if country == "PL":
        code = rec[1] if rec else "WA"
        return f"{code} {rand_str(rng, d, 4)}{rng.choice(_PLATE_LET)}"
    if country == "PT":
        return f"{rand_str(rng, _PLATE_LET, 2)}-{rand_str(rng, d, 2)}-{rand_str(rng, _PLATE_LET, 2)}"
    if country == "US":
        return f"{rng.randint(1, 9)}{rand_str(rng, 'ABCDEFGHJKLMNPRSTUVWXYZ', 3)}{rand_str(rng, d, 3)}"
    raise ValueError(country)


def vin(rng: random.Random) -> str:
    wmi = rng.choice(WMIS)
    vds = rand_str(rng, "ABCDEFGHJKLMNPRSTUVWXYZ0123456789", 5)
    year = rng.choice(VIN_YEARS)
    plant = rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")
    serial = rand_str(rng, "0123456789", 6)
    body = wmi + vds + "0" + year + plant + serial
    out = body[:8] + cd.vin_check_digit(body) + body[9:]
    assert cd.vin_valid(out)
    return out


# ---------------------------------------------------------------- secrets (vendor formats, random)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def jwt(rng: random.Random, claims: dict | None = None, alg: str = "HS256") -> str:
    header = {"alg": alg, "typ": "JWT"}
    if alg.startswith("RS"):
        header["kid"] = rand_str(rng, ALNUM, 16)
    now = rng.randint(1_760_000_000, 1_790_000_000)
    payload = {"sub": str(rng.randint(10000, 9999999)), "iat": now, "exp": now + rng.choice([900, 3600, 86400])}
    if claims:
        payload.update(claims)
    h = b64url(json.dumps(header, separators=(",", ":")).encode())
    p = b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    sig_len = 43 if alg.startswith("HS") else 342
    return f"{h}.{p}.{rand_str(rng, B64URL, sig_len)}"


def pem_private_key(rng: random.Random, kind: str = "rsa") -> str:
    if kind == "rsa":
        head, foot = "-----BEGIN RSA PRIVATE KEY-----", "-----END RSA PRIVATE KEY-----"
        body = "MIIEpAIBAAKCAQEA" + rand_str(rng, B64, 1560)
    elif kind == "pkcs8":
        head, foot = "-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----"
        body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ" + rand_str(rng, B64, 1530)
    elif kind == "ec":
        head, foot = "-----BEGIN EC PRIVATE KEY-----", "-----END EC PRIVATE KEY-----"
        body = "MHcCAQEEI" + rand_str(rng, B64, 155)
    elif kind == "openssh":
        head, foot = "-----BEGIN OPENSSH PRIVATE KEY-----", "-----END OPENSSH PRIVATE KEY-----"
        body = "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW" + rand_str(rng, B64, 330)
    else:
        raise ValueError(kind)
    pad = (-len(body)) % 4
    body = body + ("=" * pad if pad < 3 else rand_str(rng, B64, pad))
    rows = [body[i:i + 64] for i in range(0, len(body), 64)] if kind != "openssh" else [body[i:i + 70] for i in range(0, len(body), 70)]
    return "\n".join([head, *rows, foot])


def password(rng: random.Random) -> str:
    style = rng.randint(0, 5)
    if style == 0:
        return rng.choice(PASSWORD_WORDS) + rng.choice(["!", "#", "$", "@", "%", "&", "*"]) + str(rng.randint(10, 2026))
    if style == 1:
        return rand_str(rng, ALNUM, rng.randint(16, 28))
    if style == 2:
        return rand_str(rng, ALNUM + "!#%^*-_=+", rng.randint(14, 24))
    if style == 3:
        w = rng.sample(PASSWORD_WORDS, 3)
        return "-".join(x.lower() for x in w) + str(rng.randint(1, 99))
    if style == 4:
        return rand_str(rng, HEX, 32)
    return rng.choice(PASSWORD_WORDS) + str(rng.randint(1, 9)) + rng.choice(PASSWORD_WORDS).lower() + rng.choice("!?.")


def secret_token(rng: random.Random, kind: str) -> str:
    A = ALNUM
    if kind == "aws_akid":
        return "AKIA" + rand_str(rng, UPPER + "234567", 16)
    if kind == "aws_asia":
        return "ASIA" + rand_str(rng, UPPER + "234567", 16)
    if kind == "aws_secret":
        return rand_str(rng, A + "/+", 40)
    if kind == "github_pat":
        return "ghp_" + rand_str(rng, A, 36)
    if kind == "github_fine":
        return "github_pat_" + rand_str(rng, A, 22) + "_" + rand_str(rng, A, 59)
    if kind == "github_oauth":
        return "gho_" + rand_str(rng, A, 36)
    if kind == "github_app":
        return "ghs_" + rand_str(rng, A, 36)
    if kind == "gitlab_pat":
        return "glpat-" + rand_str(rng, A + "-_", 20)
    if kind == "stripe_live":
        return "sk_live_" + rand_str(rng, A, rng.choice([24, 99]))
    if kind == "stripe_restricted":
        return "rk_live_" + rand_str(rng, A, 99)
    if kind == "stripe_whsec":
        return "whsec_" + rand_str(rng, A, 32)
    if kind == "slack_bot":
        return f"xoxb-{rng.randint(10**10, 10**12)}-{rng.randint(10**11, 10**13)}-{rand_str(rng, A, 24)}"
    if kind == "slack_user":
        return f"xoxp-{rng.randint(10**10, 10**12)}-{rng.randint(10**10, 10**12)}-{rng.randint(10**11, 10**13)}-{rand_str(rng, HEX, 32)}"
    if kind == "slack_webhook":
        return f"https://hooks.slack.com/services/T{rand_str(rng, UPPER + '0123456789', 10)}/B{rand_str(rng, UPPER + '0123456789', 10)}/{rand_str(rng, A, 24)}"
    if kind == "openai":
        return "sk-proj-" + rand_str(rng, A + "-_", 156)
    if kind == "anthropic":
        return "sk-ant-api03-" + rand_str(rng, A + "-_", 93) + "AA"
    if kind == "google_api":
        return "AIza" + rand_str(rng, A + "-_", 35)
    if kind == "twilio_auth":
        return rand_str(rng, HEX, 32)
    if kind == "twilio_key":
        return "SK" + rand_str(rng, HEX, 32)
    if kind == "sendgrid":
        return "SG." + rand_str(rng, A + "-_", 22) + "." + rand_str(rng, A + "-_", 43)
    if kind == "npm":
        return "npm_" + rand_str(rng, A, 36)
    if kind == "pypi":
        return "pypi-AgEIcHlwaS5vcmc" + rand_str(rng, A + "-_", 150)
    if kind == "hf":
        return "hf_" + rand_str(rng, string.ascii_letters, 34)
    if kind == "datadog":
        return rand_str(rng, HEX, 32)
    if kind == "sentry_dsn":
        return f"https://{rand_str(rng, HEX, 32)}@o{rng.randint(100000, 4999999)}.ingest.sentry.io/{rng.randint(1000000, 9999999)}"
    if kind == "mailgun":
        return "key-" + rand_str(rng, HEX, 32)
    if kind == "shopify":
        return "shpat_" + rand_str(rng, HEX, 32)
    if kind == "digitalocean":
        return "dop_v1_" + rand_str(rng, HEX, 64)
    if kind == "dockerhub":
        return "dckr_pat_" + rand_str(rng, A + "-_", 27)
    if kind == "linear":
        return "lin_api_" + rand_str(rng, A, 40)
    if kind == "notion":
        return "ntn_" + rand_str(rng, "0123456789", 11) + rand_str(rng, A, 35)
    if kind == "telegram":
        return f"{rng.randint(10**8, 10**10)}:AA{rand_str(rng, A + '-_', 33)}"
    if kind == "discord":
        return rand_str(rng, "MNO", 1) + rand_str(rng, A, 23) + "." + rand_str(rng, A + "-_", 6) + "." + rand_str(rng, A + "-_", 38)
    if kind == "azure_storage_key":
        return rand_str(rng, A + "+/", 86) + "=="
    if kind == "gcp_api":
        return "AIza" + rand_str(rng, A + "-_", 35)
    if kind == "heroku":
        return f"{rand_str(rng, HEX, 8)}-{rand_str(rng, HEX, 4)}-{rand_str(rng, HEX, 4)}-{rand_str(rng, HEX, 4)}-{rand_str(rng, HEX, 12)}"
    if kind == "session":
        return rand_str(rng, "abcdefghijklmnopqrstuvwxyz0123456789", 32)
    if kind == "session_signed":
        return "s%3A" + rand_str(rng, A + "-_", 32) + "." + rand_str(rng, A + "%", 43)
    if kind == "rails_session":
        return rand_str(rng, A + "%", 180) + "--" + rand_str(rng, HEX, 40)
    if kind == "django_secret":
        return "django-insecure-" + rand_str(rng, "abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)", 50) if rng.random() < 0.3 else rand_str(rng, "abcdefghijklmnopqrstuvwxyz0123456789!@#%^&*(-_=+)", 50)
    if kind == "app_key":
        return "base64:" + base64.b64encode(bytes(rng.randint(0, 255) for _ in range(32))).decode()
    if kind == "hex32":
        return rand_str(rng, HEX, 64)
    if kind == "bearer_opaque":
        return rand_str(rng, A, 40)
    if kind == "vault_token":
        return "hvs." + rand_str(rng, A + "-_", 90)
    if kind == "age_key":
        return "AGE-SECRET-KEY-1" + rand_str(rng, "QPZRY9X8GF2TVDW0S3JN54KHCE6MUA7L", 58)
    raise ValueError(kind)


SECRET_KINDS = ["aws_akid", "aws_secret", "github_pat", "github_fine", "gitlab_pat", "stripe_live",
                "stripe_whsec", "slack_bot", "slack_webhook", "openai", "anthropic", "google_api", "twilio_auth",
                "sendgrid", "npm", "pypi", "hf", "datadog", "sentry_dsn", "mailgun", "shopify", "digitalocean",
                "dockerhub", "linear", "telegram", "discord", "vault_token"]
