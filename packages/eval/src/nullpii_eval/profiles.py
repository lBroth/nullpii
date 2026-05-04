"""Per-domain detection profiles.

Each backbone has a complementary sweet spot:
  - v6 baseline (`urchade/gliner_multi_pii-v1`, ONNX, model.onnx) is
    strongest on dev-paste real text — F1 0.864 on `nullpii-bench`,
    0.625 on `oasst-dev-planted`, but only 0.609 on TAB ECHR (legal).
  - v8 multi-domain fine-tune (TAB ECHR + ai4privacy + isotonic) is
    strongest on legal / structured PII — F1 0.609 on TAB ECHR,
    0.884 on isotonic-en, but regresses dev-paste to 0.499 on
    `nullpii-bench` (-0.37 vs v6).

`PROFILES` exposes a small static map keyed by user-facing profile
name. Each entry is a configuration record consumed by the bench
harness (`packages/eval/scripts/bench_full.py`) and by the runtime
profile-routing logic. The `model` field is one of:
  - `"v6"`        — `urchade/gliner_multi_pii-v1` ONNX (dev-paste).
  - `"v8"`        — `packages/eval/results/train/gliner-v8-multidomain/final`.
  - `"ensemble"`  — both v6 and v8 fused (broadest coverage, 2x cost).

`regex_pack` is `"default"` (full ~65-pattern pack from
`adapters.DEFAULT_REGEX_PATTERNS`) or `"minimal"` (universal-only
subset from `adapters.MINIMAL_REGEX_PATTERNS`).
"""
from __future__ import annotations

from typing import TypedDict


class ProfileConfig(TypedDict):
    description: str
    model: str  # "v6" | "v8" | "ensemble"
    regex_pack: str  # "default" | "minimal"
    url_filter: bool
    drop_rfc1918: bool
    compliance_fit: str


PROFILES: dict[str, ProfileConfig] = {
    "devops": {
        "description": (
            "Dev-paste workloads (RFCs, PR reviews, code with secrets, "
            "multilingual customer support). Optimized for cloud-secret "
            "detection + general PII in real text."
        ),
        "model": "v6",  # urchade/gliner_multi_pii-v1 ONNX
        "regex_pack": "default",  # full ~65 patterns
        "url_filter": True,
        "drop_rfc1918": True,
        "compliance_fit": "GDPR developer workflow, internal-tool compliance",
    },
    "legal": {
        "description": (
            "Legal text, court rulings, contracts. Heavy PERSON / "
            "DATETIME / LOC."
        ),
        "model": "v8",  # multi-domain fine-tune
        "regex_pack": "minimal",  # only universal patterns (email, IBAN, SSN, URL)
        "url_filter": True,
        "drop_rfc1918": False,
        "compliance_fit": "GDPR legal-document anonymization, court-record redaction",
    },
    "medical-experimental": {
        "description": (
            "EXPERIMENTAL: medical-narrative pre-filter. Currently uses "
            "the v8 multi-domain backbone + minimal regex, identical to "
            "`legal`. Medical-specific recognizers (MRN, prescription "
            "IDs, insurance numbers, NPI) are NOT YET implemented. "
            "Coverage estimated at ~10/18 HIPAA Safe Harbor identifiers."
        ),
        "model": "v8",
        # TODO: add medical-specific patterns (MRN, prescription IDs,
        # insurance numbers, NPI) and validate on i2b2 + MEDDOCAN
        # before removing the `-experimental` suffix.
        "regex_pack": "minimal",
        "url_filter": True,
        "drop_rfc1918": False,
        "compliance_fit": (
            "EXPERIMENTAL ONLY — not validated for HIPAA Safe Harbor. "
            "Do NOT cite this profile as a HIPAA de-identification "
            "control. Pending: i2b2 2014 deid + MEDDOCAN benchmark "
            "validation + medical-specific recognizer pack. Use as a "
            "research-grade pre-filter with a human reviewer in the loop."
        ),
    },
    "general": {
        "description": (
            "Mixed unknown content. Conservative — runs both models in "
            "ensemble (slower)."
        ),
        "model": "ensemble",  # v6 + v8 union
        "regex_pack": "default",
        "url_filter": True,
        "drop_rfc1918": True,
        "compliance_fit": "broadest coverage, mixed-domain workload",
    },
}


# Resolved model paths — single source of truth for both profile
# routing and bench tool defs. Update these here, never inline.
V6_MODEL_ID: str = "onnx-community/gliner_multi_pii-v1"
V6_ONNX_FILE: str = "onnx/model.onnx"
V8_MODEL_DIR: str = "packages/eval/results/train/gliner-v8-multidomain/final"
