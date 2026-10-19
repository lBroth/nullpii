# SPDX-License-Identifier: Apache-2.0
"""Corpus assembly: template allocation, document modes, invariant checks."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .core import GOLD_SET, Assembled, InvariantError, assemble, check_document
from .doc import Doc, Mode
from .templates import REGISTRY, Template, load_all

MIN_LEN = 300
MAX_LEN = 20_000
MAX_ATTEMPTS = 40
TEMPLATE_CAP = 0.04
MIN_TEMPLATES = 60
CLEAN_SHARE = 0.20       # documents with no gold value at all
NO_SECRET_SHARE = 0.31   # documents with gold values but no gold secret
LANG_WEIGHTS = (("en", 0.44), ("it", 0.17), ("de", 0.15), ("fr", 0.15), ("es", 0.09))


@dataclass
class BuiltDoc:
    doc_id: str
    template_id: str
    mode: str
    lang: str
    assembled: Assembled
    attempts: int
    locales: tuple
    text_langs: tuple


def build_one(tpl: Template, doc_id: str, mode: str, lang: str, seed_key: str) -> BuiltDoc:
    last_len = None
    for attempt in range(MAX_ATTEMPTS):
        rng = random.Random(f"{seed_key}:{attempt}")
        d = Doc(doc_id, tpl.tid, tpl.style, rng, mode, lang)
        d.begin()
        tpl.fn(d)
        d.end()
        a = assemble(d.frag())
        check_document(a)
        if mode == Mode.CLEAN and a.spans:
            raise InvariantError(f"{doc_id}: clean document contains gold")
        if mode != Mode.FULL and any(s["label"] == "secret" for s in a.spans):
            raise InvariantError(f"{doc_id}: no-secret document contains a gold secret")
        last_len = len(a.text)
        if MIN_LEN <= last_len <= MAX_LEN:
            return BuiltDoc(doc_id, tpl.tid, mode, lang, a, attempt + 1, tuple(sorted(d.locales_used)),
                            tuple(sorted(d.text_langs)))
    raise InvariantError(f"{doc_id} ({tpl.tid}): no attempt within length bounds (last {last_len})")


def allocate(n_docs: int, rng: random.Random) -> tuple[list[str], dict[str, Template]]:
    reg = load_all()
    tids = sorted(reg)
    if len(tids) < MIN_TEMPLATES:
        raise InvariantError(f"only {len(tids)} templates, need {MIN_TEMPLATES}")
    base, rem = divmod(n_docs, len(tids))
    extra = set(rng.sample(tids, rem))
    slots: list[str] = []
    for t in tids:
        slots += [t] * (base + (1 if t in extra else 0))
    rng.shuffle(slots)
    return slots, reg


# Templates whose substance is a set of records about people read unnaturally when
# every value is a stand-in, so they receive clean documents less often.
LOW_CLEAN_AFFINITY = 0.3
RECORD_TEMPLATES = (
    "alpr_parking_events", "audit_log_admin_actions", "clinic_appointment_bug", "csv_customer_import",
    "fleet_telematics", "gdpr_dsar_deletion", "graphql_customer_query", "hr_onboarding_accounts",
    "httpie_booking_api", "insurance_claim_parser", "iot_device_registry", "jira_refund_ticket",
    "kyc_api_integration", "mdm_device_inventory", "mysql_dump_restore", "pandas_notebook_cleaning",
    "payroll_sepa_xml", "psql_user_lookup", "readme_maintainers", "rest_client_pagination",
    "slack_incident_thread", "soap_xml_insurance", "support_email_thread", "travel_booking_pnr",
)


def assign_modes(slots: list[str], rng: random.Random) -> list[str]:
    """Exact mode counts; clean documents are drawn without replacement with
    weights (Efraimidis-Spirakis keys), the no-secret ones uniformly."""
    n_docs = len(slots)
    n_clean = round(n_docs * CLEAN_SHARE)
    n_nosec = round(n_docs * NO_SECRET_SHARE)
    keys = []
    for i, tid in enumerate(slots):
        w = LOW_CLEAN_AFFINITY if tid in RECORD_TEMPLATES else 1.0
        keys.append((rng.random() ** (1.0 / w), i))
    keys.sort(reverse=True)
    modes = [Mode.FULL] * n_docs
    for _, i in keys[:n_clean]:
        modes[i] = Mode.CLEAN
    rest = [i for _, i in keys[n_clean:]]
    rng.shuffle(rest)
    for i in rest[:n_nosec]:
        modes[i] = Mode.NO_SECRET
    return modes


def assign_langs(n_docs: int, rng: random.Random) -> list[str]:
    langs = [l for l, _ in LANG_WEIGHTS]
    weights = [w for _, w in LANG_WEIGHTS]
    return rng.choices(langs, weights=weights, k=n_docs)


def build_corpus(seed: int, n_docs: int) -> list[BuiltDoc]:
    master = random.Random(seed)
    slots, reg = allocate(n_docs, master)
    unknown = [t for t in RECORD_TEMPLATES if t not in reg]
    if unknown:
        raise InvariantError(f"unknown template ids in RECORD_TEMPLATES: {unknown}")
    modes = assign_modes(slots, master)
    langs = assign_langs(n_docs, master)
    docs = []
    for i, (tid, mode, lang) in enumerate(zip(slots, modes, langs)):
        doc_id = f"tv3-{i + 1:04d}"
        docs.append(build_one(reg[tid], doc_id, mode, lang, f"{seed}:{doc_id}:{tid}"))
    check_corpus(docs, n_docs)
    return docs


def check_corpus(docs: list[BuiltDoc], n_docs: int) -> None:
    if len(docs) != n_docs:
        raise InvariantError("document count mismatch")
    counts: dict[str, int] = {}
    for d in docs:
        counts[d.template_id] = counts.get(d.template_id, 0) + 1
        for sp in d.assembled.spans:
            if sp["label"] not in GOLD_SET:
                raise InvariantError(f"invalid label in {d.doc_id}")
        if not (MIN_LEN <= len(d.assembled.text) <= MAX_LEN):
            raise InvariantError(f"{d.doc_id} length out of bounds")
    if len(counts) < MIN_TEMPLATES:
        raise InvariantError(f"only {len(counts)} templates used")
    worst = max(counts.values())
    if worst > TEMPLATE_CAP * n_docs:
        raise InvariantError(f"template cap violated: {worst} > {TEMPLATE_CAP * n_docs}")
    no_secret = sum(1 for d in docs if not any(s["label"] == "secret" for s in d.assembled.spans))
    no_gold = sum(1 for d in docs if not d.assembled.spans)
    if no_secret < 0.40 * n_docs:
        raise InvariantError(f"only {no_secret} documents without a gold secret")
    if no_gold < 0.15 * n_docs:
        raise InvariantError(f"only {no_gold} documents without gold")
    ids = [d.doc_id for d in docs]
    if len(set(ids)) != len(ids):
        raise InvariantError("duplicate document ids")
