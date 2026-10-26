# SPDX-License-Identifier: Apache-2.0
"""Check-digit algorithms written for this generator from the public format
definitions (ISO 7064, ISO 13616, ISO 3779, ICAO 9303 and national rules)."""

from __future__ import annotations

import datetime as _dt
import string
import unicodedata

# ---------------------------------------------------------------- Luhn (cards)


def luhn_check_digit(payload: str) -> str:
    """Digit that makes `payload + digit` Luhn-valid."""
    total = 0
    for i, ch in enumerate(reversed(payload)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def luhn_valid(number: str) -> bool:
    digits = [c for c in number if c.isdigit()]
    if len(digits) < 2:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---------------------------------------------------------------- IBAN (ISO 13616, ISO 7064 MOD 97-10)


def _iban_numeric(s: str) -> str:
    out = []
    for ch in s:
        if ch.isdigit():
            out.append(ch)
        elif ch.isalpha():
            out.append(str(ord(ch.upper()) - 55))
        else:
            raise ValueError(f"bad IBAN character {ch!r}")
    return "".join(out)


def iban_check_digits(country: str, bban: str) -> str:
    n = int(_iban_numeric(bban + country + "00"))
    return f"{98 - n % 97:02d}"


def iban_valid(iban: str) -> bool:
    s = iban.replace(" ", "").upper()
    if len(s) < 5 or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    return int(_iban_numeric(s[4:] + s[:4])) % 97 == 1


# Italian odd/even tables (shared by the IBAN CIN and the codice fiscale)
_IT_ODD = [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23]


def _it_value(ch: str, odd: bool) -> int:
    if ch.isdigit():
        idx = int(ch)
    else:
        idx = ord(ch.upper()) - 65
    return _IT_ODD[idx] if odd else idx


def it_cin(abi: str, cab: str, account: str) -> str:
    """CIN control letter of an Italian BBAN (ABI 5 + CAB 5 + conto 12)."""
    s = abi + cab + account
    if len(s) != 22:
        raise ValueError("ABI+CAB+account must be 22 characters")
    total = sum(_it_value(ch, i % 2 == 0) for i, ch in enumerate(s))
    return chr(65 + total % 26)


_FR_LETTERS = {**{c: v for v, cs in enumerate(["", "AJ", "BKS", "CLT", "DMU", "ENV", "FOW", "GPX", "HQY", "IRZ"])
                  for c in cs}}


def _fr_digits(s: str) -> int:
    return int("".join(str(_FR_LETTERS[c]) if c.isalpha() else c for c in s.upper()))


def fr_rib_key(bank: str, branch: str, account: str) -> str:
    """Clé RIB: 97 - ((89*bank + 15*branch + 3*account) mod 97)."""
    total = 89 * _fr_digits(bank) + 15 * _fr_digits(branch) + 3 * _fr_digits(account)
    return f"{97 - total % 97:02d}"


_ES_WEIGHTS = [1, 2, 4, 8, 5, 10, 9, 7, 3, 6]


def _es_dc_one(ten: str) -> str:
    r = 11 - sum(int(d) * w for d, w in zip(ten, _ES_WEIGHTS)) % 11
    if r == 11:
        r = 0
    elif r == 10:
        r = 1
    return str(r)


def es_dc(bank: str, branch: str, account: str) -> str:
    """Spanish CCC control digits (dígitos de control)."""
    return _es_dc_one("00" + bank + branch) + _es_dc_one(account)


def nl_account_valid(acct10: str) -> bool:
    """Dutch '11-proof' on a 10-digit bank account number."""
    return sum(int(d) * w for d, w in zip(acct10, range(10, 0, -1))) % 11 == 0


def be_account_check(first10: str) -> str:
    r = int(first10) % 97
    return f"{97 if r == 0 else r:02d}"


def pt_nib_check(first19: str) -> str:
    return f"{98 - (int(first19) * 100) % 97:02d}"


# ---------------------------------------------------------------- Italian codice fiscale

_CF_MONTHS = "ABCDEHLMPRST"
_VOWELS = set("AEIOU")


def _ascii_upper_letters(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s.upper() if c in string.ascii_uppercase)


def _cf_part(name: str, is_given: bool) -> str:
    letters = _ascii_upper_letters(name)
    cons = [c for c in letters if c not in _VOWELS]
    vows = [c for c in letters if c in _VOWELS]
    if is_given and len(cons) >= 4:
        return cons[0] + cons[2] + cons[3]
    return ("".join(cons + vows) + "XXX")[:3]


def cf_check_char(first15: str) -> str:
    if len(first15) != 15:
        raise ValueError("codice fiscale body must be 15 characters")
    total = sum(_it_value(ch, i % 2 == 0) for i, ch in enumerate(first15))
    return chr(65 + total % 26)


def codice_fiscale(family: str, given: str, birth: _dt.date, female: bool, belfiore: str) -> str:
    day = birth.day + (40 if female else 0)
    body = (_cf_part(family, False) + _cf_part(given, True) + f"{birth.year % 100:02d}"
            + _CF_MONTHS[birth.month - 1] + f"{day:02d}" + belfiore.upper())
    return body + cf_check_char(body)


def cf_valid(cf: str) -> bool:
    return len(cf) == 16 and cf_check_char(cf[:15].upper()) == cf[15].upper()


# ---------------------------------------------------------------- German Steuer-IdNr (ISO 7064 MOD 11,10)


def de_steuer_id_check(first10: str) -> str:
    product = 10
    for ch in first10:
        s = (int(ch) + product) % 10
        if s == 0:
            s = 10
        product = (s * 2) % 11
    check = 11 - product
    return "0" if check == 10 else str(check)


def de_steuer_id_valid(tid: str) -> bool:
    tid = tid.replace(" ", "")
    if len(tid) != 11 or not tid.isdigit() or tid[0] == "0":
        return False
    counts = [tid[:10].count(d) for d in "0123456789"]
    repeated = [c for c in counts if c > 1]
    if len(repeated) != 1 or repeated[0] > 3:
        return False
    return de_steuer_id_check(tid[:10]) == tid[10]


# ---------------------------------------------------------------- French NIR (sécurité sociale)


def fr_nir_key(first13: str) -> str:
    return f"{97 - int(first13) % 97:02d}"


def fr_nir_valid(nir: str) -> bool:
    s = nir.replace(" ", "")
    return len(s) == 15 and s.isdigit() and fr_nir_key(s[:13]) == s[13:]


# ---------------------------------------------------------------- Spanish DNI / NIE

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def es_dni_letter(number: int) -> str:
    return _DNI_LETTERS[number % 23]


def es_dni_valid(dni: str) -> bool:
    s = dni.replace("-", "").upper()
    if s[0] in "XYZ":
        s = str("XYZ".index(s[0])) + s[1:]
    return len(s) == 9 and s[:8].isdigit() and es_dni_letter(int(s[:8])) == s[8]


# ---------------------------------------------------------------- Dutch BSN (11-proof)

_BSN_W = [9, 8, 7, 6, 5, 4, 3, 2, -1]


def nl_bsn_valid(bsn: str) -> bool:
    s = bsn.replace(".", "").replace(" ", "")
    if len(s) != 9 or not s.isdigit() or int(s) == 0:
        return False
    return sum(int(d) * w for d, w in zip(s, _BSN_W)) % 11 == 0


def nl_bsn_last_digit(first8: str) -> str | None:
    """Digit completing an 11-proof BSN, or None when no digit works."""
    d = sum(int(c) * w for c, w in zip(first8, _BSN_W)) % 11
    return None if d == 10 else str(d)


# ---------------------------------------------------------------- Polish PESEL

_PESEL_W = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]


def pl_pesel_check(first10: str) -> str:
    return str((10 - sum(int(d) * w for d, w in zip(first10, _PESEL_W)) % 10) % 10)


def pl_pesel_valid(p: str) -> bool:
    return len(p) == 11 and p.isdigit() and pl_pesel_check(p[:10]) == p[10]


def pl_pesel_date_part(birth: _dt.date) -> str:
    month = birth.month + (20 if birth.year >= 2000 else 0)
    return f"{birth.year % 100:02d}{month:02d}{birth.day:02d}"


# ---------------------------------------------------------------- Portuguese NIF (mod 11)


def pt_nif_check(first8: str) -> str:
    r = sum(int(d) * w for d, w in zip(first8, range(9, 1, -1))) % 11
    return "0" if r < 2 else str(11 - r)


def pt_nif_valid(n: str) -> bool:
    return len(n) == 9 and n.isdigit() and pt_nif_check(n[:8]) == n[8]


# ---------------------------------------------------------------- Swiss AHV/AVS number (EAN-13)


def ean13_check(first12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def ch_ahv_valid(ahv: str) -> bool:
    s = ahv.replace(".", "")
    return len(s) == 13 and s.startswith("756") and ean13_check(s[:12]) == s[12]


# ---------------------------------------------------------------- Belgian national register number


def be_nrn_check(first9: str, born_2000_or_later: bool) -> str:
    n = int(("2" if born_2000_or_later else "") + first9)
    return f"{97 - n % 97:02d}"


# ---------------------------------------------------------------- UK National Insurance number

_NINO_BAD_FIRST = set("DFIQUV")
_NINO_BAD_SECOND = set("DFIOQUV")
_NINO_BAD_PREFIX = {"BG", "GB", "KN", "NK", "NT", "TN", "ZZ"}


def uk_nino_valid(nino: str) -> bool:
    s = nino.replace(" ", "").upper()
    if len(s) != 9 or not s[:2].isalpha() or not s[2:8].isdigit() or s[8] not in "ABCD":
        return False
    return s[0] not in _NINO_BAD_FIRST and s[1] not in _NINO_BAD_SECOND and s[:2] not in _NINO_BAD_PREFIX


# ---------------------------------------------------------------- US SSN structural rules


def us_ssn_valid(ssn: str) -> bool:
    s = ssn.replace("-", "").replace(" ", "")
    if len(s) != 9 or not s.isdigit():
        return False
    area, group, serial = int(s[:3]), int(s[3:5]), int(s[5:])
    return 0 < area < 900 and area != 666 and group > 0 and serial > 0


# ---------------------------------------------------------------- VIN (ISO 3779, North American check digit)

_VIN_TRANSLIT = {
    **{str(d): d for d in range(10)},
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}
_VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
VIN_ALPHABET = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"


def vin_check_digit(vin: str) -> str:
    if len(vin) != 17:
        raise ValueError("VIN must be 17 characters")
    total = sum(_VIN_TRANSLIT[c] * w for c, w in zip(vin.upper(), _VIN_WEIGHTS))
    r = total % 11
    return "X" if r == 10 else str(r)


def vin_valid(vin: str) -> bool:
    v = vin.upper()
    if len(v) != 17 or any(c not in VIN_ALPHABET for c in v):
        return False
    return vin_check_digit(v) == v[8]


# ---------------------------------------------------------------- ICAO 9303 (MRZ) check digit


def icao_check_digit(s: str) -> str:
    weights = [7, 3, 1]
    total = 0
    for i, ch in enumerate(s.upper()):
        if ch.isdigit():
            v = int(ch)
        elif ch.isalpha():
            v = ord(ch) - 55
        elif ch == "<":
            v = 0
        else:
            raise ValueError(f"bad MRZ character {ch!r}")
        total += v * weights[i % 3]
    return str(total % 10)
