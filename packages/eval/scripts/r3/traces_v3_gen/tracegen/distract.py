# SPDX-License-Identifier: Apache-2.0
"""Raw distractor generators: machine timestamps, identifiers, reserved IPs,
placeholders. These look like personal data or secrets but are not."""

from __future__ import annotations

import datetime as dt
import random

from .values import ALNUM, HEX, rand_str

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class Clock:
    """A per-document wall clock that only moves forward."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        start = dt.datetime(2025, 1, 6, tzinfo=dt.timezone.utc)
        self.t = start + dt.timedelta(seconds=rng.randint(0, 650 * 86400))
        self.tz_hours = rng.choice([0, 0, 1, 2, -5, -8, 0, 1])

    def tick(self, lo: float = 0.0, hi: float = 5.0) -> dt.datetime:
        self.t += dt.timedelta(seconds=self.rng.uniform(lo, hi))
        return self.t

    def jump(self, days_lo: int = 1, days_hi: int = 30) -> dt.datetime:
        self.t += dt.timedelta(days=self.rng.randint(days_lo, days_hi), seconds=self.rng.randint(0, 86400))
        return self.t

    def local(self, t: dt.datetime | None = None) -> dt.datetime:
        t = t or self.t
        return t.astimezone(dt.timezone(dt.timedelta(hours=self.tz_hours)))


def fmt_ts(t: dt.datetime, style: str) -> str:
    ms = t.microsecond // 1000
    off = t.utcoffset() or dt.timedelta(0)
    sign = "+" if off >= dt.timedelta(0) else "-"
    mins = abs(int(off.total_seconds())) // 60
    offs = f"{sign}{mins // 60:02d}{mins % 60:02d}"
    offc = f"{sign}{mins // 60:02d}:{mins % 60:02d}"
    if style == "iso_z":
        return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"
    if style == "iso_s":
        return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if style == "iso_off":
        return t.strftime("%Y-%m-%dT%H:%M:%S") + offc
    if style == "iso_us":
        return t.strftime("%Y-%m-%dT%H:%M:%S.%f") + offc
    if style == "space_ms":
        return t.strftime("%Y-%m-%d %H:%M:%S") + f",{ms:03d}"
    if style == "space_dot":
        return t.strftime("%Y-%m-%d %H:%M:%S") + f".{ms:03d}"
    if style == "space":
        return t.strftime("%Y-%m-%d %H:%M:%S")
    if style == "slash":
        return t.strftime("%Y/%m/%d %H:%M:%S")
    if style == "syslog":
        return f"{_MON[t.month - 1]} {t.day:2d} {t:%H:%M:%S}"
    if style == "clf":
        return f"{t.day:02d}/{_MON[t.month - 1]}/{t.year}:{t:%H:%M:%S} {offs}"
    if style == "git":
        return f"{_DOW[t.weekday()]} {_MON[t.month - 1]} {t.day} {t:%H:%M:%S} {t.year} {offs}"
    if style == "git_iso":
        return t.strftime("%Y-%m-%d %H:%M:%S ") + offs
    if style == "http":
        u = t.astimezone(dt.timezone.utc)
        return f"{_DOW[u.weekday()]}, {u.day:02d} {_MON[u.month - 1]} {u.year} {u:%H:%M:%S} GMT"
    if style == "ls":
        return f"{_MON[t.month - 1]} {t.day:2d} {t:%H:%M}"
    if style == "epoch":
        return str(int(t.timestamp()))
    if style == "epoch_ms":
        return str(int(t.timestamp() * 1000))
    if style == "time":
        return t.strftime("%H:%M:%S")
    if style == "time_ms":
        return t.strftime("%H:%M:%S") + f".{ms:03d}"
    if style == "pg":
        return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.") + f"{ms:03d} UTC"
    if style == "date":
        return t.strftime("%Y-%m-%d")
    if style == "rfc2822":
        return f"{_DOW[t.weekday()]}, {t.day} {_MON[t.month - 1]} {t.year} {t:%H:%M:%S} {offs}"
    raise ValueError(style)


def sha1(rng: random.Random) -> str:
    return rand_str(rng, HEX, 40)


def short_sha(rng: random.Random, n: int | None = None) -> str:
    return rand_str(rng, HEX, n or rng.choice([7, 7, 8, 9, 10, 12]))


def sha256(rng: random.Random) -> str:
    return rand_str(rng, HEX, 64)


def uuid4(rng: random.Random) -> str:
    h = rand_str(rng, HEX, 32)
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-{rng.choice('89ab')}{h[17:20]}-{h[20:32]}"


def version(rng: random.Random) -> str:
    v = f"{rng.randint(0, 9)}.{rng.randint(0, 30)}.{rng.randint(0, 20)}"
    r = rng.random()
    if r < 0.1:
        v += f"-rc.{rng.randint(1, 5)}"
    elif r < 0.15:
        v += f"-beta.{rng.randint(1, 9)}"
    return v


def request_id(rng: random.Random) -> str:
    return rng.choice([uuid4(rng), "req_" + rand_str(rng, ALNUM, 24), rand_str(rng, HEX, 16),
                       f"{rand_str(rng, HEX, 8)}-{rand_str(rng, HEX, 4)}"])


def reserved_ip(rng: random.Random, v6: bool | None = None) -> str:
    if v6 is None:
        v6 = rng.random() < 0.2
    if v6:
        return rng.choice(["::1", "::", f"2001:db8::{rng.randint(1, 0xffff):x}",
                           f"2001:db8:{rng.randint(0, 0xffff):x}::{rng.randint(1, 0xff):x}",
                           f"2001:db8:{rng.randint(0, 0xffff):x}:{rng.randint(0, 0xffff):x}::{rng.randint(1, 0xffff):x}"])
    r = rng.random()
    if r < 0.35:
        return "127.0.0.1"
    if r < 0.42:
        return f"127.0.{rng.randint(0, 1)}.{rng.randint(1, 9)}"
    if r < 0.55:
        return "0.0.0.0"
    return rng.choice(["192.0.2", "198.51.100", "203.0.113"]) + f".{rng.randint(1, 254)}"


PLACEHOLDERS = {
    "api_key": ["YOUR_API_KEY", "your-api-key-here", "<api-key>", "<YOUR_KEY>", "REPLACE_ME", "xxxxxxxxxxxxxxxx",
                "sk_test_XXXXXXXXXXXXXXXXXXXXXXXX", "AKIAIOSFODNN7EXAMPLE", "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "${API_KEY}", "{{ secrets.API_KEY }}", "<redacted>", "****************", "[REDACTED]",
                "dummy-key", "test-key-not-real", "sk-...", "ENC[...]"],
    "token": ["<token>", "YOUR_TOKEN", "$TOKEN", "${GITHUB_TOKEN}", "<your-token-here>", "xxxx.yyyy.zzzz",
              "eyJhbGciOi...", "REDACTED", "***", "<access_token>", "{{ .Values.token }}", "TOKEN_GOES_HERE"],
    "password": ["changeme", "password", "<password>", "${DB_PASSWORD}", "secret", "********", "CHANGE_ME",
                 "example-password", "{{ db_password }}", "%(DB_PASS)s", "<db-password>", "postgres", "admin",
                 "hunter2", "•••••••••"],
    "email": ["user@example.com", "jane.doe@example.com", "test@example.org", "noreply@example.com",
              "admin@example.net", "you@yourdomain.com", "name@company.com", "foo@bar.com", "someone@example.com",
              "user@localhost"],
    "phone": ["+1 555-0100", "555-0123", "(555) 010-4477", "+44 7700 900123", "020 7946 0018", "+33 1 23 45 67 89",
              "000-000-0000", "+39 000 0000000", "+49 000 0000000", "+1-202-555-0175", "XXX-XXX-XXXX"],
    "card": ["4242 4242 4242 4242", "4111 1111 1111 1111", "**** **** **** 4242", "****1234", "XXXX-XXXX-XXXX-1881",
             "5555 5555 5555 4444", "•••• 0005"],
    "iban": ["DE00 0000 0000 0000 0000 00", "IT00X0000000000000000000000", "XX00 XXXX XXXX XXXX", "GB** **** **** 1234"],
    "name": ["John Doe", "Jane Doe", "Max Mustermann", "Erika Mustermann", "Mario Rossi", "Jean Dupont",
             "Test User", "Demo Account", "Example Person", "Fulano de Tal", "<name>", "{{first_name}}",
             "%FIRSTNAME%"],
    "address": ["123 Main Street, Anytown", "Musterstraße 1, 12345 Musterstadt", "Via Roma 1, 00000 Città",
                "1 rue de l'Exemple, 00000 Ville", "<street address>", "Street 1, City", "{{address_line_1}}"],
    "street": ["123 Main Street", "Musterstraße 1", "Via Roma 1", "1 rue de l'Exemple", "Calle Falsa 123",
               "<street>", "{{street}}"],
    "postcode": ["00000", "12345", "XXXXX", "<zip>", "AB1 2CD", "{{postcode}}"],
    "city": ["Anytown", "Musterstadt", "Springfield", "<city>", "{{city}}", "Ville"],
    "date": ["1970-01-01", "01/01/1900", "YYYY-MM-DD", "dd.mm.yyyy", "0000-00-00", "MM/DD/YYYY"],
    "id": ["XXX-XX-XXXX", "000-00-0000", "AB123456C", "RSSMRA80A01H501U", "12345678Z", "<national-id>",
           "XXXXXXXXX", "123456789"],
    "mac": ["00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "XX:XX:XX:XX:XX:XX", "aa:bb:cc:dd:ee:ff", "<mac>"],
    "geo": ["0.0, 0.0", "0.000000, 0.000000", "<lat>,<lng>", "LAT,LON", "null, null"],
    "plate": ["XX-000-XX", "AB 123 CD", "<plate>", "ABC-1234", "XX 000 XX"],
    "vin": ["1HGCM82633A004352", "XXXXXXXXXXXXXXXXX", "<vin>", "VIN_PLACEHOLDER"],
    "passport": ["X0000000", "<passport-no>", "000000000", "P<UTOERIKSSON<<ANNA<MARIA"],
    "url": ["https://example.com/your/path", "http://localhost:8080/callback", "https://your-domain.example/webhook",
            "https://<your-host>/api", "https://example.org/user/<id>"],
    "user": ["<username>", "your-username", "USERNAME", "$USER", "{{username}}", "%USERNAME%", "user"],
    "generic": ["xxx-xxx", "XXXX", "TODO", "<redacted>", "[REDACTED]", "N/A", "TBD", "***"],
}


def placeholder(rng: random.Random, kind: str) -> str:
    return rng.choice(PLACEHOLDERS[kind])
