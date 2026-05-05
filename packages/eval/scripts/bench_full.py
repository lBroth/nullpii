#!/usr/bin/env python3
"""Full comparison bench: tool × dataset matrix with checkpoint resume.

Single unified bench script — replaces older quick_*/eval_ensemble
scripts. Designed for serial multi-day runs on a 4090 RunPod.

Each (tool, dataset) combination writes:
  - {checkpoint_dir}/{tool}-{dataset}.jsonl  (one prediction per line)
  - {checkpoint_dir}/{tool}-{dataset}.state  (last completed idx)

Re-running the script picks up from `.state` and skips finished
combinations entirely. Final results:
  - {out_dir}/matrix.json   per-cell F1 / wall / throughput
  - {out_dir}/matrix.csv    pivot table
  - {out_dir}/confusion.json (if --confusion) per-label TP/FP/FN

Per-dataset default caps live in `DATASET_CONFIGS` so a default run
finishes in ~1 day on 4090. Override:
  --max-per-dataset N  applies a global cap to every dataset
  --no-cap             ignores all per-dataset defaults (full)

CLI:
  --tools      comma list of {nullpii, gliner, presidio, deberta,
               piiranha, regex, ensemble}
  --backend    cpu | cuda
  --datasets   all | <comma list>  — pick a subset by key
  --confusion  emit per-label TP/FP/FN breakdown for each cell
  --pool-size N         nullpii daemon pool (default 4)
  --threads-each N      ORT thread count per daemon (default 4)
  --gliner-threshold F  default 0.8

Single-dataset run example:
  python bench_full.py --datasets bench-bundled --tools nullpii,gliner \\
      --out-dir results/single
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.adapters import (
    DEFAULT_REGEX_PATTERNS,
    MINIMAL_REGEX_PATTERNS,
    aws_comprehend_predictor,
    azure_pii_predictor,
    boundary_refined_predictor,
    deberta_pii_predictor,
    domain_routed_predictor,
    gcp_dlp_predictor,
    gliner_lora_predictor,
    gliner_nemotron_pii_predictor,
    gliner_v2_predictor,
    gliner2_predictor,
    multi_ensemble_predictor,
    never_pii_filter_predictor,
    openai_bioes_predictor,
    openai_official_predictor,
    openai_pipeline_batch_predictor,
    piiranha_predictor,
    presidio_predictor,
    scrubadub_predictor,
    url_filter_predictor,
)
from nullpii_eval.datasets import Sample, Span, load
from nullpii_eval.metrics import evaluate, macro_f1
from nullpii_eval.router import make_embedding_detector as _v10_make_embedding_detector
from nullpii_eval.router import make_xlmr_detector as _v10_make_xlmr_detector


# ─── Dataset registry ────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class DatasetSpec:
    key: str
    loader: Callable[[int | None], list[Sample]]
    default_n: int | None  # None = use full dataset by default
    # Total upstream dataset size (rows available, ignoring cap). Used
    # ONLY for display in the CSV/JSON output as `n/total`. None = size
    # not declared; display shows just `n`.
    total_n: int | None = None


def _isotonic(loc: str, row_offset: int = 0) -> Callable[[int | None], list[Sample]]:
    return lambda n: list(
        public_datasets._load_isotonic(n, lang=loc, row_offset=row_offset).samples,
    )


def _ai4privacy(offset: int = 0) -> Callable[[int | None], list[Sample]]:
    return lambda n: list(public_datasets._load_ai4privacy(n, offset=offset).samples)


def _wikiann(lang: str) -> Callable[[int | None], list[Sample]]:
    return lambda n: list(public_datasets._load_wikiann(n, lang=lang).samples)


def _load_nullpii_bench(n: int | None) -> list[Sample]:
    """Load the bundled `nullpii-bench.jsonl` dataset.

    Merges the `bundled` and `long-prompts` subsets into one set
    (264 samples total). The legacy `adversarial` subset (7 samples)
    is excluded — it tested regex behaviour only and gave perfect
    score for trivial reasons, not a meaningful comparison row.
    """
    path = Path(__file__).resolve().parent.parent / "datasets" / "nullpii-bench.jsonl"
    out: list[Sample] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["subset"] not in ("bundled", "long-prompts"):
                continue
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            out.append(Sample(row["text"], spans))
            if n and len(out) >= n:
                break
    return out


def _load_tab_echr_test(n: int | None) -> list[Sample]:
    """Load TAB (Text Anonymization Benchmark) test split — ECHR
    (European Court of Human Rights) court rulings annotated for legal
    PII. Public, CC BY 4.0, ACL 2022 (Pilán et al.). Source:
    https://github.com/NorskRegnesentral/text-anonymisation-benchmark.

    Third-party gold standard for legal-text PII detection. Label
    mapping (entity types from TAB → nullpii 8-cat schema):
      - PERSON → private_person
      - DATETIME → private_date
      - LOC → private_address
      - ORG / CODE / DEM / MISC / QUANTITY → skipped (no clean mapping)

    127 documents, ~4200 mappable spans (filtered from 7371 total).
    """
    path = Path(__file__).resolve().parent.parent / "datasets" / "tab-echr-test.jsonl"
    out: list[Sample] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            out.append(Sample(row["text"], spans))
            if n and len(out) >= n:
                break
    return out


def _load_nullpii_adversarial_textattack(n: int | None, *, subset: str | None = None) -> list[Sample]:
    """Load the third-party adversarial corpus generated via TextAttack
    (UVA-NLP, ACL 2020). Perturbations: homoglyph swap, neighboring
    character swap, random char delete/insert/substitute. Source data
    is ai4privacy 0–500 (disjoint from bench eval offset 300k+).

    Pass `subset` to filter to a single perturbation type:
      - textattack-homoglyph
      - textattack-charswap
      - textattack-chardelete
      - textattack-charinsert
      - textattack-charsub
    """
    path = Path(__file__).resolve().parent.parent / "datasets" / "nullpii-adversarial-textattack.jsonl"
    out: list[Sample] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if subset and row.get("subset") != subset:
                continue
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            out.append(Sample(row["text"], spans))
            if n and len(out) >= n:
                break
    return out


def _load_nullpii_adversarial(n: int | None, *, subset: str | None = None) -> list[Sample]:
    """Load the adversarial edge-case bench (`nullpii-adversarial.jsonl`).

    480 samples across 6 subsets: `typo_pii`, `unicode_obf`,
    `whitespace_obf`, `encoding_obf`, `decoys`, `code_pii`.

    Pass `subset` to filter to a single category.

    Decoy samples have empty `spans` — they test FP rate (model should
    NOT flag patterns that look like PII but aren't).
    """
    path = Path(__file__).resolve().parent.parent / "datasets" / "nullpii-adversarial.jsonl"
    out: list[Sample] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if subset and row.get("subset") != subset:
                continue
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            out.append(Sample(row["text"], spans))
            if n and len(out) >= n:
                break
    return out


# Dev-focused dataset suite (open licensing only).
#
#  - nullpii-bench — project-bundled (bundled + long-prompts subsets
#    merged), Apache 2.0. Adversarial subset excluded as it only
#    exercised the regex pack.
#  - dev-prompts-synth — local generator, Apache 2.0, fully synthetic
#  - enron-planted — Enron Email Corpus (FERC public-domain release)
#                    + planted PII at known offsets
#  - stackoverflow-planted — StackExchange CC-BY-SA archive
#                            + planted PII at known offsets
#
# Excluded:
#  - bigcode/bigcode-pii-dataset — gated, requires auth + acceptance
#  - bigcode/the-stack-smol — opt-out concerns; not safe-by-default
#  - ai4privacy / Isotonic / wikiann / conll / presidio-synthetic —
#    helpers in public_datasets.py kept for future use but not
#    registered here. Re-register if needed.
#
# ~50k samples total; nullpii cpu pool=8 → ~2.5h on RunPod 5090 host.
# Override with --max-per-dataset N or --no-cap.
#
# Held-out offsets: training default caps were ai4privacy=100000 and
# Isotonic prefetched 200000 train rows for the 20k-per-locale cap. To
# benchmark on data the model never saw, slice ABOVE those indices.
# ai4privacy: rows [100000:105000]. Isotonic: row_offset=200000 so the
# entire prefetch window is past the training slice.
_AI4_HELDOUT_OFFSET = 100_000
_ISOTONIC_HELDOUT_ROW_OFFSET = 200_000

DATASET_CONFIGS: list[DatasetSpec] = [
    # ─ Generalization rows (out-of-distribution, never-seen) ───────
    DatasetSpec("nullpii-bench",         _load_nullpii_bench,                                                  None, total_n=264),
    # Dropped 2026-05-04: composite `nullpii-adversarial` mixes decoys
    # (zero-PII gold) with real PII subsets — F1 ambiguous when the
    # individual subsets are already benched. Keep only the per-subset
    # rows below.
    DatasetSpec("adversarial-typo",      lambda n: _load_nullpii_adversarial(n, subset="typo_pii"),            None, total_n=80),
    DatasetSpec("adversarial-unicode",   lambda n: _load_nullpii_adversarial(n, subset="unicode_obf"),         None, total_n=80),
    DatasetSpec("adversarial-whitespace", lambda n: _load_nullpii_adversarial(n, subset="whitespace_obf"),      None, total_n=80),
    DatasetSpec("adversarial-encoding",  lambda n: _load_nullpii_adversarial(n, subset="encoding_obf"),        None, total_n=80),
    # Dropped 2026-05-04: `adversarial-decoys` has zero gold spans. F1
    # is structurally meaningless on a no-PII slice (recall undefined).
    # If FP rate matters, track separately as a precision-only row.
    DatasetSpec("adversarial-code",      lambda n: _load_nullpii_adversarial(n, subset="code_pii"),            None, total_n=80),
    DatasetSpec("adversarial-textattack", _load_nullpii_adversarial_textattack,                                None, total_n=1670),
    DatasetSpec("textattack-homoglyph",   lambda n: _load_nullpii_adversarial_textattack(n, subset="textattack-homoglyph"),  None, total_n=334),
    DatasetSpec("textattack-charswap",    lambda n: _load_nullpii_adversarial_textattack(n, subset="textattack-charswap"),   None, total_n=334),
    DatasetSpec("textattack-chardelete",  lambda n: _load_nullpii_adversarial_textattack(n, subset="textattack-chardelete"), None, total_n=334),
    DatasetSpec("textattack-charinsert",  lambda n: _load_nullpii_adversarial_textattack(n, subset="textattack-charinsert"), None, total_n=334),
    DatasetSpec("textattack-charsub",     lambda n: _load_nullpii_adversarial_textattack(n, subset="textattack-charsub"),    None, total_n=334),

    # ─ Third-party PII benches (legal / medical) ────────────────────
    DatasetSpec("tab-echr",              _load_tab_echr_test,                                                  None, total_n=127),
    DatasetSpec("lmsys-dev-planted",     lambda n: list(public_datasets._load_lmsys_dev_planted(n).samples),   5_000),
    DatasetSpec("oasst-dev-planted",     lambda n: list(public_datasets._load_oasst_dev_planted(n).samples),   5_000, total_n=15),
    DatasetSpec("enron-planted",         lambda n: list(public_datasets._load_enron_planted(n).samples),       10_000),
    DatasetSpec("stackoverflow-planted", lambda n: list(public_datasets._load_stackoverflow_planted(n).samples), 10_000),
    DatasetSpec("thestack-planted",      lambda n: list(public_datasets._load_thestack_planted(n).samples),    5_000),
    DatasetSpec("presidio-synthetic",    lambda n: list(public_datasets._load_presidio_synthetic(n).samples),  5_000, total_n=1500),
    DatasetSpec("ai4privacy-400k",       lambda n: list(public_datasets._load_ai4privacy_400k(n).samples),     5_000, total_n=400000),

    # ─ Public PII datasets (single slice, no fine-tune-vs-heldout
    #   distinction — current `nullpii` backbone is `onnx-community/
    #   gliner_multi_pii-v1`, which has not been trained on these
    #   datasets, so heldout/traindist split would be meaningless) ─
    DatasetSpec("ai4privacy-300k",           _ai4privacy(),                                                       5_000, total_n=209000),
    DatasetSpec("isotonic-en",               _isotonic("en"),                                                     5_000, total_n=209000),
    DatasetSpec("isotonic-de",               _isotonic("de"),                                                     5_000, total_n=209000),
    DatasetSpec("isotonic-fr",               _isotonic("fr"),                                                     5_000, total_n=209000),
    DatasetSpec("isotonic-it",               _isotonic("it"),                                                     5_000, total_n=209000),
    # ─ v10 held-out splits (explicit row offsets past training slice) ─
    # v10 adapters trained on ai4 rows 0-15k and isotonic rows 0-5k
    # per-lang. These specs carve from offset 100k+, well past any
    # training row, to validate v10 generalisation rather than
    # train-set memorisation. ai4 dataset size 177k → 77k available
    # past offset 100k. Isotonic dataset size 209k → ~109k past 100k.
    DatasetSpec("ai4privacy-300k-heldout-v10",   lambda n: list(public_datasets._load_ai4privacy(n, offset=_AI4_HELDOUT_OFFSET).samples), 5_000, total_n=109000),
    # External baselines (not in v10 training corpora — held-out).
    DatasetSpec("argilla-pii",                   lambda n: list(public_datasets._load_argilla_pii(n).samples),                          2_000, total_n=2096),
    DatasetSpec("nemotron-pii-test",             lambda n: list(public_datasets._load_nemotron_pii_test(n).samples),                    5_000, total_n=100000),
    DatasetSpec("isotonic-en-heldout-v10",       _isotonic("en", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET // 2),  5_000, total_n=109000),
    DatasetSpec("isotonic-de-heldout-v10",       _isotonic("de", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET // 2),  5_000, total_n=109000),
    DatasetSpec("isotonic-fr-heldout-v10",       _isotonic("fr", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET // 2),  5_000, total_n=109000),
    # Dropped 2026-05-04: `wikiann-{es,zh,ja}` are PER/LOC NER, not
    # native PII labels. Loose mapping (PER → private_person, LOC →
    # private_address) makes absolute F1 incomparable to PII-native
    # rows. CJK universally <0.16 F1 — known dead zone, not a bench
    # signal worth tracking. Helper `_wikiann` retained in case future
    # work re-introduces a stricter mapping.
]


# ─── Tool builders ───────────────────────────────────────────────
def _wrap_batch(batch_pred):
    def _single(text):
        return batch_pred([text])[0]
    return _single


def build_tools(args) -> dict[str, Callable]:
    backend = args.backend
    openai_backend = args.openai_backend or backend

    # ─── v10 LoRA per-domain adapter helper ──────────────────────────
    # Loaded internally by router-embedding / router-xlmr only. The
    # individual per-domain adapters are NOT exposed as user-facing
    # tools — release scope is the two routers.
    def _v10_adapter(
        profile: str,
        *,
        regex_pack=DEFAULT_REGEX_PATTERNS,
        drop_rfc1918: bool,
        use_expanded_prompts: bool = False,
    ):
        # AUDIT F11 — KEEP `primary`, do NOT switch to `score_ranked`.
        # The audit (2026-05-04) recommended `score_ranked` to prevent
        # CF/IBAN regex matches overlapping with model `private_person`
        # spans from being dropped. Empirically tested 2026-05-05 on
        # 9-dataset subset; `score_ranked` regressed adversarial-typo
        # 0.940 → 0.635 (−0.30), argilla-pii 0.600 → 0.572 (−0.029),
        # nullpii-bench 0.728 → 0.725 (−0.003). v10 regex pack is
        # already high-precision (BTC validated, IDN reverted, F09
        # context-anchored phones); letting ML scores override correct
        # regex matches lowered F1 net. Audit-F11 closed as
        # "investigated, recommendation rejected based on bench
        # evidence".
        return never_pii_filter_predictor(
            inner=boundary_refined_predictor(
                inner=multi_ensemble_predictor(
                    predictors=[
                        url_filter_predictor(patterns=regex_pack),
                        gliner_lora_predictor(
                            "urchade/gliner_multi_pii-v1",
                            f"packages/eval/results/train/v10/adapters/{profile}/adapter",
                            device=backend if backend == "cpu" else "cuda",
                            threshold=args.gliner_threshold,
                            normalize_input=True,
                            use_expanded_prompts=use_expanded_prompts,
                        ),
                    ],
                    strategy="primary",
                ),
            ),
            drop_rfc1918=drop_rfc1918,
        )

    def _v10_routes(*, with_enterprise: bool) -> dict[str, Callable]:
        routes = {
            "devops":    _v10_adapter("devops",               regex_pack=DEFAULT_REGEX_PATTERNS, drop_rfc1918=args.drop_rfc1918),
            "legal":     _v10_adapter("legal",                regex_pack=MINIMAL_REGEX_PATTERNS, drop_rfc1918=False),
            "medical":   _v10_adapter("medical-experimental", regex_pack=MINIMAL_REGEX_PATTERNS, drop_rfc1918=False),
            "narrative": _v10_adapter("narrative",            regex_pack=MINIMAL_REGEX_PATTERNS, drop_rfc1918=False),
        }
        if with_enterprise:
            # 5th route — Nemotron-aug-trained enterprise adapter,
            # gated at margin=0.10 in the embedding detector.
            routes["enterprise"] = _v10_adapter(
                "enterprise",
                regex_pack=DEFAULT_REGEX_PATTERNS,
                drop_rfc1918=args.drop_rfc1918,
                use_expanded_prompts=True,
            )
        return routes

    builders: dict[str, Callable[[], Callable]] = {
        # ─── nullpii v10 — TWO release-candidate routers ──────────────
        # Multilingual embedding router (default candidate). distiluse
        # sentence-transformer + 5 per-domain prototypes + cosine
        # routing with enterprise gate (margin=0.10). 4 LoRA + embedder
        # + base ≈ 430 MB.
        "nullpii-v10-router-embedding": lambda: (lambda r: domain_routed_predictor(
            detector=_v10_make_embedding_detector(
                device="cpu" if backend == "cpu" else "cuda",
            ),
            routes=r,
            fallback=r["narrative"],
        ))(_v10_routes(with_enterprise=True)),
        # xlm-roberta-base classifier router (alt candidate). 4-way
        # head over {devops, legal, medical, narrative}. Larger
        # classifier (~1.1 GB) but discriminative — separates classes
        # that share lexical surface.
        "nullpii-v10-router-xlmr": lambda: (lambda r: domain_routed_predictor(
            detector=_v10_make_xlmr_detector(
                device="cpu" if backend == "cpu" else "cuda",
            ),
            routes=r,
            fallback=r["narrative"],
        ))(_v10_routes(with_enterprise=False)),
        # ─── Bare third-party baselines (no nullpii pipeline overlay) ─
        # Strict apple-to-apple comparison rows. NONE of these wrap our
        # boundary refiner, never-PII filter, regex pack, or chunking
        # glue. Each tool runs as its upstream project intends.
        "presidio":  lambda: presidio_predictor(),
        "deberta":   lambda: _wrap_batch(deberta_pii_predictor(device=backend, batch_size=32)),
        "piiranha":  lambda: _wrap_batch(piiranha_predictor(device=backend, batch_size=32)),
        "scrubadub": lambda: scrubadub_predictor(),
        # GLiNER multi PII v1 (`urchade/gliner_multi_pii-v1`) bare HF —
        # no chunking, no regex, no boundary refine. This is the row
        # for "what does the upstream backbone do on its own". Do not
        # confuse with our former `gliner` tool, which used our own
        # chunking glue.
        "gliner-onnx-pii-fp32": lambda: gliner_v2_predictor(
            "onnx-community/gliner_multi_pii-v1",
            onnx_file="onnx/model.onnx",
            threshold=args.gliner_threshold,
        ),
        # Nvidia Nemotron-PII (`nvidia/gliner-pii`, gliner_large-v2.1
        # backbone, ~600 MB, 55+ PII categories). Bare — 37→8 label
        # remap is the only adapter glue (`gliner_nemotron_pii_predictor`).
        "nemotron-pii-raw": lambda: gliner_nemotron_pii_predictor(
            model_path="nvidia/gliner-pii",
            device=backend if backend == "cpu" else "cuda",
            threshold=0.3,
        ),
        # GLiNER2 (fastino-ai). Schema-agnostic IE model; backbone
        # `microsoft/deberta-v3-{base,large}` per variant. Predicts
        # directly on nullpii's 8-class schema (no remap). Bare — same
        # chunking-only contract as `nemotron-pii-raw` and
        # `gliner-onnx-pii-fp32`. Library: `gliner2` (Apache 2.0).
        "gliner2-large-v1": lambda: gliner2_predictor(
            model_path="fastino/gliner2-large-v1",
            device=backend if backend == "cpu" else "cuda",
            threshold=0.3,
        ),
        "gliner2-base-v1": lambda: gliner2_predictor(
            model_path="fastino/gliner2-base-v1",
            device=backend if backend == "cpu" else "cuda",
            threshold=0.3,
        ),
        "gliner2-multi-v1": lambda: gliner2_predictor(
            model_path="fastino/gliner2-multi-v1",
            device=backend if backend == "cpu" else "cuda",
            threshold=0.3,
        ),
        # ─── 2025 GLiNER-family additions (knowledgator) ──────────────
        # Bare GLiNER models loaded via the standard `gliner` library —
        # `gliner_v2_predictor` handles loading + span output cleanly.
        # All Apache 2.0. None wrap nullpii post-processing (chunking
        # only, same contract as `gliner-onnx-pii-fp32`).
        # `gliner-x-large`: MT5-large encoder (~580M), 20 langs incl.
        # CJK / Arabic / Hindi / Ukrainian. The only true-multilingual
        # GLiNER candidate — closes our documented CJK / RTL / Indic
        # blind spot.
        "gliner-x-large": lambda: gliner_v2_predictor(
            "knowledgator/gliner-x-large",
            device=backend if backend == "cpu" else "cuda",
            threshold=args.gliner_threshold,
            local_files_only=False,
        ),
        # `gliner-x-base`: MT5-base sibling, lighter for CPU bench.
        "gliner-x-base": lambda: gliner_v2_predictor(
            "knowledgator/gliner-x-base",
            device=backend if backend == "cpu" else "cuda",
            threshold=args.gliner_threshold,
            local_files_only=False,
        ),
        # `gliner-pii-large-v1.0`: PII-specialised Apache fine-tune,
        # gliner-large backbone. EN-only despite "60+ categories"
        # framing. Reported F1 83.25 on synthetic-multi-pii-ner-v1.
        "gliner-pii-large-v1": lambda: gliner_v2_predictor(
            "knowledgator/gliner-pii-large-v1.0",
            device=backend if backend == "cpu" else "cuda",
            threshold=args.gliner_threshold,
            local_files_only=False,
        ),
        # `gliner-pii-base-v1.0`: size-matched competitor to v10 base.
        "gliner-pii-base-v1": lambda: gliner_v2_predictor(
            "knowledgator/gliner-pii-base-v1.0",
            device=backend if backend == "cpu" else "cuda",
            threshold=args.gliner_threshold,
            local_files_only=False,
        ),
        # `modern-gliner-bi-large-v1.0`: ModernBERT-large + BGE bi-encoder.
        # 8k context, ~4× faster than DeBERTa per upstream claim.
        # Long-doc speed test (TAB ECHR, dev pastes).
        "modern-gliner-bi-large-v1": lambda: gliner_v2_predictor(
            "knowledgator/modern-gliner-bi-large-v1.0",
            device=backend if backend == "cpu" else "cuda",
            threshold=args.gliner_threshold,
            local_files_only=False,
        ),
        # `gliner-multi-pii-domains-v1`: E3-JSI fine-tune of
        # urchade/gliner_multi_pii-v1. Adds Slovenian / Greek / Dutch
        # to the v10 base. F1 76.36 on synthetic-multi-pii-ner-v1.
        "gliner-multi-pii-domains-v1": lambda: gliner_v2_predictor(
            "E3-JSI/gliner-multi-pii-domains-v1",
            device=backend if backend == "cpu" else "cuda",
            threshold=args.gliner_threshold,
            local_files_only=False,
        ),
        # ─── openai/privacy-filter — three usage modes ────────────────
        # `openai`: HF transformers `pipeline()` naive aggregation. The
        # majority-default usage path; misses the model card's
        # prescribed Viterbi BIOES decoder.
        "openai":          lambda: _wrap_batch(openai_pipeline_batch_predictor(device=openai_backend, batch_size=8)),
        # `openai-bioes`: Python BIOES decoder, no Viterbi. Closes most
        # of the naive-HF gap.
        "openai-bioes":    lambda: openai_bioes_predictor(device=openai_backend),
        # `openai-official`: full opf CLI Viterbi (the model-card-
        # correct invocation). Reference for the model's intended
        # quality.
        "openai-official": lambda: openai_official_predictor(device=openai_backend),
        # ─── Cloud-API baselines (paid, lazy-loaded) ──────────────────
        # Excluded from default release bench — costs $$ + lock-in.
        # Available for one-off comparisons; require credentials in env.
        "aws-comprehend": lambda: aws_comprehend_predictor(),
        "gcp-dlp":        lambda: gcp_dlp_predictor(),
        "azure-pii":      lambda: azure_pii_predictor(),
    }
    requested = [t.strip() for t in args.tools.split(",") if t.strip()]
    out: dict[str, Callable] = {}
    for t in requested:
        if t not in builders:
            raise SystemExit(f"unknown tool: {t}")
        print(f"[bench] loading {t} ({backend})…", flush=True)
        out[t] = builders[t]()
    return out


# ─── Checkpointed worker ─────────────────────────────────────────
def _checkpoint_paths(ckpt_dir: Path, tool: str, dataset: str) -> tuple[Path, Path]:
    return (
        ckpt_dir / f"{tool}-{dataset}.jsonl",
        ckpt_dir / f"{tool}-{dataset}.state",
    )


def _load_done_idx(state_path: Path) -> int:
    if not state_path.exists():
        return -1
    try:
        return int(state_path.read_text().strip())
    except ValueError:
        return -1


def _iou(a: Span, b: Span) -> float:
    inter = max(0, min(a.end, b.end) - max(a.start, b.start))
    union = (a.end - a.start) + (b.end - b.start) - inter
    return inter / union if union > 0 else 0.0


def _confusion(preds: list[list[Span]], truths: list[list[Span]],
               ) -> dict[str, dict[str, int]]:
    """Per-label TP/FP/FN at IoU≥0.5, same-label match."""
    from collections import defaultdict
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    for ps, ts in zip(preds, truths):
        truths_remaining = list(ts)
        for p in ps:
            matched = -1
            for i, t in enumerate(truths_remaining):
                if t.label == p.label and _iou(p, t) >= 0.5:
                    matched = i
                    break
            if matched >= 0:
                tp[p.label] += 1
                truths_remaining.pop(matched)
            else:
                fp[p.label] += 1
        for t in truths_remaining:
            fn[t.label] += 1
    return {
        lbl: {"tp": tp[lbl], "fp": fp[lbl], "fn": fn[lbl]}
        for lbl in set(tp) | set(fp) | set(fn)
    }


def run_combo(
    tool_name: str, predictor: Callable, dataset: DatasetSpec, samples: list[Sample],
    ckpt_dir: Path, *, want_confusion: bool,
) -> tuple[float, float, int, dict | None]:
    """Returns (f1, wall_seconds, n_processed, confusion_or_None).

    Resumes from checkpoint. Per-sample exceptions ARE NOT swallowed —
    they propagate up to the caller. The caller (main()) records the
    cell as CRASHED in the matrix and moves on to the next combo.
    """
    pred_path, state_path = _checkpoint_paths(ckpt_dir, tool_name, dataset.key)
    done_idx = _load_done_idx(state_path)

    truths = [list(s.spans) for s in samples]
    preds: list[list[Span]] = []
    if done_idx >= 0 and pred_path.exists():
        with pred_path.open(encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                preds.append([Span(s[2], int(s[0]), int(s[1])) for s in row["spans"]])
        if len(preds) > done_idx + 1:
            preds = preds[: done_idx + 1]
        elif len(preds) < done_idx + 1:
            done_idx = len(preds) - 1
    print(f"  [{tool_name}/{dataset.key}] resume idx={done_idx + 1}/{len(samples)}", flush=True)

    t0 = time.perf_counter()
    flush_every = 100
    with pred_path.open("a", encoding="utf-8") as f:
        for i in range(done_idx + 1, len(samples)):
            try:
                spans = list(predictor(samples[i].text).spans)
            except Exception as e:
                # No silent recovery — flush partial state then re-raise so
                # the (tool, dataset) cell is marked CRASHED at the outer
                # loop. Empty-spans fallback would silently corrupt F1.
                f.flush()
                state_path.write_text(str(i - 1))
                msg = f"{type(e).__name__}: {e}"
                print(f"  [{tool_name}/{dataset.key}] idx={i} FATAL {msg}", flush=True)
                raise RuntimeError(
                    f"{tool_name}/{dataset.key} failed at idx={i}: {msg}",
                ) from e
            preds.append(spans)
            f.write(json.dumps({"idx": i, "spans": [(s.start, s.end, s.label) for s in spans]}) + "\n")
            if (i + 1) % flush_every == 0:
                f.flush()
                state_path.write_text(str(i))
                pct = (i + 1) * 100 / max(1, len(samples))
                el = time.perf_counter() - t0
                rate = (i - done_idx) / max(1e-3, el)
                print(f"  [{tool_name}/{dataset.key}] {i + 1}/{len(samples)} "
                      f"({pct:.1f}%) {rate:.1f} samp/s", flush=True)
    state_path.write_text(str(len(samples) - 1))
    el = time.perf_counter() - t0
    f1 = macro_f1(evaluate(preds, truths))
    conf = _confusion(preds, truths) if want_confusion else None
    return f1, el, len(samples), conf


# ─── Main ────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools", default="nullpii,gliner,presidio,deberta,piiranha,regex,ensemble")
    parser.add_argument("--backend", default="cuda", choices=["cpu", "cuda"])
    parser.add_argument("--nullpii-backend", default="",
                        help="override backend just for nullpii (e.g. cpu when ORT MoE "
                             "kernels lack Blackwell SM_120 support). Defaults to --backend.")
    parser.add_argument("--openai-backend", default="",
                        help="override backend just for the bare openai/privacy-filter "
                             "HF pipeline (1.3B params; CPU inference is too slow). "
                             "Defaults to --backend.")
    parser.add_argument("--datasets", default="all")
    parser.add_argument("--max-per-dataset", type=int, default=0,
                        help="0 = use per-dataset defaults; >0 = cap every dataset to N")
    parser.add_argument("--no-cap", action="store_true",
                        help="ignore per-dataset default caps (full no-cap bench)")
    parser.add_argument("--confusion", action="store_true",
                        help="emit per-label TP/FP/FN to confusion.json")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--checkpoint-dir", default="")
    parser.add_argument("--pool-size", type=int, default=4)
    parser.add_argument("--threads-each", type=int, default=4)
    parser.add_argument("--gliner-threshold", type=float, default=0.5)
    parser.add_argument(
        "--drop-rfc1918", action="store_true",
        help="Enable nullpii's never_pii_filter to drop RFC1918 + link-local IPs. "
             "Off by default — those ranges can carry internal-network PII.",
    )
    parser.add_argument("--gliner-v2-pt-dir", default="",
                        help="path to fine-tuned GLiNER v2 PT checkpoint (required if "
                             "--tools includes gliner-v2-pt)")
    parser.add_argument("--gliner-v2-onnx-dir", default="",
                        help="path to ONNX export dir of v2 (required if --tools "
                             "includes gliner-v2-int4)")
    parser.add_argument("--parallel-tools", type=int, default=1,
                        help="run N tools concurrently within each dataset (1=serial). "
                             "32GB 5090 fits 4-6 ML tools simultaneously.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = Path(args.checkpoint_dir or (out_dir / "checkpoints"))
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    if args.datasets == "all":
        datasets = list(DATASET_CONFIGS)
    else:
        keep = {d.strip() for d in args.datasets.split(",")}
        datasets = [d for d in DATASET_CONFIGS if d.key in keep]
    if not datasets:
        raise SystemExit("no datasets selected")

    print(f"[bench] backend={args.backend} datasets={[d.key for d in datasets]}", flush=True)
    if args.max_per_dataset:
        print(f"[bench] global cap: {args.max_per_dataset} per dataset", flush=True)
    elif args.no_cap:
        print("[bench] no-cap: full datasets (may take days)", flush=True)
    else:
        print("[bench] using per-dataset default caps", flush=True)

    tools = build_tools(args)
    print(f"[bench] tools loaded: {list(tools.keys())}", flush=True)

    matrix: dict[str, dict[str, dict]] = {}
    matrix_path = out_dir / "matrix.json"
    if matrix_path.exists():
        matrix = json.loads(matrix_path.read_text())
    confusion_all: dict[str, dict[str, dict]] = {}
    confusion_path = out_dir / "confusion.json"
    if args.confusion and confusion_path.exists():
        confusion_all = json.loads(confusion_path.read_text())

    for ds in datasets:
        print(f"\n[bench] === DATASET {ds.key} ===", flush=True)
        if args.max_per_dataset:
            n_arg = args.max_per_dataset
        elif args.no_cap:
            n_arg = None
        else:
            n_arg = ds.default_n  # may be None for small datasets
        try:
            samples = ds.loader(n_arg)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            print(f"[bench] FAILED to load {ds.key}: {msg}", flush=True)
            # Record the failure visibly in the matrix so post-hoc
            # readers see WHY a dataset is missing, not just absence.
            matrix.setdefault(ds.key, {})["_load_error"] = msg
            matrix_path.write_text(json.dumps(matrix, indent=2))
            continue
        if not samples:
            print(f"[bench] {ds.key}: 0 samples — skipping", flush=True)
            matrix.setdefault(ds.key, {})["_load_error"] = "loader returned 0 samples"
            matrix_path.write_text(json.dumps(matrix, indent=2))
            continue
        cap_label = "full" if n_arg is None else f"cap {n_arg}"
        print(f"[bench] {ds.key}: {len(samples)} samples ({cap_label})", flush=True)

        def _record(tool_name: str, result: tuple | BaseException) -> None:
            if isinstance(result, BaseException):
                err = f"{type(result).__name__}: {result}"
                print(f"[bench] {tool_name}/{ds.key} CRASHED: {err}", flush=True)
                # Record CRASHED status in the matrix — invisible skips
                # would silently corrupt the comparison story.
                matrix.setdefault(ds.key, {})[tool_name] = {
                    "status": "CRASHED",
                    "error": err,
                    "f1": None,
                    "wall_s": 0.0,
                    "n": 0,
                    "samples_per_s": 0.0,
                }
                matrix_path.write_text(json.dumps(matrix, indent=2))
                return
            f1, el, n, conf = result
            matrix.setdefault(ds.key, {})[tool_name] = {
                "status": "OK",
                "f1": f1, "wall_s": el, "n": n,
                "total_n": ds.total_n,
                "samples_per_s": n / max(1e-3, el),
            }
            matrix_path.write_text(json.dumps(matrix, indent=2))
            if conf is not None:
                confusion_all.setdefault(ds.key, {})[tool_name] = conf
                confusion_path.write_text(json.dumps(confusion_all, indent=2))
            print(f"[bench] {tool_name}/{ds.key} F1={f1:.4f} {el:.1f}s "
                  f"({n / max(1e-3, el):.1f} samp/s)", flush=True)

        if args.parallel_tools <= 1:
            for tool_name, predictor in tools.items():
                try:
                    res = run_combo(
                        tool_name, predictor, ds, samples, ckpt_dir,
                        want_confusion=args.confusion,
                    )
                    _record(tool_name, res)
                except Exception as e:
                    _record(tool_name, e)
        else:
            print(f"[bench] running {len(tools)} tools in parallel "
                  f"(max_workers={args.parallel_tools})", flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel_tools) as ex:
                fut_to_name = {
                    ex.submit(
                        run_combo, tname, pred, ds, samples, ckpt_dir,
                        want_confusion=args.confusion,
                    ): tname
                    for tname, pred in tools.items()
                }
                for fut in concurrent.futures.as_completed(fut_to_name):
                    tname = fut_to_name[fut]
                    try:
                        _record(tname, fut.result())
                    except Exception as e:
                        _record(tname, e)

    # CSV matrix view: rows = datasets, cols = tools.
    # Extra columns `n` (samples actually benched) and `total_n` (rows
    # available in the upstream dataset) make the cap visible — readers
    # can see at a glance whether a 0.55 F1 cell is on a 5k slice of a
    # 400k dataset or the full 264-sample bench.
    def _fmt_count(x: int | None) -> str:
        if x is None:
            return ""
        if x >= 1_000_000:
            return f"{x / 1_000_000:.1f}M".replace(".0M", "M")
        if x >= 1_000:
            return f"{x / 1_000:.1f}k".replace(".0k", "k")
        return str(x)

    csv_path = out_dir / "matrix.csv"
    tool_cols = sorted({
        t for d in matrix.values() for t in d
        if not t.startswith("_")
    })
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dataset", "n", "total_n", *tool_cols])
        for ds_key in sorted(matrix):
            cells = matrix[ds_key]
            ok_cells = [c for c in cells.values() if isinstance(c, dict) and c.get("status") == "OK"]
            n_val   = ok_cells[0].get("n")       if ok_cells else None
            total_n = ok_cells[0].get("total_n") if ok_cells else None
            row = [ds_key, _fmt_count(n_val), _fmt_count(total_n)]
            for t in tool_cols:
                cell = cells.get(t)
                if not cell:
                    row.append("")
                elif cell.get("status") == "CRASHED":
                    row.append("CRASHED")
                elif cell.get("f1") is None:
                    row.append("")
                else:
                    row.append(f"{cell['f1']:.4f}")
            w.writerow(row)
    print(f"\n[bench] matrix → {matrix_path}", flush=True)
    print(f"[bench] csv    → {csv_path}", flush=True)

    # Summary: surface failures explicitly so they cannot be missed.
    failures: list[str] = []
    for ds_key, cells in matrix.items():
        if "_load_error" in cells:
            failures.append(f"  LOAD_FAIL  {ds_key}: {cells['_load_error']}")
        for tname, cell in cells.items():
            if tname.startswith("_"):
                continue
            if cell.get("status") == "CRASHED":
                failures.append(f"  CRASHED    {tname}/{ds_key}: {cell.get('error', '?')}")
    if failures:
        print(f"\n[bench] {len(failures)} CELLS WITH FAILURES:", flush=True)
        for line in failures:
            print(line, flush=True)
    else:
        print("\n[bench] no failures recorded.", flush=True)


if __name__ == "__main__":
    main()
