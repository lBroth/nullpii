#!/usr/bin/env python3
"""Full comparison bench: tool × dataset matrix with checkpoint resume.

Single bench script — replaces older quick_*/eval_ensemble
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
  --gliner-threshold F  default 0.5

Single-dataset run example:
  python bench_full.py --datasets bench-bundled --tools nullpii,gliner \\
      --out-dir results/single
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import fcntl
import functools
import hashlib
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
    ETTIN_68M,
    MINIMAL_REGEX_PATTERNS,
    LabelCut,
    OPENMED_LARGE,
    OPENMED_SMALL,
    PII_IDENTIFIER,
    _GLINER_NATIVE_LABELS,
    _GLINER_NATIVE_TO_NULLPII8,
    boundary_refined_predictor,
    deberta_pii_predictor,
    domain_routed_predictor,
    gliner_lora_predictor,
    gliner_nemotron_pii_predictor,
    gliner_v2_predictor,
    hf_token_classifier_predictor,
    multi_ensemble_predictor,
    never_pii_filter_predictor,
    nullpii_runtime_predictor,
    openai_privacy_filter_predictor,
    openmed_privacy_filter_predictor,
    piiranha_predictor,
    rizzo_pii_predictor,
    presidio_multilang_predictor,
    presidio_predictor,
    url_filter_predictor,
)
from nullpii_eval.datasets import Sample, Span
from nullpii_eval.metrics import evaluate, macro_f1
from nullpii_eval.router import make_embedding_detector as _make_embedding_detector


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


def _load_nullpii_bench(n: int | None) -> list[Sample]:
    """Load the entire `nullpii-bench.jsonl` (2361 samples: 2052 `clean` +
    219 `adversarial` + 90 `v03_coverage`).

    Single-file bench surface that covers every project-authored row:
    multilingual dev paste, long-form prompts, preprocessor regression
    slices (typo / unicode / whitespace / encoding / decoys / code-PII),
    TextAttack perturbations, and the v0.3 schema-coverage rows
    (passport / driver-license / vehicle / geolocation / ip / mac).
    Mixed character is intentional: one F1 number summarises behaviour
    across every adversarial pattern the project authors.
    """
    path = Path(__file__).resolve().parent.parent / "datasets" / "nullpii-bench.jsonl"
    out: list[Sample] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            out.append(Sample(row["text"], spans))
            if n and len(out) >= n:
                break
    return out


def _load_presidio_synthetic_static(n: int | None) -> list[Sample]:
    """Load the frozen presidio-synthetic gold set from datasets/.

    Generated once with PresidioSentenceFaker(random_seed=2026) and saved
    as a static JSONL so F1 is reproducible across presidio-evaluator
    versions. Regenerate with:
      python -c "from nullpii_eval.public_datasets import _load_presidio_synthetic; ..."
    """
    path = Path(__file__).resolve().parent.parent / "datasets" / "presidio-synthetic.jsonl"
    return _load_charspan_jsonl(path, n)


def _load_charspan_jsonl(path: Path, n: int | None, *, language: str | None = None) -> list[Sample]:
    """Load `{text, spans:[{label,start,end}]}` JSONL → list[Sample]."""
    out: list[Sample] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            out.append(Sample(row["text"], spans, language))
            if n and len(out) >= n:
                break
    return out


def _load_tab_echr_test(n: int | None) -> list[Sample]:
    """Load TAB (Text Anonymization Benchmark) test split — ECHR
    (European Court of Human Rights) court rulings annotated for legal
    PII. Public, CC BY 4.0, ACL 2022 (Pilán et al.). Source:
    https://github.com/NorskRegnesentral/text-anonymisation-benchmark.

    Third-party gold standard for legal-text PII detection. Label
    mapping (entity types from TAB → nullpii 12-cat schema):
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


# Held-out offsets: training default caps were ai4privacy=100000 and
# Isotonic prefetched 200000 train rows for the 20k-per-locale cap. To
# benchmark on data the model never saw, slice ABOVE those indices.
# ai4privacy: rows [100000:105000]. Isotonic: row_offset=200000 so the
# entire prefetch window is past the training slice.
_AI4_HELDOUT_OFFSET = 100_000
_ISOTONIC_HELDOUT_ROW_OFFSET = 200_000

# ─ A/B loop report set (packages/eval/scripts/ab/PROTOCOL.md) ─────
# Read only at checkpoints to test the stop criterion, never to choose
# between variants. Isotonic rows from 100_000 are read by no other spec
# and by no training corpus. ai4privacy-300k is grouped by language, so
# its report slice strides across the whole split, skipping the two
# slices other specs read, to cover every language rather than one.
_REPORT_ISOTONIC_ROW_OFFSET = 100_000
_REPORT_ISOTONIC_N = 1_000
_REPORT_AI4_N = 2_000
_REPORT_AI4_EXCLUDED = ((0, 5_000), (_AI4_HELDOUT_OFFSET, _AI4_HELDOUT_OFFSET + 5_000))


# Claude-Code-traces report set, built by scripts/ab/traces_gen.py into
# the gitignored results tree (its carriers are third-party files that
# are read locally, not redistributed).
_TRACES_REPORT = Path(__file__).resolve().parent.parent / "results" / "ab-loop" / "traces-report.jsonl"


_TRACES_TUNING = _TRACES_REPORT.with_name("traces-tuning.jsonl")


def _load_traces(path: Path, n: int | None) -> list[Sample]:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: run scripts/ab/traces_gen.py first")
    return _load_charspan_jsonl(path, n, language="en")


def _load_claude_code_traces(n: int | None) -> list[Sample]:
    return _load_traces(_TRACES_REPORT, n)


def _load_claude_code_traces_tuning(n: int | None) -> list[Sample]:
    return _load_traces(_TRACES_TUNING, n)


# ─ Gated report set R2 (PROTOCOL rule change 9) ─────────────────
# Each file is frozen by SHA-256 before any tool runs on it; a changed
# file fails loud instead of being scored. traces-v2 comes from
# scripts/r2/traces_v2_gen.py (default seed); the PIIMB file is the
# `sentences` test split of piimb/pii-masking-benchmark (CC-BY-NC-4.0,
# evaluation only, never redistributed).
_RESULTS = Path(__file__).resolve().parent.parent / "results"
_TRACES_V2 = _RESULTS / "r2" / "traces-v2.jsonl"
_TRACES_V2_SHA256 = "3a741e9a58e3446f0742296f26d5cee7df0bd8e3a59a188140ccc1739313951f"
_PIIMB_SENTENCES = _RESULTS / "ab-loop" / "piimb" / "test_sentences.jsonl"
_PIIMB_SENTENCES_SHA256 = "5ff46f3a80316318794f94596fa374060d70f2f32a85909f958cbabc70bae41f"


def _frozen_rows(path: Path, sha256: str) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise ValueError(f"{path}: SHA-256 {digest} is not the frozen {sha256}")
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


@functools.cache
def _piimb_rows() -> tuple[dict, ...]:
    return tuple(_frozen_rows(_PIIMB_SENTENCES, _PIIMB_SENTENCES_SHA256))


def _piimb(task: str) -> Callable[[int | None], list[Sample]]:
    def _load(n: int | None) -> list[Sample]:
        samples = public_datasets.load_piimb_task(list(_piimb_rows()), task)
        return samples[:n] if n else samples
    return _load


def _load_traces_v2(n: int | None) -> list[Sample]:
    rows = _frozen_rows(_TRACES_V2, _TRACES_V2_SHA256)
    samples = [Sample(r["text"], tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in r["spans"])) for r in rows]
    return samples[:n] if n else samples


def _traces_v2_clusters(n: int) -> list[str]:
    """The template skeleton of each traces-v2 document: rule change 9
    resamples this set by template cluster, not by document."""
    return [r["template"] for r in _frozen_rows(_TRACES_V2, _TRACES_V2_SHA256)[:n]]


# Datasets resampled by cluster in `char_metrics.py`: key -> cluster id per document.
DATASET_CLUSTERS: dict[str, Callable[[int], list[str]]] = {"traces-v2": _traces_v2_clusters}


def _ai4privacy_report(n: int | None) -> list[Sample]:
    every = list(public_datasets._load_ai4privacy(None).samples)
    allowed = [i for i in range(len(every)) if not any(a <= i < b for a, b in _REPORT_AI4_EXCLUDED)]
    count = n or _REPORT_AI4_N
    stride = len(allowed) / count
    return [every[allowed[int(k * stride)]] for k in range(count)]

DATASET_CONFIGS: list[DatasetSpec] = [
    # ─ Project-authored bench (one file, all adversarial / preprocessor /
    #   TextAttack subsets aggregated to a single F1 number) ─────────
    DatasetSpec("nullpii-bench",         _load_nullpii_bench,                                                  None, total_n=2361),

    # ─ Third-party PII benches ────────────────────────────────────
    DatasetSpec("tab-echr",              _load_tab_echr_test,                                                  None, total_n=127),
    DatasetSpec("presidio-synthetic",    _load_presidio_synthetic_static,                                      5_000, total_n=5000),
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
    # ─ held-out splits (explicit row offsets past training slice) ─
    # adapters trained on ai4 rows 0-15k and isotonic rows 0-5k
    # per-lang. These specs carve from offset 100k+, well past any
    # training row, to validate generalisation rather than
    # train-set memorisation. ai4 dataset size 177k → 77k available
    # past offset 100k. Isotonic dataset size 209k → ~109k past 100k.
    DatasetSpec("ai4privacy-300k-heldout",   lambda n: list(public_datasets._load_ai4privacy(n, offset=_AI4_HELDOUT_OFFSET).samples), 5_000, total_n=109000),
    # External baselines (not in training corpora — held-out).
    DatasetSpec("argilla-pii",                   lambda n: list(public_datasets._load_argilla_pii(n).samples),                          2_000, total_n=2096),
    DatasetSpec("nemotron-pii-test",             lambda n: list(public_datasets._load_nemotron_pii_test(n).samples),                    5_000, total_n=100000),
    # Vendor-authored Italian legal corpus — the reverse-direction arena.
    # NOT blind for rizzo-pii (same author, same generator family, and
    # template_id values recur across its own train/validation splits).
    DatasetSpec("rizzo-clean-val",               lambda n: list(public_datasets._load_rizzo_clean_val(n).samples),                      5_000, total_n=29297),
    DatasetSpec("isotonic-en-heldout",       _isotonic("en", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET),  5_000, total_n=9000),
    DatasetSpec("isotonic-de-heldout",       _isotonic("de", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET),  5_000, total_n=9000),
    DatasetSpec("isotonic-fr-heldout",       _isotonic("fr", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET),  5_000, total_n=9000),
    DatasetSpec("isotonic-it-heldout",       _isotonic("it", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET),  5_000, total_n=9000),
    # ─ A/B loop report set — see _REPORT_* above ─────────────────
    DatasetSpec("isotonic-en-report",        _isotonic("en", row_offset=_REPORT_ISOTONIC_ROW_OFFSET),   _REPORT_ISOTONIC_N, total_n=_REPORT_ISOTONIC_N),
    DatasetSpec("isotonic-de-report",        _isotonic("de", row_offset=_REPORT_ISOTONIC_ROW_OFFSET),   _REPORT_ISOTONIC_N, total_n=_REPORT_ISOTONIC_N),
    DatasetSpec("isotonic-fr-report",        _isotonic("fr", row_offset=_REPORT_ISOTONIC_ROW_OFFSET),   _REPORT_ISOTONIC_N, total_n=_REPORT_ISOTONIC_N),
    DatasetSpec("isotonic-it-report",        _isotonic("it", row_offset=_REPORT_ISOTONIC_ROW_OFFSET),   _REPORT_ISOTONIC_N, total_n=_REPORT_ISOTONIC_N),
    DatasetSpec("ai4privacy-300k-report",    _ai4privacy_report,                                         _REPORT_AI4_N, total_n=_REPORT_AI4_N),
    DatasetSpec("claude-code-traces",        _load_claude_code_traces,                                   None, total_n=440),
    # Tuning twin (seed 777, carrier files disjoint from the report set).
    DatasetSpec("claude-code-traces-tuning", _load_claude_code_traces_tuning,                            None, total_n=440),
    # ─ Gated report set R2 (rule change 9) — see _TRACES_V2 above ──
    DatasetSpec("piimb-mapa-eur-lex",        _piimb("mapa-eur-lex"),                                     None, total_n=12_200),
    DatasetSpec("piimb-privy",               _piimb("privy"),                                            None, total_n=5_363),
    DatasetSpec("piimb-gretel",              _piimb("gretel"),                                           None, total_n=19_601),
    DatasetSpec("traces-v2",                 _load_traces_v2,                                            None, total_n=600),
]


# ─── Tool builders ───────────────────────────────────────────────
# Tools come in two flavours: single-sample (`predictor(text) -> ToolResult`)
# and batch (`predictor(list[str]) -> list[ToolResult]`). Batch predictors
# are tagged so `run_combo` knows to chunk samples and feed real batches,
# which is the difference between 2 samp/s and 80+ samp/s on the 5090
# for transformer tools like deberta / piiranha.
def _mark_batch(batch_pred):
    batch_pred.is_batch = True  # type: ignore[attr-defined]
    return batch_pred


def _wrap_batch(batch_pred):
    """Adapt a batch predictor to a single-sample callable. Used by
    tools whose downstream pipeline expects `pred(text)`; transformer
    tools prefer `_mark_batch` instead."""
    def _single(text):
        return batch_pred([text])[0]
    return _single



def _required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} must be set for this tool")
    return value

# GPU batch cap for tools whose windows reach 2048 tokens (see below).
_LONG_WINDOW_BATCH = 8


def build_tools(args) -> dict[str, Callable]:
    backend = args.backend
    # Inner GPU batch for transformer tools. Override via env when
    # running with high `--parallel-tools` so activation memory fits;
    # 32 is the default that worked at parallel-2 on 5090, 8 lets
    # parallel-4 share the same 32 GB VRAM.
    global _BATCH
    _BATCH = int(os.environ.get("NULLPII_BENCH_BATCH", "32"))

    # ─── LoRA per-domain adapter helper ──────────────────────────
    # Loaded internally by router-embedding only. The
    # individual per-domain adapters are NOT exposed as user-facing
    # tools — release scope is the two routers.
    def _adapter(
        profile: str,
        *,
        regex_pack=DEFAULT_REGEX_PATTERNS,
        drop_rfc1918: bool,
        use_expanded_prompts: bool = False,
    ):
        # KEEP `primary`, do NOT switch to `score_ranked`.
        # The audit (2026-05-04) recommended `score_ranked` to prevent
        # CF/IBAN regex matches overlapping with model `private_person`
        # spans from being dropped. Empirically tested 2026-05-05 on
        # 9-dataset subset; `score_ranked` regressed adversarial-typo
        # 0.940 → 0.635 (−0.30), argilla-pii 0.600 → 0.572 (−0.029),
        # nullpii-bench 0.728 → 0.725 (−0.003). regex pack is
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
                            f"packages/eval/results/train/adapters/{profile}/adapter",
                            device=backend,
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

    def _routes(*, with_enterprise: bool) -> dict[str, Callable]:
        routes = {
            "devops":    _adapter("devops",               regex_pack=DEFAULT_REGEX_PATTERNS, drop_rfc1918=args.drop_rfc1918),
            "legal":     _adapter("legal",                regex_pack=MINIMAL_REGEX_PATTERNS, drop_rfc1918=False),
            "medical":   _adapter("medical", regex_pack=MINIMAL_REGEX_PATTERNS, drop_rfc1918=False),
            "narrative": _adapter("narrative",            regex_pack=MINIMAL_REGEX_PATTERNS, drop_rfc1918=False),
        }
        if with_enterprise:
            # 5th route — Nemotron-aug-trained enterprise adapter,
            # gated at margin=0.10 in the embedding detector.
            routes["enterprise"] = _adapter(
                "enterprise",
                regex_pack=DEFAULT_REGEX_PATTERNS,
                drop_rfc1918=args.drop_rfc1918,
                use_expanded_prompts=True,
            )
        return routes

    builders: dict[str, Callable[[], Callable]] = {
        # ─── nullpii — local npm runtime (canonical user-facing row) ──
        # Spawns `node bin/nullpii.mjs scan --ndjson` from the local
        # build (`dist/cli/index.js`). One model load, NDJSON streaming.
        # This is the row that bench-as-published: identical pipeline
        # to what `npm i nullpii` users get (distiluse encoder +
        # embedding router + 5 merged-LoRA GLiNER + recognizer pack +
        # vault). Requires `npm run build` and a populated model dir
        # (env `NULLPII_MODEL_DIR`, default falls through to npm's
        # default download cache).
        # Force nullpii to CPU regardless of the global `--backend`. On
        # the 5090 (SM_120) onnxruntime's CUDA EP can't run the GLiNER
        # MoE node (`Non-zero status code returned while running MoE`),
        # but the rest of the tools (PyTorch transformers) run fine on
        # CUDA — so the pod bench wants `--backend cuda` overall.
        "nullpii": lambda: nullpii_runtime_predictor(
            backend="cpu",
            model_dir=os.environ.get("NULLPII_MODEL_DIR"),
        ),
        # ─── Python re-impl (sanity check vs the npm subprocess) ────
        # Composes the router stack from individual library calls
        # (gliner + peft for LoRA + Python ports of boundary refine /
        # never-PII / URL filter / regex pack). Not byte-for-byte
        # identical to the `nullpii` row.
        "nullpii-router-embedding": lambda: (lambda r: domain_routed_predictor(
            detector=_make_embedding_detector(
                device=backend,
            ),
            routes=r,
            fallback=r["narrative"],
        ))(_routes(with_enterprise=True)),
        # ─── Model-only — what someone gets running just the HF
        # `lBroth/nullpii` artifacts (distiluse routing + LoRA-merged
        # GLiNER inference + adversarial-input normalisation) without the
        # npm runtime's regex pack / url_filter / never_pii_filter /
        # boundary refinement. Honest representation of the HF model
        # card's published F1: what the model alone delivers.
        "nullpii-model-only": lambda: (lambda r: domain_routed_predictor(
            detector=_make_embedding_detector(
                device=backend,
            ),
            routes=r,
            fallback=r["narrative"],
        ))({
            d: gliner_lora_predictor(
                "urchade/gliner_multi_pii-v1",
                f"packages/eval/results/train/adapters/{d}/adapter",
                device=backend,
                threshold=args.gliner_threshold,
                normalize_input=True,
            )
            for d in ("devops", "legal", "medical", "narrative", "enterprise")
        }),
        # ─── Bare third-party baselines (no nullpii pipeline overlay) ─
        # Each runs upstream library directly. NONE wraps nullpii post-
        # processing (boundary refine / never-PII filter / regex pack /
        # `_normalize_for_detection`). Only the per-tool label remap to
        # nullpii's 12-class schema runs (cross-schema bridge).
        "presidio":  lambda **kw: presidio_predictor(**kw),
        "presidio-multilang": lambda **kw: presidio_multilang_predictor(**kw),
        "deberta":   lambda **kw: _mark_batch(deberta_pii_predictor(device=backend, batch_size=_BATCH, **kw)),
        "deberta-simple": lambda: _mark_batch(deberta_pii_predictor(device=backend, batch_size=_BATCH, aggregation_strategy="simple")),
        "piiranha":  lambda **kw: _mark_batch(piiranha_predictor(device=backend, batch_size=_BATCH, **kw)),
        "rizzo-pii": lambda **kw: _mark_batch(rizzo_pii_predictor(device=backend, batch_size=_BATCH, **kw)),
        # GLiNER multi PII v1 (`urchade/gliner_multi_pii-v1`) bare HF.
        "gliner-onnx-pii-fp32": lambda **kw: gliner_v2_predictor(
            "onnx-community/gliner_multi_pii-v1",
            onnx_file="onnx/model.onnx",
            labels=_GLINER_NATIVE_LABELS,
            label_map=_GLINER_NATIVE_TO_NULLPII8,
            **{"threshold": args.gliner_threshold, **kw},
        ),
        # ─── nullpii bare model — the merged-LoRA ONNX
        # WITHOUT the npm runtime pipeline. Loads `model.onnx` from
        # `NULLPII_MODEL_DIR` (the same artifact `npm i nullpii`
        # downloads, but consumed via the bare `gliner_v2_predictor`
        # — no recognizer pack, no `_normalize_for_detection`, no
        # base64 decoder, no boundary refine, no never-PII filter).
        # Honest representation of what the HF artifact alone
        # delivers, paired with the `nullpii` row (full runtime) so
        # the model vs pipeline delta is explicit on the model card.
        "nullpii-bare": lambda: gliner_v2_predictor(
            os.environ.get("NULLPII_MODEL_DIR", "packages/eval/results/release/onnx-unified-aug2"),
            onnx_file="model.onnx",
            threshold=args.gliner_threshold,
            local_files_only=True,
        ),
        # NVIDIA Nemotron-PII (`nvidia/gliner-pii`, gliner_large-v2.1
        # backbone, ~600 MB, 55+ PII categories). 37→8 label remap.
        "nemotron-pii-raw": lambda **kw: gliner_nemotron_pii_predictor(
            model_path="nvidia/gliner-pii",
            device=backend,
            **{"threshold": 0.3, **kw},
        ),
        # `gliner-pii-large-v1.0` (knowledgator) — PII-specialised
        # Apache fine-tune, gliner-large backbone. Bare HF.
        "gliner-pii-large-v1": lambda **kw: gliner_v2_predictor(
            "knowledgator/gliner-pii-large-v1.0",
            device=backend,
            local_files_only=False,
            labels=_GLINER_NATIVE_LABELS,
            label_map=_GLINER_NATIVE_TO_NULLPII8,
            **{"threshold": args.gliner_threshold, **kw},
        ),
        # A local merged GLiNER directory (phase-F2 bare-model A/B), prompted
        # with nullpii's 12 runtime labels. The directory comes from
        # NULLPII_EVAL_GLINER_DIR; run each model into its own --out-dir.
        "gliner-local": lambda: gliner_v2_predictor(
            _required_env("NULLPII_EVAL_GLINER_DIR"),
            device=backend,
            threshold=args.gliner_threshold,
            local_files_only=True,
        ),
        # Knowledgator's streaming-span GLiNER on a Qwen3-0.6B causal
        # backbone (July 2026, Apache-2.0). Needs gliner>=0.2.28, newer
        # than this venv's pin, so it runs from a separate venv; same
        # native labels and map as its sibling gliner-pii-large-v1.
        "gliner-stream-pii": lambda **kw: gliner_v2_predictor(
            "knowledgator/gliner-stream-pii-v1.0",
            device=backend,
            local_files_only=False,
            labels=_GLINER_NATIVE_LABELS,
            label_map=_GLINER_NATIVE_TO_NULLPII8,
            **{"threshold": args.gliner_threshold, **kw},
        ),
        # `openai/privacy-filter` — DeBERTa-v3 BIOES-tagged PII tagger,
        # trained on nullpii's exact 8-class schema. Decoded via explicit
        # BIOES walk (the HF naive aggregation drops boundary tokens for
        # BIOES schemas). Bare HF, no nullpii post-processing.
        "openai-privacy-filter": lambda **kw: openai_privacy_filter_predictor(
            device=backend, **kw,
        ),
        # ─── Token classifiers fine-tuned on nvidia/Nemotron-PII ─────
        # Card usage (`aggregation_strategy="simple"`), inputs cut into
        # token windows of the fine-tuning length; see `TokenClassifierSpec`.
        # The 2048-token ModernBERT windows run at a smaller GPU batch so
        # activations fit next to other jobs; batch size changes padding
        # only, never the windows a document is cut into.
        "openmed-small": lambda **kw: _mark_batch(hf_token_classifier_predictor(OPENMED_SMALL, device=backend, batch_size=_BATCH, **kw)),
        "openmed-large": lambda **kw: _mark_batch(hf_token_classifier_predictor(OPENMED_LARGE, device=backend, batch_size=_BATCH, **kw)),
        "ettin-68m": lambda **kw: _mark_batch(hf_token_classifier_predictor(ETTIN_68M, device=backend, batch_size=min(_BATCH, _LONG_WINDOW_BATCH), **kw)),
        "pii-identifier": lambda **kw: _mark_batch(hf_token_classifier_predictor(PII_IDENTIFIER, device=backend, batch_size=min(_BATCH, _LONG_WINDOW_BATCH), **kw)),
        # OpenMed's opf fine-tune of openai/privacy-filter, served by the
        # same opf runtime as the row above (CPU: opf has no MPS path).
        "openmed-pf-multi-v2": lambda **kw: openmed_privacy_filter_predictor(device=backend, **kw),
    }
    requested = [t.strip() for t in args.tools.split(",") if t.strip()]
    configs = _tool_configs(args.tool_config)
    unknown = sorted(set(configs) - set(requested))
    if unknown:
        raise SystemExit(f"--tool-config names tools not requested: {unknown}")
    out: dict[str, Callable] = {}
    for t in requested:
        if t not in builders:
            raise SystemExit(f"unknown tool: {t}")
        print(f"[bench] loading {t} ({backend}) {sorted(configs.get(t, {}))}…", flush=True)
        out[t] = builders[t](**configs.get(t, {}))
    return out


def _tool_configs(path: str) -> dict[str, dict]:
    """Per-tool builder overrides from `--tool-config` (rule change 9: a
    competitor's tuned operating point). `{"tool": {"threshold": 0.05,
    "label_cut": {"default": 0.5, "thresholds": {...}}, "o_bias": 2.0,
    "viterbi_biases": {...}}}`; a `label_cut` object becomes a `LabelCut`."""
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    configs: dict[str, dict] = {}
    for tool, kwargs in raw.items():
        cut = kwargs.get("label_cut")
        if cut is not None:
            kwargs = {**kwargs, "label_cut": LabelCut(thresholds=dict(cut["thresholds"]), default=float(cut["default"]))}
        configs[tool] = kwargs
    return configs


# ─── Checkpointed worker ─────────────────────────────────────────
def _checkpoint_paths(ckpt_dir: Path, tool: str, dataset: str) -> tuple[Path, Path]:
    return (
        ckpt_dir / f"{tool}-{dataset}.jsonl",
        ckpt_dir / f"{tool}-{dataset}.state",
    )


def _checkpoint_spans(result) -> list[tuple]:
    """(start, end, label), plus the tool's score where it emits one, so
    `threshold_sim.py` can screen operating points from the checkpoint."""
    if not result.scores:
        return [(s.start, s.end, s.label) for s in result.spans]
    if len(result.scores) != len(result.spans):
        raise ValueError(f"{len(result.spans)} spans but {len(result.scores)} scores")
    return [(s.start, s.end, s.label, round(sc, 6)) for s, sc in zip(result.spans, result.scores, strict=True)]


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
    # Batch-mode tools (deberta, piiranha) declare `predictor.is_batch=True`
    # and accept `list[str]` directly. Feeding them one sample at a time
    # caps throughput at ~2 samp/s on a 5090; in real batches deberta-pii
    # ramps to ~100 samp/s. Single-sample tools (presidio, nullpii via
    # npm subprocess, gliner-v2 chunked predictor) stay on the per-sample
    # path because their internals can't share work across inputs anyway.
    is_batch = bool(getattr(predictor, "is_batch", False))
    # Tools whose documented API takes the text's language per call
    # (Presidio) declare `wants_language` and get the sample's language.
    wants_language = bool(getattr(predictor, "wants_language", False))
    # Outer chunk size for run_combo's iteration; the predictor's
    # internal `batch_size` (set in build_tools) governs the actual GPU
    # batch. 32 keeps activation memory safe even with 4 parallel tools
    # sharing the 5090's 32 GB VRAM on long-document datasets (tab-echr
    # / ai4privacy etc).
    batch_size = 32 if is_batch else 1
    with pred_path.open("a", encoding="utf-8") as f:
        for batch_start in range(done_idx + 1, len(samples), batch_size):
            batch_end = min(batch_start + batch_size, len(samples))
            try:
                if is_batch:
                    texts = [samples[k].text for k in range(batch_start, batch_end)]
                    results = list(predictor(texts))
                elif wants_language:
                    results = [predictor(samples[batch_start].text, language=samples[batch_start].language)]
                else:
                    results = [predictor(samples[batch_start].text)]
            except Exception as e:
                f.flush()
                state_path.write_text(str(batch_start - 1))
                msg = f"{type(e).__name__}: {e}"
                print(f"  [{tool_name}/{dataset.key}] idx={batch_start} FATAL {msg}", flush=True)
                raise RuntimeError(
                    f"{tool_name}/{dataset.key} failed at idx={batch_start}: {msg}",
                ) from e
            for offset, result in enumerate(results):
                i = batch_start + offset
                preds.append(list(result.spans))
                f.write(json.dumps({"idx": i, "spans": _checkpoint_spans(result)}) + "\n")
            i = batch_end - 1
            if ((i + 1) // flush_every) > (batch_start // flush_every) or i + 1 == len(samples):
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
    parser.add_argument("--backend", default="cuda", choices=["cpu", "cuda", "mps"])
    parser.add_argument("--datasets", default="all")
    parser.add_argument("--max-per-dataset", type=int, default=0,
                        help="0 = use per-dataset defaults; >0 = cap every dataset to N")
    parser.add_argument("--no-cap", action="store_true",
                        help="ignore per-dataset default caps (full no-cap bench)")
    parser.add_argument("--confusion", action="store_true",
                        help="emit per-label TP/FP/FN to confusion.json")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--checkpoint-dir", default="")
    parser.add_argument("--gliner-threshold", type=float, default=0.5)
    parser.add_argument("--tool-config", default="",
                        help="JSON file of per-tool builder overrides (operating points); see _tool_configs")
    parser.add_argument(
        "--drop-rfc1918", action="store_true",
        help="Enable nullpii's never_pii_filter to drop RFC1918 + link-local IPs. "
             "Off by default — those ranges can carry internal-network PII.",
    )
    parser.add_argument("--parallel-tools", type=int, default=1,
                        help="run N tools concurrently within each dataset (1=serial). "
                             "32GB 5090 fits 4-6 ML tools simultaneously.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = Path(args.checkpoint_dir or (out_dir / "checkpoints"))
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    # One writer per checkpoint directory: two runs resuming it at once would
    # each append every row. Held until the process exits.
    ckpt_lock = (ckpt_dir / ".lock").open("w")
    try:
        fcntl.flock(ckpt_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"{ckpt_dir}: another bench_full run is writing these checkpoints") from None

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
