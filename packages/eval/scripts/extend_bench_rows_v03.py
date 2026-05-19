#!/usr/bin/env python3
"""Append coverage rows for the 6 v0.3 labels (`private_passport`,
`private_driver_license`, `private_vehicle_id`, `private_geolocation`,
`private_ip`, `private_mac`) to `nullpii-bench.jsonl`.

The earlier `generate_bench_rows.py` (seed 20260515) only exercised
secrets / long-doc chunking / multi-layer encoding / base64-wrapped /
validator-numbers — none of the six v0.3 labels was represented. Re-
running with the SAME seed would produce identical (already-appended)
rows. This script uses a distinct seed and emits a disjoint row set so
appending is idempotent.

Independent-gold rule: pure-Python templates + seeded RNG + structural
validators (ISO 3779 VIN mod-11) computed inline. No `nullpii` /
`nullpii_eval` import. Spans labelled directly from template metadata,
not via any detector.

Usage:
  python packages/eval/scripts/extend_bench_rows_v03.py \\
    --out packages/eval/datasets/nullpii-bench.jsonl --append
"""
from __future__ import annotations

import argparse
import json
import random
import string
from collections import Counter
from pathlib import Path

RNG = random.Random(20260517)
SAMPLES: list[dict] = []

VIN_TRANSLIT: dict[str, int] = {
    **{c: int(c) for c in "0123456789"},
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}
VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
VIN_ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"  # ISO 3779 excludes I/O/Q


def add(text: str, spans: list[tuple[int, int, str]], category: str) -> None:
    SAMPLES.append({
        "text": text,
        "spans": [{"label": lbl, "start": st, "end": en} for st, en, lbl in spans],
        "category": category,
    })


def make_vin() -> str:
    """ISO 3779-valid VIN: 17 chars, mod-11 weighted check digit at pos 9."""
    while True:
        chars = [RNG.choice(VIN_ALPHABET) for _ in range(17)]
        chars[8] = "0"  # placeholder, replaced below
        total = sum(VIN_TRANSLIT[c] * w for c, w in zip(chars, VIN_WEIGHTS))
        rem = total % 11
        check = "X" if rem == 10 else str(rem)
        if check not in VIN_ALPHABET and check != "X":
            continue
        chars[8] = check
        return "".join(chars)


def rand_letters(n: int) -> str:
    return "".join(RNG.choices(string.ascii_uppercase, k=n))


def rand_digits(n: int) -> str:
    return "".join(RNG.choices(string.digits, k=n))


# ─── Passport (15 rows, 6 jurisdictions) ───────────────────────────
def gen_passport() -> None:
    templates = [
        # (template, country, generator)
        ("My passport: {x} expires 2031.", "us",
            lambda: RNG.choice("ABCDEFGHJKLMNPRSTUVWXYZ") + rand_digits(8)),
        ("US passport book {x} issued in California.", "us",
            lambda: RNG.choice("ABCDEFGHJKLMNPRSTUVWXYZ") + rand_digits(8)),
        ("Passaporto: {x}, valido fino al 2029.", "it",
            lambda: rand_letters(2) + rand_digits(7)),
        ("Passport no. {x} confirmed at border control.", "uk",
            lambda: rand_digits(9)),
        ("UK passport number: {x}.", "uk",
            lambda: rand_digits(9)),
        ("Passnummer: {x} ausgestellt.", "de",
            lambda: RNG.choice("CFGRPT") + "".join(RNG.choices(string.ascii_uppercase + string.digits, k=9))),
        ("Passeport n° {x} renouvelé.", "fr",
            lambda: rand_digits(2) + rand_letters(2) + rand_digits(5)),
        ("Pasaporte: {x}, fecha de caducidad 2030.", "es",
            lambda: rand_letters(3) + rand_digits(6)),
        ("Reisepass: {x} - bitte vorzeigen.", "de",
            lambda: RNG.choice("CFGRPT") + "".join(RNG.choices(string.ascii_uppercase + string.digits, k=9))),
        ("Customer's passport {x} on file.", "us",
            lambda: RNG.choice("ABCDEFGHJKLMNPRSTUVWXYZ") + rand_digits(8)),
        ("Paspoort: {x}, geldig.", "nl",
            lambda: rand_letters(2) + rand_digits(7)),
        ("Travel doc passport: {x}, no issues.", "generic",
            lambda: rand_letters(2) + rand_digits(7)),
        ("Passport # {x} scanned at gate B14.", "uk",
            lambda: rand_digits(9)),
        ("Renewal request for passaporto {x}.", "it",
            lambda: rand_letters(2) + rand_digits(7)),
        ("Boarding pass references passport {x}.", "us",
            lambda: RNG.choice("ABCDEFGHJKLMNPRSTUVWXYZ") + rand_digits(8)),
    ]
    for tmpl, _country, gen in templates:
        pii = gen()
        text = tmpl.format(x=pii)
        st = text.find(pii)
        add(text, [(st, st + len(pii), "private_passport")], "passport")


# ─── Driver licence (15 rows) ─────────────────────────────────────
def gen_driver_license() -> None:
    templates = [
        ("DL: {x} renewed last month.", "ca",
            lambda: RNG.choice(string.ascii_uppercase) + rand_digits(7)),
        ("California driver license {x} on file.", "ca",
            lambda: RNG.choice(string.ascii_uppercase) + rand_digits(7)),
        ("NY DL: {x} verified.", "ny",
            lambda: rand_digits(9)),
        ("Driver license: {x} (NY).", "ny",
            lambda: rand_digits(9)),
        ("Patente di guida: {x}, valida 2030.", "it",
            lambda: rand_letters(2) + rand_digits(7) + RNG.choice(string.ascii_uppercase)),
        ("N. patente {x} - rinnovo necessario.", "it",
            lambda: rand_letters(1) + rand_digits(7) + RNG.choice(string.ascii_uppercase)),
        ("Führerschein: {x} ausgestellt 2018.", "de",
            lambda: RNG.choice(string.ascii_uppercase) + rand_digits(9)),
        ("Permis de conduire: {x} catégorie B.", "fr",
            lambda: rand_digits(2) + rand_letters(2) + rand_digits(5)),
        ("Carnet de conducir: {x} expedido en Madrid.", "es",
            lambda: rand_digits(8) + RNG.choice(string.ascii_uppercase)),
        ("Rijbewijs: {x} verlengd.", "nl",
            lambda: rand_digits(10)),
        ("CNH: {x} válida.", "br",
            lambda: rand_digits(11)),
        ("Driver's license: {x} renewed.", "ca",
            lambda: RNG.choice(string.ascii_uppercase) + rand_digits(7)),
        ("DL# {x} suspended.", "ny",
            lambda: rand_digits(9)),
        ("Carta de condução {x} portuguesa.", "pt",
            lambda: rand_letters(2) + rand_digits(7)),
        ("Patente: {x}, scadenza 2032.", "it",
            lambda: rand_letters(2) + rand_digits(7) + RNG.choice(string.ascii_uppercase)),
    ]
    for tmpl, _country, gen in templates:
        pii = gen()
        text = tmpl.format(x=pii)
        st = text.find(pii)
        add(text, [(st, st + len(pii), "private_driver_license")], "driver-license")


# ─── Vehicle id — VIN + plates (15 rows) ──────────────────────────
def gen_vehicle_id() -> None:
    # VIN — 6 rows with computed valid check digit.
    for _ in range(6):
        vin = make_vin()
        tmpl = RNG.choice([
            "Vehicle VIN {x} owner contact required.",
            "Title transfer for VIN: {x}, mileage 42,318.",
            "Insurance claim references {x}.",
            "Recall affects VIN {x}, ETA 6 weeks.",
        ])
        text = tmpl.format(x=vin)
        st = text.find(vin)
        add(text, [(st, st + len(vin), "private_vehicle_id")], "vehicle-vin")
    # License plates.
    plate_templates = [
        ("Auto targata {x} parcheggiata.", lambda: f"{rand_letters(2)} {rand_digits(3)} {rand_letters(2)}"),
        ("Plaque {x} flashée hier.", lambda: f"{rand_letters(2)}-{rand_digits(3)}-{rand_letters(2)}"),
        ("Kennzeichen {x} gemeldet.", lambda: f"{rand_letters(2)}-{rand_letters(2)} {rand_digits(3)}"),
        ("UK plate {x} on CCTV.", lambda: f"{rand_letters(2)}{rand_digits(2)} {rand_letters(3)}"),
        ("Matrícula {x} registrada.", lambda: f"{rand_digits(4)} {''.join(RNG.choices('BCDFGHJKLMNPRSTVWXYZ', k=3))}"),
        ("License plate: {x} pulled over.", lambda: f"{rand_letters(3)}{rand_digits(4)}"),
        ("Targa {x} per il furgone aziendale.", lambda: f"{rand_letters(2)} {rand_digits(3)} {rand_letters(2)}"),
        ("French registration {x} confirmed.", lambda: f"{rand_letters(2)}-{rand_digits(3)}-{rand_letters(2)}"),
        ("Plate number: {x}, reported stolen.", lambda: f"{rand_letters(3)}{rand_digits(4)}"),
    ]
    for tmpl, gen in plate_templates:
        plate = gen()
        text = tmpl.format(x=plate)
        st = text.find(plate)
        add(text, [(st, st + len(plate), "private_vehicle_id")], "vehicle-plate")


# ─── Geolocation (15 rows) ────────────────────────────────────────
def gen_geolocation() -> None:
    cities = [
        (41.9028, 12.4964, "Rome"),
        (48.8566, 2.3522, "Paris"),
        (51.5074, -0.1278, "London"),
        (40.4168, -3.7038, "Madrid"),
        (52.5200, 13.4050, "Berlin"),
        (-33.8688, 151.2093, "Sydney"),
        (35.6762, 139.6503, "Tokyo"),
        (37.7749, -122.4194, "San Francisco"),
        (-23.5505, -46.6333, "São Paulo"),
        (28.6139, 77.2090, "New Delhi"),
    ]
    # Decimal pairs — 6 rows.
    for _ in range(6):
        lat, lon, city = RNG.choice(cities)
        pair = f"{lat}, {lon}"
        tmpl = RNG.choice([
            "GPS sample: {x} near downtown.",
            "Last seen at {x}, possibly heading north.",
            "Coords logged: {x}.",
        ])
        text = tmpl.format(x=pair)
        st = text.find(pair)
        add(text, [(st, st + len(pair), "private_geolocation")], "geo-decimal")
    # DMS — 4 rows.
    for _ in range(4):
        deg = RNG.randint(1, 89)
        minute = RNG.randint(0, 59)
        sec = RNG.randint(0, 59)
        hem = RNG.choice("NSEW")
        dms = f"{deg}°{minute:02d}'{sec:02d}\"{hem}"
        tmpl = RNG.choice([
            "Marker at {x} on the trail map.",
            "Survey point {x}, accuracy +/-2m.",
        ])
        text = tmpl.format(x=dms)
        st = text.find(dms)
        add(text, [(st, st + len(dms), "private_geolocation")], "geo-dms")
    # Context-anchored single coord — 5 rows.
    for _ in range(5):
        lat, _lon, _city = RNG.choice(cities)
        pii = f"{lat}"
        tmpl = RNG.choice([
            "Telemetry record latitude: {x}, sensor#3 active.",
            "Server reports lat: {x}, long missing.",
            "GPS: {x} altitude not captured.",
            "Coordinate logged - latitude: {x}.",
            "Field report - gps: {x}, see followup.",
        ])
        text = tmpl.format(x=pii)
        st = text.find(pii)
        add(text, [(st, st + len(pii), "private_geolocation")], "geo-context")


# ─── IP addresses (15 rows) ───────────────────────────────────────
def gen_private_ip() -> None:
    v4 = [
        "192.168.1.1", "10.0.0.42", "172.16.5.200", "203.0.113.7", "198.51.100.15",
        "8.8.8.8", "1.1.1.1", "127.0.0.1", "169.254.10.20", "100.64.0.5",
    ]
    v6 = [
        "2001:db8::1", "fe80::1ff:fe23:4567:890a", "::ffff:192.0.2.1",
        "2001:0db8:85a3:0000:0000:8a2e:0370:7334", "fd12:3456:789a::1",
    ]
    for ip in v4:
        tmpl = RNG.choice([
            "Connection from {x} blocked by WAF.",
            "Failed login from {x} at 14:02.",
            "Origin IP {x} - flagged.",
        ])
        text = tmpl.format(x=ip)
        st = text.find(ip)
        add(text, [(st, st + len(ip), "private_ip")], "ip-v4")
    for ip in v6:
        tmpl = RNG.choice([
            "IPv6 source {x} routed via gateway.",
            "Client {x} requested resource.",
        ])
        text = tmpl.format(x=ip)
        st = text.find(ip)
        add(text, [(st, st + len(ip), "private_ip")], "ip-v6")


# ─── MAC addresses (15 rows) ─────────────────────────────────────
def gen_private_mac() -> None:
    def rand_mac(sep: str) -> str:
        octets = ["{:02x}".format(RNG.randint(0, 255)) for _ in range(6)]
        # ensure not all zeros / not broadcast (handled by validator anyway)
        if all(o == "00" for o in octets):
            octets[0] = "01"
        return sep.join(octets)

    for _ in range(10):
        mac = rand_mac(":")
        tmpl = RNG.choice([
            "DHCP lease for {x} expired.",
            "Device MAC {x} - new on network.",
            "Layer-2 sniff observed {x}.",
            "Switch port 12: {x} bridged.",
        ])
        text = tmpl.format(x=mac)
        st = text.find(mac)
        add(text, [(st, st + len(mac), "private_mac")], "mac-colon")
    for _ in range(5):
        mac = rand_mac("-")
        tmpl = RNG.choice([
            "Windows reports adapter {x} disconnected.",
            "ipconfig output: physical address {x}.",
        ])
        text = tmpl.format(x=mac)
        st = text.find(mac)
        add(text, [(st, st + len(mac), "private_mac")], "mac-dash")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()

    gen_passport()
    gen_driver_license()
    gen_vehicle_id()
    gen_geolocation()
    gen_private_ip()
    gen_private_mac()

    by_cat = Counter(s["category"] for s in SAMPLES)
    by_lbl = Counter(span["label"] for s in SAMPLES for span in s["spans"])
    print(f"generated {len(SAMPLES)} samples across {len(by_cat)} categories")
    for cat, n in by_cat.most_common():
        print(f"  {cat}: {n}")
    print("by label:")
    for lbl, n in by_lbl.most_common():
        print(f"  {lbl}: {n}")

    mode = "a" if args.append else "w"
    with args.out.open(mode) as f:
        for i, s in enumerate(SAMPLES):
            row = {
                "id": f"v03-{s['category']}-{i:04d}",
                "subset": "v03_coverage",
                "source": "fair",
                "category": s["category"],
                "text": s["text"],
                "spans": s["spans"],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{'appended to' if args.append else 'wrote'} {args.out}")


if __name__ == "__main__":
    main()
