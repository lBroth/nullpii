#!/usr/bin/env python3
"""MEDDOCAN dataset loader — VALIDATED labels via finiteautomata/meddocan.

Source: HuggingFace `finiteautomata/meddocan` (CC BY 4.0).
Has explicit BIO labels with canonical MEDDOCAN names (45-entry
ClassLabel: O + B-/I- × 22 entity types). Mapping below is validated
against the published MEDDOCAN guidelines at
https://temu.bsc.es/meddocan/index.php/datasets/.

Note: this dataset ships pre-tokenized (token list + BIO ner_tags) but
NO original `text` field. We reconstruct text by joining tokens with
single spaces; the resulting char offsets are self-consistent with the
token list but do not match the original document offsets.

Splits: train (4731), validation (2469), test (2374).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "eval" / "src"))

from nullpii_eval.datasets import Sample, Span  # noqa: E402

# Canonical MEDDOCAN entity types → nullpii 8-class schema.
# Reviewed against the BSC MEDDOCAN documentation (TeMU 2019).
_MEDDOCAN_ENTITY_TO_NULLPII: dict[str, str | None] = {
    # Direct identifiers — unambiguous
    "NOMBRE_SUJETO_ASISTENCIA":      "private_person",
    "NOMBRE_PERSONAL_SANITARIO":     "private_person",
    "CORREO_ELECTRONICO":            "private_email",
    "NUMERO_TELEFONO":               "private_phone",
    "NUMERO_FAX":                    "private_phone",
    # Account / health-system identifiers
    "ID_SUJETO_ASISTENCIA":          "account_number",   # patient ID (NHC)
    "ID_ASEGURAMIENTO":              "account_number",   # insurance / NASS
    "ID_TITULACION_PERSONAL_SANITARIO": "account_number",
    "ID_EMPLEO_PERSONAL_SANITARIO":  "account_number",
    "ID_CONTACTO_ASISTENCIAL":       "account_number",
    # Address / location
    "CALLE":                         "private_address",
    "TERRITORIO":                    "private_address",
    "PAIS":                          "private_address",
    "HOSPITAL":                      "private_address",
    "CENTRO_SALUD":                  "private_address",
    "INSTITUCION":                   "private_address",
    # Date / age
    "FECHAS":                        "private_date",
    "EDAD_SUJETO_ASISTENCIA":        "private_date",     # age — quasi-PII per GDPR
    # Skipped — not in nullpii 8-class schema or ambiguous
    "SEXO_SUJETO_ASISTENCIA":        None,  # gender — demographic-only
    "FAMILIARES_SUJETO_ASISTENCIA":  None,  # relationship words
    "PROFESION":                     None,  # profession — context-dependent PII
    "OTROS_SUJETO_ASISTENCIA":       None,  # catch-all "other"
}


def _reconstruct_text(tokens: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """Join tokens with single spaces. Return (text, [(start, end), ...])
    where each tuple is the char-offset span of token[i]."""
    text_parts = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    for i, tok in enumerate(tokens):
        if i > 0:
            text_parts.append(" ")
            pos += 1
        offsets.append((pos, pos + len(tok)))
        text_parts.append(tok)
        pos += len(tok)
    return "".join(text_parts), offsets


def _bio_tags_to_spans(
    tokens: list[str],
    tag_names: list[str],
    offsets: list[tuple[int, int]],
) -> list[Span]:
    """Walk BIO-labelled tokens, group into contiguous spans, map to
    nullpii labels via `_MEDDOCAN_ENTITY_TO_NULLPII`. Skipped entity
    types yield no span."""
    spans: list[Span] = []
    cur_label: str | None = None
    cur_start: int | None = None
    cur_end: int = 0
    for tok, tag, (s, e) in zip(tokens, tag_names, offsets):
        if tag == "O" or tag is None:
            if cur_label is not None and cur_start is not None:
                spans.append(Span(cur_label, cur_start, cur_end))
                cur_label = None
                cur_start = None
            continue
        bio_prefix = tag[:2]  # 'B-' or 'I-'
        entity_type = tag[2:]
        nullpii_label = _MEDDOCAN_ENTITY_TO_NULLPII.get(entity_type)
        if nullpii_label is None:
            if cur_label is not None and cur_start is not None:
                spans.append(Span(cur_label, cur_start, cur_end))
                cur_label = None
                cur_start = None
            continue
        if bio_prefix == "B-" or nullpii_label != cur_label:
            if cur_label is not None and cur_start is not None:
                spans.append(Span(cur_label, cur_start, cur_end))
            cur_label = nullpii_label
            cur_start = s
            cur_end = e
        else:  # I- continuation of same nullpii label
            cur_end = e
    if cur_label is not None and cur_start is not None:
        spans.append(Span(cur_label, cur_start, cur_end))
    return spans


def load_meddocan_train(max_samples: int | None = None) -> list[Sample]:
    """Load the MEDDOCAN train split with BIO tags resolved to nullpii
    8-class schema."""
    from datasets import load_dataset
    ds = load_dataset("finiteautomata/meddocan", split="train")
    label_names = ds.features["ner_tags"].feature.names

    out: list[Sample] = []
    for ex in ds:
        tokens = list(ex["tokens"])
        if not tokens:
            continue
        tag_ids = list(ex["ner_tags"])
        tag_names = [label_names[t] for t in tag_ids]
        text, offsets = _reconstruct_text(tokens)
        spans = _bio_tags_to_spans(tokens, tag_names, offsets)
        out.append(Sample(text, tuple(spans)))
        if max_samples and len(out) >= max_samples:
            break
    return out


if __name__ == "__main__":
    samples = load_meddocan_train(max_samples=10)
    for i, s in enumerate(samples):
        if not s.spans:
            continue
        print(f"=== sample {i} ===")
        print(f"text: {s.text[:300]}")
        print(f"spans:")
        for sp in s.spans:
            print(f"  [{sp.label}] {s.text[sp.start:sp.end]!r}")
        print()
