# SPDX-License-Identifier: Apache-2.0
"""Fetch the open value lists into lists/ (run once; the output is frozen with the benchmark).

Sources (details and licences in lists/SOURCES.md):
- Wikidata (CC0): given names and family names by language of the name (P407),
  street names by country (P31 = street, P17 = country).
- GeoNames postal code dumps (CC BY 4.0): postal code + place + region, per country.

Raw responses are cached under cache/lists/. The build itself (gen/build.py) reads only lists/.
"""
from __future__ import annotations

import csv
import io
import random
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, LISTS, derive_seed  # noqa: E402

UA = "ab1-benchmark-builder/0.1 (research dataset build script)"
WDQS = "https://query.wikidata.org/sparql"
RAW = CACHE / "lists"

LANG_QID = {"en": "Q1860", "it": "Q652", "de": "Q188", "fr": "Q150", "es": "Q1321"}
COUNTRY_QID = {"us": "Q30", "gb": "Q145", "it": "Q38", "de": "Q183", "fr": "Q142", "es": "Q29"}
COUNTRY_LANG = {"us": "en", "gb": "en", "it": "it", "de": "de", "fr": "fr", "es": "es"}
MAX_STREETS = 3000
ORG_WORDS = re.compile(r"GmbH|\bAG\b|\bKG\b|\bSE\b|Bank|Sparkasse|Versicherung|Universit|Klinik|Radio|Rundfunk|Verlag|Amt\b|Postfach|"
                       r"Management|Beratung|Zement|Stadtwerke|Deutsche|Finanz|Gesellschaft|Verband|Bundes|Landes|Kasse|Werke|Zentrum|"
                       r"Zentrale|Ministerium|Behörde|Service|Holding|Versand|Großkunde|&|\.|\d", re.I)
GEONAMES = {"us": "US.zip", "gb": "GB_full.csv.zip", "it": "IT.zip", "de": "DE.zip", "fr": "FR.zip", "es": "ES.zip"}

NAME_RE = re.compile(r"^[A-ZÀ-Þ][a-zß-ÿ']+(?:[ -][A-ZÀ-Þ][a-zß-ÿ']+)?$")
STREET_PREFIX = {
    "it": re.compile(r"^(Via|Viale|Corso|Piazza|Largo|Vicolo|Piazzale|Strada|Lungomare|Borgo) ", re.I),
    "de": re.compile(r"(straße|strasse|weg|allee|platz|gasse|ring|damm|ufer|chaussee|steig|markt)$|^(Am|An der|Im|Auf der) ", re.I),
    "fr": re.compile(r"^(Rue|Avenue|Boulevard|Place|Chemin|Allée|Impasse|Quai|Cours|Route) ", re.I),
    "es": re.compile(r"^(Calle|Avenida|Paseo|Plaza|Carrer|Camino|Ronda|Travesía|Glorieta|Rambla) ", re.I),
    "us": re.compile(r" (Street|Avenue|Road|Boulevard|Drive|Lane|Way|Place|Court|Parkway)$"),
    "gb": re.compile(r" (Street|Road|Lane|Avenue|Way|Place|Gardens|Terrace|Crescent|Close|Row|Hill|Square)$"),
}


def sparql(query: str, cache_name: str) -> list[dict[str, str]]:
    path = RAW / cache_name
    if not path.exists():
        url = WDQS + "?" + urllib.parse.urlencode({"query": query})
        req = urllib.request.Request(url, headers={"Accept": "text/csv", "User-Agent": UA})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    body = resp.read().decode("utf-8")
                break
            except Exception as exc:  # retried, then re-raised
                if attempt == 1:
                    raise
                print(f"retry {cache_name}: {exc}", file=sys.stderr)
                time.sleep(10)
        path.write_text(body, encoding="utf-8")
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


def fetch_names(lang: str) -> None:
    q = LANG_QID[lang]
    specs = {
        "given_male": ("Q12308941", 700),
        "given_female": ("Q11879590", 700),
        "surnames": ("Q101352", 1500),
    }
    out_dir = LISTS / "names" / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    for fname, (cls, limit) in specs.items():
        rows = None
        for min_sl in (0, 2, 3, 5, 8):
            query = (
                "SELECT ?item ?label ?sl WHERE { ?item wdt:P31 wd:%s; wdt:P407 wd:%s; wikibase:sitelinks ?sl. "
                "FILTER(?sl >= %d) ?item rdfs:label ?label. FILTER(LANG(?label) IN (\"%s\", \"mul\")) }"
                % (cls, q, min_sl, lang)
            )
            name = f"wd_{fname}_{lang}_sl{min_sl}.csv"
            try:
                rows = sparql(query, name)
                if not all(r.get("sl", "").isdigit() and r.get("item", "").startswith("http") for r in rows):
                    raise ValueError("truncated response")
                break
            except Exception as exc:  # timeout or truncated body: retry with a stricter sitelink floor
                print(f"{name}: {exc}; trying a higher sitelink floor", file=sys.stderr)
                (RAW / name).unlink(missing_ok=True)
                rows = None
        if rows is None:
            raise RuntimeError(f"could not fetch {fname} {lang}")
        # rank locally (server-side ORDER BY times out on large classes): most sitelinks first
        rows.sort(key=lambda r: (-int(r["sl"]), int(r["item"].rsplit("Q", 1)[1]), r["label"]))
        seen: set[str] = set()
        names = []
        for r in rows:
            label = r["label"].strip()
            if not NAME_RE.match(label) or len(label) < 3 or len(label) > 18 or label in seen:
                continue
            seen.add(label)
            names.append(label)
            if len(names) >= limit:
                break
        (out_dir / f"{fname}.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
        print(lang, fname, len(names))


def fetch_streets(country: str) -> None:
    lang = COUNTRY_LANG[country]
    query = (
        "SELECT ?s ?label WHERE { ?s wdt:P31 wd:Q79007; wdt:P17 wd:%s; rdfs:label ?label. "
        "FILTER(LANG(?label) = \"%s\") }" % (COUNTRY_QID[country], lang)
    )
    rows = sparql(query, f"wd_streets_{country}.csv")
    seen: set[str] = set()
    streets = []
    for r in rows:
        label = re.sub(r"\s*\(.*?\)\s*", "", r["label"]).strip()
        label = label.split(",")[0].strip()
        if not label or label in seen or len(label) > 40 or any(ch.isdigit() for ch in label):
            continue
        if not STREET_PREFIX[country].search(label):
            continue
        label = label[0].upper() + label[1:]
        if label in seen:
            continue
        seen.add(label)
        streets.append(label)
    streets.sort()
    if len(streets) > MAX_STREETS:
        rng = random.Random(derive_seed("street-sample", country))
        streets = sorted(rng.sample(streets, MAX_STREETS))
    out = LISTS / "streets"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{country}.txt").write_text("\n".join(streets) + "\n", encoding="utf-8")
    print("streets", country, len(streets))


def fetch_postal(country: str) -> None:
    fname = GEONAMES[country]
    raw = RAW / fname
    if not raw.exists():
        req = urllib.request.Request("https://download.geonames.org/export/zip/" + fname, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw.write_bytes(resp.read())
    with zipfile.ZipFile(raw) as zf:
        inner = [n for n in zf.namelist() if n.endswith(".txt") or n.endswith(".csv")]
        inner = [n for n in inner if not n.lower().startswith("readme")]
        text = zf.read(inner[0]).decode("utf-8")
    rows = []
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 7 or not f[1] or not f[2]:
            continue
        if country in ("de", "fr", "it", "es") and not f[1].isdigit():
            continue  # CEDEX and other business codes
        if country == "de" and (ORG_WORDS.search(f[2]) or len(f[2].split()) > 3 or not f[5] or not f[4].isalpha()):
            continue  # Großkunden postal codes name a company, not a place
        if country == "es" and ("(" in f[2] or "," in f[2]):
            continue
        # columns: country, postal code, place, admin1 name, admin1 code, admin2 name, admin2 code
        rows.append([f[1], f[2], f[3], f[4], f[5], f[6]])
    rng = random.Random(derive_seed("postal-sample", country))
    rows.sort()
    sample = sorted(rng.sample(rows, min(2500, len(rows))))
    out = LISTS / "postal"
    out.mkdir(parents=True, exist_ok=True)
    with (out / f"{country}.tsv").open("w", encoding="utf-8") as fh:
        fh.write("#postal_code\tplace\tadmin1_name\tadmin1_code\tadmin2_name\tadmin2_code\n")
        for r in sample:
            fh.write("\t".join(c.replace("\t", " ") for c in r) + "\n")
    print("postal", country, len(sample), "of", len(rows))


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for lang in LANG_QID:
        fetch_names(lang)
    for country in COUNTRY_QID:
        fetch_streets(country)
    for country in GEONAMES:
        fetch_postal(country)


if __name__ == "__main__":
    main()
