#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and freeze the R3 report-set files (scripts/r3/CRITERIA.md).

Downloads every R3 source at its pinned revision, applies the label maps
below and writes one frozen JSONL per dataset key into `results/r3/`
(gitignored), plus `results/r3/MANIFEST.json`. One row per document:

    {"text", "spans": [{"start", "end", "label"}], "ignore": [[start, end], ...],
     "language", "cluster"}            (+ "genre", "subgenre" for redactionbench)

Offsets are Python string indices into `text`. The JSONL is written with
ASCII escapes, so no character inside a text can split a line.

Label maps. Every native label of every source maps to a gold label, to
IGNORE (an ignore region: neither true nor false positive, for every tool)
or to DROP (neither gold nor ignore: the core-regime rule, so masking it is
charged like any non-gold text). The maps were written from each source's
documentation before its gold was opened; a native label missing from its
map raises.

Gold-span rules, applied per document in this order:
1. A span whose offsets fall outside the text, or whose `text[start:end]`
   differs from the entity string the source records with it, is not gold:
   it becomes an ignore region (clipped to the text) and is counted as
   `misaligned`. An entity the source gives no offsets at all (REDACT) is
   not gold either: every exact occurrence of its string in the text becomes
   an ignore region, counted as `no_offsets`. A source that records no entity
   string gets a bounds check only, and an out-of-range span there raises.
2. REDACT spans with `disclosed == false` become ignore regions.
3. Same-label gold spans that share at least one character are merged into
   their union (touching spans stay separate mentions).
4. A gold span that lies inside a gold span of another label is dropped (the
   outer entity is the unit to mask, e.g. a name inside an e-mail address);
   identical extents keep the alphabetically first label. Partially
   overlapping spans of different labels are both kept. The char metric is
   label-agnostic, so rules 3-4 change per-label counts only.
5. Ignore regions are merged into their union. Gold characters inside one
   still count (`char_metrics.doc_counts`).

PIILO (Kaggle `lburleigh/piilo-dataset` v2) is gated in CRITERIA.md but not
built here: TODO add it once the owner's Kaggle access is in place.

Run: python scripts/r3/build_r3.py   (from packages/eval, any cwd works)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import HfApi, get_hf_file_metadata, hf_hub_download, hf_hub_url

EVAL_DIR = Path(__file__).resolve().parents[2]
OUT_DIR = EVAL_DIR / "results" / "r3"
SOURCES_DIR = OUT_DIR / "sources"
MANIFEST = "MANIFEST.json"
REDACT_TERMS_COPY = "redact-LICENSE"

# ─── Map targets ─────────────────────────────────────────────────
IGNORE = "<ignore>"
DROP = "<drop>"

CORE_LABELS = frozenset({
    "private_person", "private_email", "private_phone", "private_address",
    "private_date", "private_url", "private_ip", "private_mac",
    "account_number", "secret", "private_passport", "private_driver_license",
    "private_vehicle_id", "private_geolocation",
})
# Gold labels of the reported-only sets whose gold is not typed by core
# category; the char metric is label-agnostic, per-label recall shows them.
UNTYPED = "untyped"
CONTACT = "contact"

# ─── redact: guneeshv/REDACT-PII-Benchmark (data/schema.md, 51 types) ──
# Core types as CRITERIA.md lists them; the other 29 are ignore regions.
REDACT_LABELS: dict[str, str] = {
    "Full_Name": "private_person",
    "First_Given_Name": "private_person",
    "Last_Family_Name": "private_person",
    "Preferred_Name": "private_person",
    "Personal_Email_Address": "private_email",
    "Work_Email_Address": "private_email",
    "Telephone_Numbers_Personal": "private_phone",
    "Telephone_Numbers_Work": "private_phone",
    "Address_Personal": "private_address",
    "Address_Work": "private_address",
    "City": "private_address",
    "State": "private_address",
    "Date_Time": "private_date",
    "Date_of_Birth": "private_date",
    "Static_IP_Address": "private_ip",
    "Credit_Card_Numbers": "account_number",
    "National_Identification_Number": "account_number",
    "Tax_Reference_Number": "account_number",
    "Password": "secret",
    "Passport_Number": "private_passport",
    "Driving_License_Number": "private_driver_license",
    "Geolocation_Data": "private_geolocation",
    # Non-core: ignore regions (CRITERIA: organisation, age, gender and every
    # other non-core type).
    **dict.fromkeys((
        "Account_Statements", "Age", "Allergy_Information",
        "Building_Badge_Card_Number", "Business_Title", "Citizenship_Status",
        "Compensation_and_Salary", "Country_of_Residence", "Crime",
        "Customer_Reference_Number", "Disciplinary_Action",
        "Emergency_Contact_Details", "Employee_ID_Number", "Gender", "Location",
        "Marital_Status", "Medical_Information", "Nationality", "Org_Name",
        "PEP_Status", "Performance_Assessment", "Place_of_Birth",
        "Political_Party", "Professional_Background", "Religion",
        "Sex_Orientation", "Sickness_Day_Records", "Social_Media_Identifiers",
        "Trade_Union_Membership",
    ), IGNORE),
}

# ─── tonic-human: TonicAI/Privacy-Bench v2.5, human_annotations ──
# The README's ten labels. LOCATION_ADDRESS is street-level only in v2.5, so
# city, state and ZIP are not gold (CRITERIA states it with every figure).
TONIC_LABELS: dict[str, str] = {
    "NAME_GIVEN": "private_person",
    "NAME_FAMILY": "private_person",
    "EMAIL_ADDRESS": "private_email",
    "PHONE_NUMBER": "private_phone",
    "LOCATION_ADDRESS": "private_address",
    "ACCOUNT_NUMBER": "account_number",
    "URL": "private_url",
    "USERNAME": IGNORE,
    "EMPLOYEE_ID": IGNORE,
    "ORGANIZATION": IGNORE,
}

# ─── eu-clinical (a): Greek clinical de-id benchmark ─────────────
# Keyed by the arbitrated gold's `category`; categories and their contents
# from the Zenodo record's README, scoring/build_gold_standard.py (CATMAP,
# ADD_FINE) and generation/ master prompt's category table.
GREEK_LABELS: dict[str, str] = {
    # patient, next-of-kin and clinician names (greek_patient_name, greek_clinician)
    "name": "private_person",
    # dates of birth and every other date, prose month-year included (dob, date)
    "date": "private_date",
    # any address: patient home and hospital letterhead, street, town, postcode
    "address": "private_address",
    # every phone and fax number (greek_phone)
    "phone": "private_phone",
    # ΑΜΚΑ (social security number) and hospital record number (amka, gr_id)
    "id": "account_number",
    # hospital and private-clinic names; the benchmark also files hospital
    # websites (fine `url`) under this category: CRITERIA makes it ignore
    "hospital": IGNORE,
}
# `other` holds the benchmark's `email` fine category (CATMAP email→other).
GREEK_OTHER = "other"
GREEK_OTHER_EMAIL_FINE = "email"
GREEK_OTHER_EMAIL = "private_email"
# An `other` span of any other fine category has no core type: ignore region.
GREEK_OTHER_REST = IGNORE

# ─── eu-clinical (b): GraSCCo_PHI (Zenodo 11502329) ──────────────
# The INCEpTION tag set (layer json) and the annotation guideline
# (_Annoguide____GeMTeX___DeID.pdf, sections 4.1-4.8).
GRASCCO_NO_KIND = "<no kind>"
GRASCCO_LABELS: dict[str, str] = {
    "NAME_PATIENT": "private_person",    # patient or relative, first and last name
    "NAME_RELATIVE": "private_person",   # the patient's relatives
    "NAME_DOCTOR": "private_person",     # doctors and other medical staff
    "NAME_EXT": "private_person",        # persons named with authorities, insurers
    "NAME_OTHER": "private_person",      # any other person's name (4.1: names of persons)
    "NAME_TITLE": IGNORE,                # academic titles (Prof. Dr.), annotated apart from the name
    "NAME_USERNAME": IGNORE,             # usernames, secretary initials: no core type (tonic USERNAME too)
    "DATE": "private_date",              # every date, birth and death included
    "AGE": IGNORE,                       # out of core: C3 ignore region, as in redact and mama
    "PROFESSION": IGNORE,                # out of core: C3 ignore region, as REDACT's Business_Title
    "LOCATION_STREET": "private_address",  # street name and house number
    "LOCATION_CITY": "private_address",    # city (REDACT City is core too)
    "LOCATION_ZIP": "private_address",     # postcode
    "LOCATION_STATE": "private_address",   # state or Bundesland (REDACT State is core too)
    "LOCATION_OTHER": "private_address",   # 4.4: other addresses, e.g. P.O. boxes
    "LOCATION_COUNTRY": IGNORE,            # a country is not an address (REDACT Country_of_Residence is ignore)
    "LOCATION_HOSPITAL": IGNORE,           # hospital: CRITERIA ignore region
    "LOCATION_ORGANIZATION": IGNORE,       # organisation: CRITERIA ignore region
    "ID": "account_number",              # patient, case, insurance, IBAN, room/ward numbers, study ids
    "CONTACT_PHONE": "private_phone",
    "CONTACT_FAX": "private_phone",      # a fax number is a phone number
    "CONTACT_EMAIL": "private_email",
    "CONTACT_URL": "private_url",
    "OTHER": IGNORE,                     # 4.8: protected passages with no other category: no core type
    # A PHI span the curators left without a kind (found by the structure
    # check, before any count): marked for de-identification but untyped, so
    # no core type, as OTHER.
    GRASCCO_NO_KIND: IGNORE,
}

# ─── redactionbench: A10Networks/RedactionBench (README) ─────────
REDACTIONBENCH_LABELS: dict[str, str] = {
    "mandatory": UNTYPED,   # must redact; untyped, so a dedicated label
    "contextual": IGNORE,   # may redact without penalty
}

# ─── mama-deid-val: mamahealth/mama-deid-dataset (LABELLING.md) ──
MAMA_LABELS: dict[str, str] = {
    "PERSON": "private_person",              # patient, relative, any non-clinical person
    "CLINICIAN": "private_person",           # named clinician, initials included
    "ADDRESS": "private_address",            # street-level address, postcode, coordinates
    "RESIDENCE_LOCALITY": "private_address", # town where a person lives, works, travels
    # Phone, fax, email or social handle in one untyped label: LABELLING.md
    # records no subtype per span and does not say it is phone only, so it
    # stays gold under a dedicated label (not private_phone).
    "CONTACT": CONTACT,
    "DOB": "private_date",
    "CLINICAL_DATE": "private_date",         # owner map; includes relative points in time
    "ID": "account_number",                  # every identifier kind, IP/MAC/password included
    "URL": "private_url",
    "ORG": IGNORE,                           # non-healthcare organisation
    "NRP": IGNORE,                           # nationality, religion, orientation...
    "AGE": IGNORE,                           # owner map for this set
    # Kept labels (not masked by the dataset's policy):
    "CARE_INSTITUTION": IGNORE,              # hospital or clinic name: hospital is ignore (CRITERIA)
    "CARE_LOCALITY": IGNORE,                 # care town or a care place's address: kept by policy, address-shaped
    "RESIDENCE_COUNTRY": IGNORE,             # a country, as GraSCCo LOCATION_COUNTRY
    "CLINICAL_INTERVENTION": DROP,           # drugs, procedures: clinical content, never PII
    "CLINICAL_STATE": DROP,                  # conditions, findings, lab values: never PII
    "CLINICAL_DURATION": DROP,               # clinical intervals: never PII
}

# ─── Pinned sources ──────────────────────────────────────────────
CC_BY_4 = "CC BY 4.0"

REDACT_REPO = "guneeshv/REDACT-PII-Benchmark"
REDACT_REVISION = "1d7fef611cbaad42ba19666e7d7238ed45b264dd"
REDACT_FILE = "pii_benchmark_sample1000.json"
REDACT_TERMS = "LICENSE"
# "EU language or English", read per language, not per regional variant.
REDACT_LANGUAGES: dict[str, str] = {
    "CS": "cs", "DA": "da", "DE": "de", "EN": "en", "ES": "es", "FI": "fi",
    "FR": "fr", "FR_CA": "fr", "HU": "hu", "IT": "it", "NL": "nl",
    "PT_BR": "pt", "PT_EU": "pt", "SV": "sv",
}

TONIC_REPO = "TonicAI/Privacy-Bench"
TONIC_TAG = "v2.5"
TONIC_TAG_REF = "a9f3e392088bbfee269e78a1d93dc9086e75e4eb"   # the tag's ref (CRITERIA `a9f3e39`)
TONIC_REVISION = "a79d9e80c5ee68f5dd79da8452e5eb1e1ba97a1e"  # the commit the tag resolves to
# The six human-annotated sets, in the README's order.
TONIC_SETS = (
    "megan_donovan_eli_lilly", "morgan_morgan_stanley", "daniel_lincoln_financial_group",
    "isabella_chipotle", "nora_caterpillar", "renee_tyson_foods",
)
TONIC_LANGUAGE = "en"

GREEK_REPO = "prorris/greek-deid-benchmark"
GREEK_REVISION = "dd82ef67dd4d647c58a2dbba342c87203d65a13f"
GREEK_CORPUS = "data/deid_corpus_gemini500.jsonl"
GREEK_GOLD = "annotations/gold_standard.json"
GREEK_LICENCE_FILE = "LICENSE"
GREEK_ZENODO_RECORD = "22824895"
GREEK_ZENODO_FILE = "zenodo_greek-deid-benchmark-1.0.0_1ca4f18.zip"
GREEK_ZENODO_ROOT = "greek-deid-benchmark-1.0.0/"
# HF mirror path -> path inside the Zenodo archive (record of reference).
GREEK_MIRRORED = {
    GREEK_CORPUS: "corpus/deid_corpus_gemini500.jsonl",
    GREEK_GOLD: "annotations/gold_standard.json",
}
GREEK_LANGUAGE = "el"
GREEK_NOTES = 500

GRASCCO_ZENODO_RECORD = "11502329"
GRASCCO_ZIP = "grascco_phi_annotation_json.zip"
GRASCCO_GUIDELINE = "_Annoguide____GeMTeX___DeID.pdf"
GRASCCO_LAYER = "layer_inception-gemtex-deid-base_project-grascco.json"
GRASCCO_LANGUAGE = "de"
GRASCCO_PHI_TYPE = "webanno.custom.PHI"
GRASCCO_SOFA_TYPE = "uima.cas.Sofa"
GRASCCO_VIEW = "_InitialView"

REDACTIONBENCH_REPO = "A10Networks/RedactionBench"
REDACTIONBENCH_REVISION = "1af44a65c4cb6f12ec62ffb55d75b7f30da82fb1"
REDACTIONBENCH_FILE = "data/test-00000-of-00001.parquet"
REDACTIONBENCH_LANGUAGE = "en"

MAMA_REPO = "mamahealth/mama-deid-dataset"
MAMA_REVISION = "2277eb88cb6946bc2d4aa6a26cda85f01529d1b9"
MAMA_FILE = "validation.jsonl"
MAMA_POLICY_FILE = "LABELLING.md"
# The row records its language only through a language-named source file
# (`<shape>-vl-<iso>#<n>`); every other row has none.
MAMA_LANGUAGE_ID = re.compile(r"^[a-z]+-vl-([a-z]{2})#")
# Turns of one conversation (`...#3.1`, `...#3.2`) form one cluster.
MAMA_TURN_SUFFIX = re.compile(r"\.\d+$")

ZENODO_API = "https://zenodo.org/api/records/{record}"
HTTP_TIMEOUT_S = 120
HF_DATASET = "dataset"


# ─── Data shapes ─────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class NativeSpan:
    # None where the source gives the entity no offsets (REDACT, unaligned).
    start: int | None
    end: int | None
    label: str
    # The entity string the source records with the span; None where the
    # source records none (then only bounds are checked).
    recorded: str | None = None
    # REDACT `disclosed == false`.
    undisclosed: bool = False


@dataclass(slots=True)
class RawDoc:
    text: str
    language: str | None
    cluster: str
    spans: list[NativeSpan]
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Stats:
    native: Counter = field(default_factory=Counter)        # (native label, outcome) -> spans
    events: Counter = field(default_factory=Counter)        # rule outcomes


@dataclass(frozen=True, slots=True)
class Built:
    docs: list[RawDoc]
    label_map: dict[str, str]
    sources: list[dict]


# ─── Small helpers ───────────────────────────────────────────────
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _file_digest(path: Path, algo: str) -> str:
    return hashlib.new(algo, path.read_bytes()).hexdigest()


def _http_get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310 (fixed https host)
        return resp.read()


def _hf_file(repo: str, filename: str, revision: str) -> Path:
    return Path(hf_hub_download(repo, filename, repo_type=HF_DATASET, revision=revision))


def _hf_files(repo: str, revision: str, filenames: Iterable[str]) -> dict[str, Path]:
    return {f: _hf_file(repo, f, revision) for f in filenames}


def _hf_source(repo: str, revision: str, paths: dict[str, Path], licence: str, terms: str, **more) -> dict:
    return {
        "hf_repo": repo, "revision": revision, "licence": licence, "terms_file": terms,
        "files": {name: _sha256_file(p) for name, p in sorted(paths.items())}, **more,
    }


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ─── Zenodo ──────────────────────────────────────────────────────
def _zenodo_record(record: str) -> dict:
    return json.loads(_http_get(ZENODO_API.format(record=record)))


def _zenodo_file(meta: dict, key: str) -> Path:
    """Download one file of a Zenodo record into the sources cache, verified
    against the checksum the record publishes."""
    entry = next((f for f in meta["files"] if f["key"] == key), None)
    if entry is None:
        raise KeyError(f"zenodo {meta['id']}: no file {key!r}")
    algo, expected = entry["checksum"].split(":", 1)
    path = SOURCES_DIR / f"zenodo-{meta['id']}" / key
    if not path.exists() or _file_digest(path, algo) != expected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_http_get(entry["links"]["self"]))
    actual = _file_digest(path, algo)
    if actual != expected:
        raise ValueError(f"zenodo {meta['id']}/{key}: {algo} {actual} is not the published {expected}")
    return path


def _zenodo_source(meta: dict, paths: dict[str, Path], terms: str) -> dict:
    licence = meta["metadata"]["license"]["id"]
    if licence != "cc-by-4.0":
        raise ValueError(f"zenodo {meta['id']}: licence {licence!r} is not the CC BY 4.0 CRITERIA recorded")
    return {
        "zenodo_record": str(meta["id"]), "doi": meta["doi"],
        "version": meta["metadata"].get("version"), "licence": CC_BY_4, "terms_file": terms,
        "files": {name: _sha256_file(p) for name, p in sorted(paths.items())},
    }


# ─── Span resolution (module docstring, rules 1-5) ───────────────
def _union(intervals: Iterable[tuple[int, int]], *, touching: bool) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if out and (start < out[-1][1] or (touching and start == out[-1][1])):
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _target(label_map: dict[str, str], label: str) -> str:
    if label not in label_map:
        raise KeyError(f"unknown native label {label!r}")
    return label_map[label]


def _has_offsets(span: NativeSpan) -> bool:
    return span.start is not None and span.end is not None


def _occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    index = text.find(needle) if needle else -1
    while index >= 0:
        out.append((index, index + len(needle)))
        index = text.find(needle, index + len(needle))
    return out


def _ignore_regions(text: str, span: NativeSpan, stats: Stats) -> list[tuple[int, int]]:
    """Where a non-gold span is ignored: its offsets clipped to the text or,
    for an entity without offsets, every exact occurrence of its string."""
    if not _has_offsets(span):
        found = _occurrences(text, span.recorded or "")
        stats.events["no_offsets_occurrences_ignored"] += len(found)
        return found
    start, end = max(0, span.start), min(len(text), span.end)
    if start >= end:
        stats.events["misaligned_empty_after_clip"] += 1
        return []
    return [(start, end)]


def _aligned(text: str, span: NativeSpan) -> bool:
    if not _has_offsets(span):
        if span.recorded is None:
            raise ValueError("a span with neither offsets nor an entity string")
        return False
    in_range = 0 <= span.start < span.end <= len(text)
    if span.recorded is None:
        if not in_range:
            raise ValueError(f"span [{span.start}, {span.end}) out of range for a text of {len(text)} chars")
        return True
    return in_range and text[span.start:span.end] == span.recorded


def _classify(doc: RawDoc, label_map: dict[str, str], stats: Stats) -> tuple[list[tuple[int, int, str]], list[tuple[int, int]]]:
    """Rules 1-2: each native span becomes gold, an ignore region or nothing."""
    gold: list[tuple[int, int, str]] = []
    ignore: list[tuple[int, int]] = []
    for span in doc.spans:
        target = _target(label_map, span.label)
        if target == DROP:
            stats.native[(span.label, "drop")] += 1
            continue
        aligned = _aligned(doc.text, span)
        outcome = "ignore" if target == IGNORE else "gold"
        if not aligned:
            kind = "misaligned" if _has_offsets(span) else "no_offsets"
            stats.events[f"{kind}_{outcome}"] += 1
            outcome = "ignore"
        elif span.undisclosed:
            stats.events[f"undisclosed_{outcome}"] += 1
            outcome = "ignore"
        stats.native[(span.label, outcome)] += 1
        if outcome == "gold":
            gold.append((span.start, span.end, target))
            continue
        ignore.extend(_ignore_regions(doc.text, span, stats))
    return gold, ignore


def _merge_same_label(gold: list[tuple[int, int, str]], stats: Stats) -> list[tuple[int, int, str]]:
    """Rule 3."""
    out: list[tuple[int, int, str]] = []
    for label in sorted({g[2] for g in gold}):
        own = [(s, e) for s, e, lab in gold if lab == label]
        merged = _union(own, touching=False)
        stats.events["same_label_merged_away"] += len(own) - len(merged)
        out.extend((s, e, label) for s, e in merged)
    return sorted(out)


def _contained_in_other(span: tuple[int, int, str], gold: list[tuple[int, int, str]]) -> bool:
    start, end, label = span
    for other in gold:
        o_start, o_end, o_label = other
        if o_label == label or not (o_start <= start and end <= o_end):
            continue
        if (o_start, o_end) != (start, end) or o_label < label:
            return True
    return False


def _partial_overlaps(gold: list[tuple[int, int, str]]) -> int:
    count = 0
    for i, (s1, e1, l1) in enumerate(gold):
        for s2, e2, l2 in gold[i + 1:]:
            if l1 != l2 and s1 < e2 and s2 < e1 and not (s1 <= s2 and e2 <= e1) and not (s2 <= s1 and e1 <= e2):
                count += 1
    return count


def _resolve_cross_label(gold: list[tuple[int, int, str]], stats: Stats) -> list[tuple[int, int, str]]:
    """Rule 4."""
    kept = [g for g in gold if not _contained_in_other(g, gold)]
    stats.events["nested_cross_label_dropped"] += len(gold) - len(kept)
    stats.events["partial_cross_label_overlaps"] += _partial_overlaps(kept)
    return kept


def _row(doc: RawDoc, label_map: dict[str, str], stats: Stats) -> dict:
    gold, ignore = _classify(doc, label_map, stats)
    gold = _resolve_cross_label(_merge_same_label(gold, stats), stats)
    row = {
        "text": doc.text,
        "spans": [{"start": s, "end": e, "label": lab} for s, e, lab in gold],
        "ignore": [[s, e] for s, e in _union(ignore, touching=True)],
        "language": doc.language,
        "cluster": doc.cluster,
    }
    row.update(doc.extra)
    return row


def _check_map(label_map: dict[str, str], extra_gold: frozenset[str] = frozenset()) -> None:
    allowed = CORE_LABELS | extra_gold | {IGNORE, DROP}
    bad = sorted({t for t in label_map.values() if t not in allowed})
    if bad:
        raise ValueError(f"label map targets outside the core labels: {bad}")


# ─── Source loaders ──────────────────────────────────────────────
def _redact_span(entity: dict) -> NativeSpan:
    disclosed = entity["disclosed"]
    if not isinstance(disclosed, bool):
        raise TypeError(f"REDACT `disclosed` is {type(disclosed).__name__}, not bool")
    return NativeSpan(_optional_int(entity["start"]), _optional_int(entity["end"]), entity["entity_type"],
                      recorded=entity["entity_string"], undisclosed=not disclosed)


def _optional_int(value: int | None) -> int | None:
    return None if value is None else int(value)


def build_redact() -> Built:
    paths = _hf_files(REDACT_REPO, REDACT_REVISION, (REDACT_FILE, REDACT_TERMS))
    records = json.loads(paths[REDACT_FILE].read_text(encoding="utf-8"))
    docs = [
        RawDoc(
            text=rec["text"],
            language=REDACT_LANGUAGES[rec["axes"]["language"]],
            # record_id is the generation configuration: records sharing it
            # share every axis, so they form one cluster.
            cluster=str(rec["record_id"]),
            spans=[_redact_span(e) for e in rec["entities"]],
        )
        for rec in records
        if rec["axes"]["language"] in REDACT_LANGUAGES
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paths[REDACT_TERMS], OUT_DIR / REDACT_TERMS_COPY)
    source = _hf_source(REDACT_REPO, REDACT_REVISION, paths, "REDACT Dataset Terms v1.0", REDACT_TERMS,
                        terms_copy=REDACT_TERMS_COPY, split="locked 1,000-record detector split")
    return Built(docs, REDACT_LABELS, [source])


def _check_tonic_tag() -> None:
    refs = HfApi().list_repo_refs(TONIC_REPO, repo_type=HF_DATASET)
    tag = next((t for t in refs.tags if t.name == TONIC_TAG), None)
    if tag is None or tag.target_commit != TONIC_TAG_REF:
        raise ValueError(f"{TONIC_REPO} tag {TONIC_TAG} no longer points at {TONIC_TAG_REF}")
    url = hf_hub_url(TONIC_REPO, "README.md", repo_type=HF_DATASET, revision=TONIC_TAG)
    commit = get_hf_file_metadata(url).commit_hash
    if commit != TONIC_REVISION:
        raise ValueError(f"{TONIC_REPO} tag {TONIC_TAG} resolves to {commit}, not {TONIC_REVISION}")


def _tonic_docs(set_name: str, path: Path) -> list[RawDoc]:
    return [
        RawDoc(
            text=row["text"],
            language=TONIC_LANGUAGE,
            # Document pages share their document's row id: one cluster.
            cluster=f"{set_name}:{row['meta']['row_id']}",
            spans=[NativeSpan(int(s["start"]), int(s["end"]), s["label"], recorded=s["text"])
                   for s in row["ground_truth_spans"]],
        )
        for row in _read_jsonl(path)
    ]


def build_tonic() -> Built:
    _check_tonic_tag()
    files = [f"human_annotations/{name}{suffix}.jsonl" for name in TONIC_SETS for suffix in ("", "_documents")]
    paths = _hf_files(TONIC_REPO, TONIC_REVISION, ["README.md", *files])
    docs = [doc for name in TONIC_SETS for suffix in ("", "_documents")
            for doc in _tonic_docs(name, paths[f"human_annotations/{name}{suffix}.jsonl"])]
    source = _hf_source(TONIC_REPO, TONIC_REVISION, paths, CC_BY_4, "README.md (dataset card)",
                        tag=TONIC_TAG, tag_ref=TONIC_TAG_REF)
    return Built(docs, TONIC_LABELS, [source])


def _greek_label(span: dict) -> str:
    category = span["category"]
    if category != GREEK_OTHER:
        return category
    return f"{GREEK_OTHER}/{GREEK_OTHER_EMAIL_FINE}" if span["fine"] == GREEK_OTHER_EMAIL_FINE else f"{GREEK_OTHER}/*"


def _greek_label_map() -> dict[str, str]:
    return {**GREEK_LABELS, f"{GREEK_OTHER}/{GREEK_OTHER_EMAIL_FINE}": GREEK_OTHER_EMAIL,
            f"{GREEK_OTHER}/*": GREEK_OTHER_REST}


def _check_greek_mirror(paths: dict[str, Path], zenodo_zip: Path) -> None:
    with zipfile.ZipFile(zenodo_zip) as archive:
        for hf_name, zip_name in GREEK_MIRRORED.items():
            if _sha256_bytes(archive.read(GREEK_ZENODO_ROOT + zip_name)) != _sha256_file(paths[hf_name]):
                raise ValueError(f"{GREEK_REPO}/{hf_name} differs from Zenodo {GREEK_ZENODO_RECORD}/{zip_name}")


def _greek_docs(paths: dict[str, Path]) -> list[RawDoc]:
    notes = json.loads(paths[GREEK_GOLD].read_text(encoding="utf-8"))["notes"]
    corpus = _read_jsonl(paths[GREEK_CORPUS])
    if len(corpus) != GREEK_NOTES or {r["id"] for r in corpus} != set(notes):
        raise ValueError("Greek corpus and gold standard do not hold the same 500 notes")
    return [
        RawDoc(
            text=rec["text"], language=GREEK_LANGUAGE, cluster=f"greek/{rec['id']}",
            spans=[NativeSpan(int(s["start"]), int(s["end"]), _greek_label(s), recorded=s["text"])
                   for s in notes[rec["id"]]],
        )
        for rec in corpus
    ]


def _utf16_to_index(text: str) -> Callable[[int], int]:
    """UIMA JSON CAS offsets count UTF-16 code units; map them to Python
    indices. The identity when the text has no astral characters."""
    if all(ord(ch) <= 0xFFFF for ch in text):
        return lambda offset: offset
    table: dict[int, int] = {}
    units = 0
    for index, ch in enumerate(text):
        table[units] = index
        units += 2 if ord(ch) > 0xFFFF else 1
    table[units] = len(text)

    def _convert(offset: int) -> int:
        if offset not in table:
            raise ValueError(f"UTF-16 offset {offset} splits a surrogate pair")
        return table[offset]
    return _convert


def _grascco_doc(name: str, cas: dict) -> RawDoc:
    structures = {fs["%ID"]: fs for fs in cas["%FEATURE_STRUCTURES"]}
    sofa_id = cas["%VIEWS"][GRASCCO_VIEW]["%SOFA"]
    sofa = structures[sofa_id]
    if sofa["%TYPE"] != GRASCCO_SOFA_TYPE:
        raise ValueError(f"GraSCCo {name}: view sofa is a {sofa['%TYPE']}")
    text = sofa["sofaString"]
    to_index = _utf16_to_index(text)
    phi = [fs for fs in cas["%FEATURE_STRUCTURES"] if fs.get("%TYPE") == GRASCCO_PHI_TYPE]
    if any(fs["@sofa"] != sofa_id for fs in phi):
        raise ValueError(f"GraSCCo {name}: PHI annotation on another view")
    # JSON CAS omits a feature at its default value, so a span at offset 0 has no `begin`.
    spans = [NativeSpan(to_index(fs.get("begin", 0)), to_index(fs["end"]), fs.get("kind") or GRASCCO_NO_KIND)
             for fs in sorted(phi, key=lambda fs: (fs.get("begin", 0), fs["end"], fs["%ID"]))]
    return RawDoc(text=text, language=GRASCCO_LANGUAGE, cluster=f"grascco/{name}", spans=spans)


def _grascco_docs(zip_path: Path) -> list[RawDoc]:
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(n for n in archive.namelist() if not n.endswith("/"))
        return [_grascco_doc(Path(n).name.removesuffix("_phi.json"), json.loads(archive.read(n))) for n in names]


def build_eu_clinical() -> Built:
    greek_paths = _hf_files(GREEK_REPO, GREEK_REVISION, (GREEK_CORPUS, GREEK_GOLD, GREEK_LICENCE_FILE))
    greek_meta = _zenodo_record(GREEK_ZENODO_RECORD)
    greek_zip = _zenodo_file(greek_meta, GREEK_ZENODO_FILE)
    _check_greek_mirror(greek_paths, greek_zip)
    grascco_meta = _zenodo_record(GRASCCO_ZENODO_RECORD)
    grascco_paths = {key: _zenodo_file(grascco_meta, key) for key in (GRASCCO_ZIP, GRASCCO_GUIDELINE, GRASCCO_LAYER)}
    greek_source = _hf_source(GREEK_REPO, GREEK_REVISION, greek_paths, CC_BY_4, GREEK_LICENCE_FILE,
                              record_of_reference=_zenodo_source(greek_meta, {GREEK_ZENODO_FILE: greek_zip}, "LICENSE in the archive"),
                              mirror_check="HF corpus and gold_standard.json are byte-identical to the Zenodo archive's")
    grascco_source = _zenodo_source(grascco_meta, grascco_paths, "Zenodo record licence (CC BY 4.0)")
    label_map = {**{f"el:{k}": v for k, v in _greek_label_map().items()},
                 **{f"de:{k}": v for k, v in GRASCCO_LABELS.items()}}
    docs = [_prefix_labels(d, "el") for d in _greek_docs(greek_paths)]
    docs += [_prefix_labels(d, "de") for d in _grascco_docs(grascco_paths[GRASCCO_ZIP])]
    return Built(docs, label_map, [greek_source, grascco_source])


def _prefix_labels(doc: RawDoc, prefix: str) -> RawDoc:
    """The two sources' native labels share one map; a prefix keeps them apart."""
    doc.spans = [NativeSpan(s.start, s.end, f"{prefix}:{s.label}", s.recorded, s.undisclosed) for s in doc.spans]
    return doc


def build_redactionbench() -> Built:
    paths = _hf_files(REDACTIONBENCH_REPO, REDACTIONBENCH_REVISION, ("README.md", REDACTIONBENCH_FILE))
    rows = pq.read_table(paths[REDACTIONBENCH_FILE]).to_pylist()
    docs = [
        RawDoc(
            text=row["raw_text"], language=REDACTIONBENCH_LANGUAGE, cluster=f"rb/{index}",
            spans=[NativeSpan(int(s["start"]), int(s["end"]), s["label"]) for s in row["spans"]],
            # `genre` is the slice key (CRITERIA's dev genres are these
            # categories); `subgenre` is the source's genre folder.
            extra={"genre": row["category"], "subgenre": row["genre"]},
        )
        for index, row in enumerate(rows)
    ]
    source = _hf_source(REDACTIONBENCH_REPO, REDACTIONBENCH_REVISION, paths, CC_BY_4, "README.md (dataset card)")
    return Built(docs, REDACTIONBENCH_LABELS, [source])


def _mama_language(row_id: str) -> str | None:
    match = MAMA_LANGUAGE_ID.match(row_id)
    return match.group(1) if match else None


def build_mama() -> Built:
    paths = _hf_files(MAMA_REPO, MAMA_REVISION, ("README.md", MAMA_POLICY_FILE, MAMA_FILE))
    docs = [
        RawDoc(
            text=row["text"], language=_mama_language(row["id"]),
            cluster=MAMA_TURN_SUFFIX.sub("", row["id"]),
            spans=[NativeSpan(int(s["start"]), int(s["end"]), s["label"]) for s in row["spans"]],
        )
        for row in _read_jsonl(paths[MAMA_FILE])
    ]
    source = _hf_source(MAMA_REPO, MAMA_REVISION, paths, CC_BY_4, "README.md (dataset card)",
                        split="validation", label_policy=MAMA_POLICY_FILE)
    return Built(docs, MAMA_LABELS, [source])


# ─── Freeze ──────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Key:
    name: str
    build: Callable[[], Built]
    extra_gold: frozenset[str] = frozenset()


KEYS: tuple[Key, ...] = (
    Key("redact", build_redact),
    Key("tonic-human", build_tonic),
    Key("eu-clinical", build_eu_clinical),
    Key("redactionbench", build_redactionbench, frozenset({UNTYPED})),
    Key("mama-deid-val", build_mama, frozenset({CONTACT})),
)


def _write_jsonl(path: Path, rows: list[dict]) -> str:
    data = "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in rows).encode("ascii")
    path.write_bytes(data)
    return _sha256_bytes(data)


def _union_len(intervals: Iterable[tuple[int, int]]) -> int:
    return sum(e - s for s, e in _union(intervals, touching=True))


def _label_summary(rows: list[dict]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        for s in row["spans"]:
            entry = out.setdefault(s["label"], {"spans": 0, "chars": 0})
            entry["spans"] += 1
            entry["chars"] += s["end"] - s["start"]
    return dict(sorted(out.items()))


def _native_summary(stats: Stats, label_map: dict[str, str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for (label, outcome), count in sorted(stats.native.items()):
        entry = out.setdefault(label, {"target": _render(label_map[label])})
        entry[outcome] = count
    return out


def _render(target: str) -> str:
    return {IGNORE: "ignore", DROP: "drop"}.get(target, target)


def _manifest_entry(rows: list[dict], built: Built, stats: Stats, file_name: str, digest: str) -> dict:
    gold_chars = sum(_union_len((s["start"], s["end"]) for s in r["spans"]) for r in rows)
    ignore_chars = sum(_union_len(map(tuple, r["ignore"])) for r in rows)
    return {
        "file": file_name,
        "sha256": digest,
        "rows": len(rows),
        "sources": built.sources,
        "gold_spans": sum(len(r["spans"]) for r in rows),
        "gold_chars": gold_chars,
        "gold_by_label": _label_summary(rows),
        "ignore_regions": sum(len(r["ignore"]) for r in rows),
        "ignore_chars": ignore_chars,
        "languages": dict(sorted(Counter(str(r["language"]) for r in rows).items())),
        "clusters": len({r["cluster"] for r in rows}),
        "native_labels": _native_summary(stats, built.label_map),
        "rule_events": dict(sorted(stats.events.items())),
        "label_map": {k: _render(v) for k, v in sorted(built.label_map.items())},
    }


def _check_rows(rows: list[dict]) -> None:
    for i, row in enumerate(rows):
        length = len(row["text"])
        for s in row["spans"]:
            if not 0 <= s["start"] < s["end"] <= length:
                raise ValueError(f"row {i}: gold span out of range")
        for start, end in row["ignore"]:
            if not 0 <= start < end <= length:
                raise ValueError(f"row {i}: ignore region out of range")


def freeze(key: Key) -> dict:
    built = key.build()
    _check_map(built.label_map, key.extra_gold)
    stats = Stats()
    rows = [_row(doc, built.label_map, stats) for doc in built.docs]
    _check_rows(rows)
    file_name = f"{key.name}.jsonl"
    digest = _write_jsonl(OUT_DIR / file_name, rows)
    return _manifest_entry(rows, built, stats, file_name, digest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for key in KEYS:
        entry = freeze(key)
        manifest[key.name] = entry
        print(f"[r3] {key.name}: {entry['rows']} rows, {entry['gold_spans']} gold spans, "
              f"{entry['ignore_regions']} ignore regions, sha256 {entry['sha256']}", flush=True)
    manifest["_todo"] = ["piilo: Kaggle lburleigh/piilo-dataset v2, not built (owner's Kaggle access pending)"]
    (OUT_DIR / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                                    encoding="ascii")
    print(f"[r3] manifest -> {OUT_DIR / MANIFEST}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
