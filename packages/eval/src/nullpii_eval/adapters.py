"""Tool adapters: each takes `text` and returns a list of `Span`.

The nullpii adapter spawns a long-running `nullpii serve` process and
talks to it via JSON-lines on stdin/stdout — keeps the model in memory
across calls (one model load, not one per sample).

Presidio runs in-process via its Python API.
"""
from __future__ import annotations

import atexit
import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .datasets import Span

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
NULLPII_BIN = REPO_ROOT / "bin" / "nullpii.mjs"
DEFAULT_MODEL_DIR = REPO_ROOT / "packages" / "convert" / "artifacts" / "model"


@dataclass(frozen=True, slots=True)
class ToolResult:
    spans: list[Span]
    elapsed_ms: float
    # Optional parallel scores per span. Empty tuple = no scores
    # available (resolver will default to 1.0). Populated by predictors
    # that have native confidence (e.g. GLiNER) or by the regex layer
    # which assigns per-label priors.
    scores: tuple[float, ...] = ()


Predictor = Callable[[str], ToolResult]


@dataclass(frozen=True, slots=True)
class LabelCut:
    """A per-label operating point (PROTOCOL rule change 9, item 3): a span
    is kept iff its score reaches its label's threshold, or `default` for a
    label the map does not list. Applied to a tool's own scores, after its
    label map and before its window dedupe."""

    thresholds: Mapping[str, float]
    default: float

    def keeps(self, label: str, score: float) -> bool:
        return score >= self.thresholds.get(label, self.default)


def _scored_result(spans_with_scores: list[tuple[Span, float]], kept: list[Span], elapsed_ms: float) -> ToolResult:
    """The `kept` spans (a subset of the same objects) with their scores."""
    score_by_id = {id(sp): sc for sp, sc in spans_with_scores}
    return ToolResult(kept, elapsed_ms, scores=tuple(score_by_id[id(sp)] for sp in kept))


def _bias_background_logit(model, bias: float) -> None:
    """Lower the background (`O`) logit of every token by `bias`, so a
    positive bias trades precision for recall (rule change 9, item 3: the
    recall knob of a token classifier). A bias of 0 leaves the model
    untouched, so the tool's default output is reproduced exactly."""
    if bias == 0.0:
        return
    o_id = model.config.label2id.get("O")
    if o_id is None:
        raise ValueError(f"{model.config.name_or_path}: no 'O' label to bias")

    def _hook(_module, _inputs, output):
        output.logits[..., o_id] -= bias
        return output

    model.register_forward_hook(_hook)


def _utf16_to_code_points(text: str) -> list[int]:
    """Map each UTF-16 offset of `text` to its code-point offset.

    The nullpii runtime is JavaScript, so its span offsets count UTF-16 code
    units; Python strings and the gold spans count code points. An astral
    character (most emoji) is two units and one code point, so without this
    every span after one would land one position early per such character.
    """
    m: list[int] = []
    for cp, ch in enumerate(text):
        m.append(cp)
        if ord(ch) > 0xFFFF:
            m.append(cp)
    m.append(len(text))
    return m


def nullpii_runtime_predictor(
    *,
    backend: str = "cpu",
    model_dir: str | Path | None = None,
    threshold: float | None = None,
) -> Predictor:
    """Predictor backed by the local nullpii npm package via `scan --ndjson`.

    Spawns `node bin/nullpii.mjs scan --ndjson` once, loads the unified
    GLiNER ONNX in that subprocess (model + recognizer pack + base64
    detector + vault), then streams texts in NDJSON form on stdin and
    reads JSON-per-line span results from stdout. One model load — no
    per-call startup cost.

    This is the canonical "what the user gets via `npm i nullpii`" row.
    Built from the local repo (`dist/cli/index.js`), not the npm
    registry — bench measures the same code that will publish.

    Hardening (2026-05-13): on the first call we wait up to 120 s for
    the model to load. stderr is captured to a tempfile so a crash
    surfaces a real diagnostic instead of a bare `BrokenPipeError`.
    """
    if not NULLPII_BIN.is_file():
        raise FileNotFoundError(f"nullpii CLI not found at {NULLPII_BIN}")

    argv = ["node", str(NULLPII_BIN), "scan", "--ndjson", "--backend", backend]
    if model_dir is not None:
        argv += ["--model-dir", str(model_dir)]
    if threshold is not None:
        argv += ["--threshold", str(threshold)]

    import tempfile as _tempfile  # noqa: I001  (local-only)

    stderr_log = _tempfile.NamedTemporaryFile(
        mode="w+", prefix="nullpii-stderr-", suffix=".log", delete=False,
    )
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr_log,
        text=True,
        bufsize=1,
    )
    if proc.stdin is None or proc.stdout is None:
        raise RuntimeError("nullpii subprocess: stdin/stdout pipes failed to open")

    def _drain_stderr() -> str:
        try:
            with open(stderr_log.name, encoding="utf-8", errors="replace") as f:
                return f.read()[-2000:]
        except OSError:
            return "<stderr unreadable>"

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        try:
            proc.stdin.write(json.dumps({"text": text}) + "\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
        except BrokenPipeError as e:
            rc = proc.poll()
            raise RuntimeError(
                f"nullpii subprocess died before first write (rc={rc}). "
                f"stderr tail:\n{_drain_stderr()}",
            ) from e
        line = proc.stdout.readline()  # type: ignore[union-attr]
        elapsed = (time.perf_counter() - t0) * 1000
        if not line:
            rc = proc.poll()
            raise RuntimeError(
                f"nullpii subprocess closed stdout unexpectedly (rc={rc}). "
                f"stderr tail:\n{_drain_stderr()}",
            )
        result = json.loads(line)
        if "error" in result:
            raise RuntimeError(f"nullpii ndjson error: {result['error']}")
        to_point = _utf16_to_code_points(text)
        spans: list[Span] = []
        for s in result.get("spans", []):
            label = str(s.get("label", "")).lower()
            spans.append(Span(label, to_point[int(s["start"])], to_point[int(s["end"])]))
        return ToolResult(spans, elapsed)

    return _predict


BatchPredictor = Callable[[list[str]], list[ToolResult]]


_PIIRANHA_LABEL_MAP = {
    "ACCOUNTNUM": "account_number",
    "CREDITCARDNUMBER": "account_number",
    "IDCARDNUM": "account_number",
    "SOCIALNUM": "account_number",
    "TAXNUM": "account_number",
    # v0.3 schema split: driver licence has its own `private_driver_license`.
    "DRIVERLICENSENUM": "private_driver_license",
    "BUILDINGNUM": "private_address",
    "CITY": "private_address",
    "STREET": "private_address",
    "ZIPCODE": "private_address",
    "DATEOFBIRTH": "private_date",
    "EMAIL": "private_email",
    "GIVENNAME": "private_person",
    "SURNAME": "private_person",
    "USERNAME": "private_person",  # as `_AI4PRIVACY_LABELS` USERNAME
    "TELEPHONENUM": "private_phone",
    "PASSWORD": "secret",
}


# piiranha's card: "context length is 256 Deberta tokens". The overlap keeps
# the old 1,000/200-character chunking's one-fifth ratio.
_PIIRANHA_MAX_TOKENS = 256
_PIIRANHA_OVERLAP_TOKENS = 48


def piiranha_predictor(
    *,
    device: str | None = None,
    batch_size: int = 32,
    o_bias: float = 0.0,
    label_cut: LabelCut | None = None,
) -> BatchPredictor:
    """`iiiorg/piiranha-v1-detect-personal-information` — multilingual
    DeBERTa-v3-based PII detector (en/es/fr/de/it/nl, 17 labels, 256 tok).

    Upstream model card: "context length is 256 Deberta tokens. If your
    text is longer than that, just split it up". The input is cut into
    token windows of at most 256 tokens, special tokens included, with
    `_PIIRANHA_OVERLAP_TOKENS` of overlap, and spans repeated in an
    overlap are deduped by IoU. (Until 2026-10-18 the windows were 1,000
    characters: about 250 tokens of prose, but up to 724 tokens of code,
    which ran the model far past its trained length on trace text.)
    """
    try:
        import torch  # noqa: I001
        from transformers import pipeline
    except ImportError as e:
        raise ImportError("transformers + torch required") from e

    if device is None:
        device = "mps" if torch.backends.mps.is_available() else (
            "cuda" if torch.cuda.is_available() else "cpu"
        )
    if device == "cpu":
        threads = max(1, (os.cpu_count() or 8) // 2)
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(max(1, threads // 4))
        except RuntimeError:
            pass

    pipe = pipeline(
        task="token-classification",
        model="iiiorg/piiranha-v1-detect-personal-information",
        aggregation_strategy="simple",
        device=device,
        batch_size=batch_size,
    )
    native = {_strip_bioes(label) for label in pipe.model.config.id2label.values()} - {"O"}
    _check_label_coverage(native, _PIIRANHA_LABEL_MAP, tool="piiranha")
    _bias_background_logit(pipe.model, o_bias)
    window = _PIIRANHA_MAX_TOKENS - _WINDOW_RESERVED_TOKENS

    def _decode_spans(results: list[dict], text: str, offset: int = 0) -> list[tuple[Span, float]]:
        spans: list[tuple[Span, float]] = []
        for r in results:
            entity = str(r.get("entity_group") or r.get("entity") or "")
            label = _map_native_label(_strip_bioes(entity), _PIIRANHA_LABEL_MAP, tool="piiranha")
            score = float(r["score"])
            if label is None or (label_cut is not None and not label_cut.keeps(label, score)):
                continue
            start, end = _strip_span(text, int(r["start"]) + offset, int(r["end"]) + offset)
            if start < end:
                spans.append((Span(label, start, end), score))
        return spans

    def _dedupe_by_iou(spans: list[Span]) -> list[Span]:
        if len(spans) <= 1:
            return spans
        sorted_spans = sorted(spans, key=lambda s: (s.start, -s.end))
        out: list[Span] = []
        for s in sorted_spans:
            merged = False
            for i in range(len(out) - 1, -1, -1):
                prev = out[i]
                if prev.end <= s.start:
                    break
                if prev.label != s.label:
                    continue
                inter = max(0, min(prev.end, s.end) - max(prev.start, s.start))
                if inter == 0:
                    continue
                union = (prev.end - prev.start) + (s.end - s.start) - inter
                if inter / union >= 0.5:
                    if (s.end - s.start) > (prev.end - prev.start):
                        out[i] = s
                    merged = True
                    break
            if not merged:
                out.append(s)
        return sorted(out, key=lambda s: s.start)

    def _predict_batch(texts: list[str]) -> list[ToolResult]:
        t0 = time.perf_counter()
        # Split each text into chunks; remember which chunk belongs to
        # which input so we can stitch back.
        per_input_chunks: list[list[tuple[int, str]]] = []
        flat_chunks: list[str] = []
        for text in texts:
            chunks = _token_windows(pipe.tokenizer, text, window, _PIIRANHA_OVERLAP_TOKENS) if text else [(0, text)]
            for _, chunk in chunks:
                if len(pipe.tokenizer(chunk)["input_ids"]) > _PIIRANHA_MAX_TOKENS:
                    raise ValueError(f"[piiranha] window exceeds {_PIIRANHA_MAX_TOKENS} tokens; raise the reserve")
            per_input_chunks.append(chunks)
            flat_chunks.extend(c for _, c in chunks)

        flat_results = pipe(flat_chunks) if flat_chunks else []
        if flat_results and isinstance(flat_results[0], dict):
            flat_results = [flat_results]  # type: ignore[list-item]

        elapsed = (time.perf_counter() - t0) * 1000
        per_call = elapsed / max(1, len(texts))

        out: list[ToolResult] = []
        cursor = 0
        for text, chunks in zip(texts, per_input_chunks, strict=True):
            collected: list[tuple[Span, float]] = []
            for off, _ in chunks:
                results = flat_results[cursor] if cursor < len(flat_results) else []
                cursor += 1
                collected.extend(_decode_spans(results, text, offset=off))
            out.append(_scored_result(collected, _dedupe_by_iou([sp for sp, _ in collected]), per_call))
        return out

    return _predict_batch


# `rizzoaiacademy/rizzo-pii-0.3B` (mmBERT/ModernBERT, 22 tags, 44 BIO ids)
# → nullpii's schema. Same contract as `_DEBERTA_LABEL_MAP`: `None` drops
# the prediction.
#
# The rule is SYMMETRY WITH OUR GOLD: a competitor prediction maps to X
# iff our dataset loaders map the corresponding gold label to X. Where
# our gold ignores a category (age, gender, money, organisations), the
# prediction is dropped rather than scored — charging rizzo for
# predicting something no gold in this bench records would measure the
# taxonomy gap, not detection quality.
_RIZZO_LABEL_MAP: dict[str, str | None] = {
    # ─── Person ───────────────────────────────────────────────────
    # Legal roles (judge, lawyer, witness, party) all collapse into
    # FULLNAME upstream — a deliberate choice in their taxonomy.
    "FULLNAME": "private_person",
    # ─── Contact ──────────────────────────────────────────────────
    "EMAIL": "private_email",       # includes PEC upstream
    "TELEPHONENUM": "private_phone",
    # ─── Address ──────────────────────────────────────────────────
    # nullpii collapses every postal component into one label, matching
    # how `_AI4PRIVACY_LABELS` and `_ISOTONIC_LABEL_MAP` fold the gold.
    "STREET": "private_address",
    "BUILDINGNUM": "private_address",
    "CITY": "private_address",
    "ZIPCODE": "private_address",
    "PROVINCE": "private_address",  # administrative subdivision ≡ ai4privacy STATE
    # ─── Temporal ─────────────────────────────────────────────────
    "DATE": "private_date",
    "TIME": "private_date",         # our gold folds TIME → private_date everywhere
    # ─── Structured identifiers ───────────────────────────────────
    "IBAN": "account_number",
    "CREDITCARDNUMBER": "account_number",
    "CF": "account_number",         # nullpii's own `core:cf-italy` emits account_number
    "PIVA": "account_number",       # tax id ≡ ai4privacy TAXNUM
    # MAPPING HAZARD, disclosed. rizzo collapses passport / driving
    # licence / ID card / social number into one ID_DOC tag; nullpii
    # split private_passport and private_driver_license out in v0.3. On
    # gold that says passport, this map produces a FP on account_number
    # AND a FN on private_passport — rizzo is double-charged and cannot
    # win the span. Quantify with the merged-bucket variant before
    # reading any account_number / passport / driver_license cell.
    "ID_DOC": "account_number",
    # ─── Vehicle ──────────────────────────────────────────────────
    "TARGA": "private_vehicle_id",  # nullpii ships `core:plate-it` for the same format
    # ─── Regex net only (the app's `detect_regex`; the model has no such tag)
    "URL": "private_url",
    "IPADDR": "private_ip",
    # ─── Dropped: no home in nullpii's 14-label schema ─────────────
    "AGE": None,        # our gold ignores AGE (`_ISOTONIC_IGNORED`)
    "GENDER": None,     # demographic attribute, not an identifier
    "AMOUNT": None,     # a monetary figure identifies nobody
    "ORG": None,        # our gold drops it (`public_datasets.py` `_NER_LABEL_MAP`)
    "DOCID": None,      # docket / protocol number identifies a proceeding
    "CATASTO": None,    # cadastral parcel; identifies a property, not a person
}

# Classes in nullpii's schema that neither the model nor the app's regex
# net can emit, so rizzo-pii scores a structural 0 on gold holding them.
_RIZZO_UNEMITTABLE = frozenset({
    "secret",
    "private_mac",
    "private_geolocation",
})

# The app pins model release v1.5.0 (`APP_MODEL_VERSION`); this is that tag's commit.
_RIZZO_REVISION = "a1c3c83827eca22e9675e30c1111c4641caf5901"
# The app passes each word chunk whole and the pipeline does not truncate, so
# a chunk runs at any length the model's positions allow. Only a chunk longer
# than that (a whitespace-free run in code or logs, which would crash the app)
# is cut into token windows of that length.
_RIZZO_MAX_POSITIONS = 8192
_RIZZO_OVERLAP_TOKENS = 64
# Chunks are batched under a padded-token budget, so one multi-thousand-token
# chunk is not padded out across a full batch: that ran a 12 GB GPU out of
# memory. Batching changes padding only, never the chunks.
_RIZZO_BATCH_TOKEN_BUDGET = 32 * 512


def rizzo_pii_predictor(
    *,
    device: str | None = None,
    batch_size: int = 32,
    o_bias: float = 0.0,
    label_cut: LabelCut | None = None,
) -> BatchPredictor:
    """`rizzoaiacademy/rizzo-pii-0.3B` run the way its desktop app serves it
    (`src/app/app.py` `analyze()`, vendored in `vendor/rizzo_pii_app.py`):

    1. the model over the app's word chunks (`chunk_text`: 120 words, 20 of
       overlap) with `aggregation_strategy="simple"`;
    2. `complete_time`, which widens the model's TIME spans to the whole time;
    3. `detect_regex` over the full text: email, CF, IBAN, Luhn card, P.IVA,
       Italian phone, plate, URL, IP, docket ids and numeric dates, checksum-
       validated where a checksum exists;
    4. `_merge`: greedy non-overlapping selection (checksum-valid, then hard
       regex, then score, then length), whitespace trim, word-boundary
       extension and fusion.

    The card asks for exactly this: "always pair the model with a regex +
    checksum safety net … This is exactly what the rizzo-pii desktop app
    does." The app strips the text first; spans are shifted back onto the
    original text.

    Operating point: `o_bias` lowers the model's `O` logit, before the
    merge; `label_cut` filters the merged spans by score. Regex spans score
    1.0 when their checksum passed and 0.9 otherwise, as the app records them.

    Two departures from the app, both forced: the model runs on `device`
    (the app picks CUDA or CPU and has no MPS path), and chunks are batched
    under the token budget above (the app runs batch 1; spans are the same).
    """
    from transformers import pipeline

    from .vendor import rizzo_pii_app as app

    device = _resolve_torch_device(device)
    pipe = pipeline(
        task="token-classification",
        model="rizzoaiacademy/rizzo-pii-0.3B",
        revision=_RIZZO_REVISION,
        aggregation_strategy="simple",
        device=device,
    )
    native = {_strip_bioes(label) for label in pipe.model.config.id2label.values()} - {"O"}
    regex_labels = {label for label, *_ in app.DETECTORS} | {"IBAN"}
    _check_label_coverage(native | regex_labels, _RIZZO_LABEL_MAP, tool="rizzo-pii")
    _bias_background_logit(pipe.model, o_bias)
    max_window = _RIZZO_MAX_POSITIONS - _WINDOW_RESERVED_TOKENS

    def _chunks(body: str) -> list[tuple[int, str]]:
        """(offset, chunk): the app's word chunks, each cut into token windows
        only if it is longer than the model's positions."""
        return [
            (offset + sub_offset, sub)
            for chunk, offset in app.chunk_text(body)
            for sub_offset, sub in _token_windows(pipe.tokenizer, chunk, max_window, _RIZZO_OVERLAP_TOKENS)
        ]

    def _run_model(chunks: list[str]) -> list[list[dict]]:
        """Pipeline entities per chunk, in input order, shortest chunks first
        in batches that stay under the padded-token budget."""
        lengths = [len(ids) for ids in pipe.tokenizer(chunks)["input_ids"]]
        order = sorted(range(len(chunks)), key=lengths.__getitem__)
        results: list[list[dict]] = [[] for _ in chunks]
        i = 0
        while i < len(order):
            j = i + 1
            while j < len(order) and j - i < batch_size and (j - i + 1) * lengths[order[j]] <= _RIZZO_BATCH_TOKEN_BUDGET:
                j += 1
            group = order[i:j]
            out = pipe([chunks[k] for k in group], batch_size=len(group))
            for k, entities in zip(group, out, strict=True):
                results[k] = entities
            i = j
        return results

    def _analyze(body: str, chunks: list[tuple[int, str]], per_chunk: list[list[dict]]) -> list[dict]:
        """The app's `analyze()` from the model's entities on: `complete_time`,
        `detect_regex`, `_merge`. Entities are built as `detect_model` does."""
        model_ents = [
            {
                "label": e["entity_group"],
                "start": int(e["start"]) + offset,
                "end": int(e["end"]) + offset,
                "score": float(e["score"]),
                "validated": False,
                "source": "modello",
            }
            for (offset, _), entities in zip(chunks, per_chunk, strict=True)
            for e in entities
        ]
        app.complete_time(model_ents, body)
        return app._merge(model_ents + app.detect_regex(body), body)

    def _predict_batch(texts: list[str]) -> list[ToolResult]:
        t0 = time.perf_counter()
        bodies = [text.strip() for text in texts]
        per_input = [_chunks(body) for body in bodies]
        flat = [chunk for chunks in per_input for _, chunk in chunks]
        flat_results = _run_model(flat) if flat else []
        merged: list[list[dict]] = []
        cursor = 0
        for body, chunks in zip(bodies, per_input, strict=True):
            merged.append(_analyze(body, chunks, flat_results[cursor : cursor + len(chunks)]))
            cursor += len(chunks)
        per_call = (time.perf_counter() - t0) * 1000 / max(1, len(texts))
        out: list[ToolResult] = []
        for text, kept in zip(texts, merged, strict=True):
            lead = len(text) - len(text.lstrip())
            spans: list[tuple[Span, float]] = []
            for e in kept:
                label = _map_native_label(e["label"], _RIZZO_LABEL_MAP, tool="rizzo-pii")
                if label is None or (label_cut is not None and not label_cut.keeps(label, e["score"])):
                    continue
                spans.append((Span(label, e["start"] + lead, e["end"] + lead), e["score"]))
            out.append(_scored_result(spans, [sp for sp, _ in spans], per_call))
        return out

    return _predict_batch


def _dedupe_spans_by_iou(spans: list[Span], threshold: float = 0.5) -> list[Span]:
    """Collapse same-label spans duplicated across a chunk boundary."""
    if len(spans) <= 1:
        return spans
    out: list[Span] = []
    for s in sorted(spans, key=lambda x: (x.start, -x.end)):
        merged = False
        for i in range(len(out) - 1, -1, -1):
            prev = out[i]
            if prev.end <= s.start:
                break
            if prev.label != s.label:
                continue
            inter = max(0, min(prev.end, s.end) - max(prev.start, s.start))
            if inter == 0:
                continue
            union = (prev.end - prev.start) + (s.end - s.start) - inter
            if inter / union >= threshold:
                if (s.end - s.start) > (prev.end - prev.start):
                    out[i] = s
                merged = True
                break
        if not merged:
            out.append(s)
    return sorted(out, key=lambda s: s.start)


_OPENAI_PRIVACY_FILTER_OK = {
    "ACCOUNT_NUMBER",
    "PRIVATE_ADDRESS",
    "PRIVATE_DATE",
    "PRIVATE_EMAIL",
    "PRIVATE_PERSON",
    "PRIVATE_PHONE",
    "PRIVATE_URL",
    "SECRET",
}


def openai_privacy_filter_predictor(
    *,
    device: str | None = None,
    model: str | Path | None = None,
    label_map: dict[str, str | None] | None = None,
    viterbi_biases: Mapping[str, float] | None = None,
) -> Predictor:
    """`openai/privacy-filter` — gpt-oss-derived bidirectional token
    classifier (1.5B params total / 50M active, 128k context). Loaded
    via the upstream `opf` Python API so the constrained Viterbi
    decoder lives in the official runtime, not a local approximation.

    Bare-mode contract: no nullpii post-processing applied. Labels are
    the model's native 8-class taxonomy (already aligned with nullpii's
    schema, modulo case).

    `model` serves an `opf`-layout fine-tune from that checkpoint dir
    instead of the base model; a fine-tune with its own taxonomy then
    passes `label_map` (native upper-case label → nullpii label or None),
    and a predicted label missing from it raises.

    `viterbi_biases` sets the decoder's transition biases, the operating-
    point control the opf README documents for the precision/recall
    trade-off (rule change 9, item 3). Keys are opf's own
    `VITERBI_BIAS_KEYS`; an unlisted key stays 0. `None` uses the
    checkpoint's shipped calibration.
    """
    try:
        from opf import OPF, DecodeOptions
    except ImportError as e:
        raise ImportError(
            "opf required — `pip install -e git+https://github.com/openai/privacy-filter`",
        ) from e

    if device is None:
        try:
            import torch
        except ImportError as e:
            raise ImportError("torch required") from e
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device not in ("cpu", "cuda"):
        # opf only supports cpu / cuda; mps not advertised.
        device = "cpu"

    # `discard_overlapping_predicted_spans=False` makes the bench output
    # reproducible across opf releases — OPF's CLI default flipped in
    # past versions; pinning it here freezes behaviour even if upstream
    # changes its default again. Constrained Viterbi already emits
    # mostly non-overlapping spans, so the effect on F1 is small but
    # the determinism guarantee matters for audit reproducibility.
    runtime = OPF(
        model=model,
        device=device,
        decode_mode="viterbi",
        output_mode="typed",
        trim_whitespace=True,
        discard_overlapping_predicted_spans=False,
    )
    decode = None
    if viterbi_biases is not None:
        decode = DecodeOptions(viterbi_calibration_path=str(_opf_calibration_file(viterbi_biases)))

    def _project(native: str) -> str | None:
        if label_map is None:
            return native.lower() if native in _OPENAI_PRIVACY_FILTER_OK else None
        return _map_native_label(native, label_map, tool="opf")

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        result = runtime.redact(text, decode=decode)
        elapsed = (time.perf_counter() - t0) * 1000
        spans: list[Span] = []
        # OPF returns either a RedactionResult or a plain string when
        # `output_text_only`; we explicitly stay in the structured path.
        detected = getattr(result, "detected_spans", ()) or ()
        for d in detected:
            label = _project(str(d.label).upper())
            if label is not None:
                spans.append(Span(label, int(d.start), int(d.end)))
        return ToolResult(spans, elapsed)

    return _predict


def _opf_calibration_file(biases: Mapping[str, float]) -> Path:
    """An opf `viterbi_calibration.json` holding `biases` as its default
    operating point, written once under the eval cache, keyed by content."""
    from opf._core.decoding import VITERBI_BIAS_KEYS

    unknown = sorted(set(biases) - set(VITERBI_BIAS_KEYS))
    if unknown:
        raise ValueError(f"unknown opf Viterbi bias keys: {unknown}")
    full = {key: float(biases.get(key, 0.0)) for key in VITERBI_BIAS_KEYS}
    payload = json.dumps({"operating_points": {"default": {"biases": full}}}, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    path = _OPF_CALIBRATION_CACHE / f"viterbi-{digest}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload + "\n", encoding="utf-8")
    return path


def _map_native_label(native: str, label_map: dict[str, str | None], *, tool: str) -> str | None:
    """Native label → nullpii label, None for a deliberate drop. A label
    absent from the map raises: a silent fall-through would hide a
    missing map entry as a recall loss."""
    if native not in label_map:
        raise ValueError(f"[{tool}] predicted label {native!r} has no entry in its label map")
    return label_map[native]


# ─── Nemotron-PII taxonomy → nullpii ─────────────────────────────
# Shared by the four token classifiers fine-tuned on `nvidia/Nemotron-PII`
# (OpenMed SuperClinical Small/Large, ettin-68m, pii-identifier). Their
# native labels are the 55 Nemotron-PII types; `national_id` exists only
# in the two ModernBERT heads. Same SYMMETRY RULE as `_RIZZO_LABEL_MAP`:
# a prediction maps to X iff one of our gold loaders maps the equivalent
# gold label to X, and is dropped where our gold ignores the category.
# `_NEMOTRON_TO_NULLPII8` (the nemotron-pii-test gold map) is the first
# reference; where it is silent but a report-set loader maps the same
# concept (fax, api key, IPv6, tax / national id), that loader decides,
# because leaving it out would charge the tool a leak on gold it found.
_NEMOTRON_TOKEN_LABEL_MAP: dict[str, str | None] = {
    # ─── Person ───────────────────────────────────────────────────
    "first_name": "private_person",
    "last_name": "private_person",
    "user_name": "private_person",       # ai4privacy / isotonic USERNAME
    # ─── Contact ──────────────────────────────────────────────────
    "email": "private_email",
    "phone_number": "private_phone",
    "fax_number": "private_phone",       # ai4privacy FAX → private_phone
    "url": "private_url",
    # ─── Address ──────────────────────────────────────────────────
    "street_address": "private_address",
    "city": "private_address",
    "county": "private_address",
    "state": "private_address",
    "postcode": "private_address",
    "country": "private_address",        # ai4privacy / isotonic COUNTRY
    "coordinate": "private_geolocation",
    # ─── Temporal ─────────────────────────────────────────────────
    "date": "private_date",
    "time": "private_date",
    "date_time": "private_date",
    "date_of_birth": "private_date",
    # ─── Structured identifiers ───────────────────────────────────
    "ssn": "account_number",
    "account_number": "account_number",
    "bank_routing_number": "account_number",
    "swift_bic": "account_number",       # ai4privacy / isotonic BIC
    "credit_debit_card": "account_number",
    "cvv": "account_number",             # isotonic CREDITCARDCVV
    "tax_id": "account_number",          # ai4privacy TAXNUM
    "national_id": "account_number",     # ai4privacy IDCARDNUM / SOCIALNUM
    "employee_id": "account_number",
    "customer_id": "account_number",
    "medical_record_number": "account_number",
    "health_plan_beneficiary_number": "account_number",
    "certificate_license_number": "account_number",
    "device_identifier": "account_number",  # isotonic PHONEIMEI
    "vehicle_identifier": "private_vehicle_id",
    "license_plate": "private_vehicle_id",
    "ipv4": "private_ip",
    "ipv6": "private_ip",                # ai4privacy / isotonic / argilla IPV6
    "mac_address": "private_mac",
    # ─── Secrets ──────────────────────────────────────────────────
    "password": "secret",
    "pin": "secret",
    "api_key": "secret",                 # isotonic API_KEY
    # A session cookie is a bearer credential: the traces gold files
    # `_authToken` values and bigcode's AUTH_TOKEN under `secret`.
    "http_cookie": "secret",
    "biometric_identifier": "secret",    # as `_NEMOTRON_TO_NULLPII8`
    # A generic identifier. Measured on isotonic-en tuning rows, nvidia's
    # GLiNER puts 52% of gold account-number and 49% of gold secret
    # characters under it, and NVIDIA's own serving masks it; dropping it
    # (as until 2026-10-19) deleted those detections. Only the categories
    # nullpii's core regime disables are dropped (below).
    "unique_id": "account_number",
    # ─── Dropped: the categories nullpii's core regime disables ──────
    "company_name": None,                # ORG is dropped by every loader
    # Isotonic ignores AGE. NB argilla's gold maps AGE → private_date, so
    # on argilla-pii this drop costs the tool any AGE chars it found;
    # same decision as `_RIZZO_LABEL_MAP`, disclosed rather than split.
    "age": None,
    "gender": None,                      # demographic, `_ISOTONIC_IGNORED`
    "occupation": None,                  # JOBTITLE / JOBTYPE ignored
    "employment_status": None,
    "education_level": None,
    "language": None,
    "blood_type": None,
    "race_ethnicity": None,
    "religious_belief": None,
    "political_view": None,
    "sexuality": None,
}

# `OpenMed/privacy-filter-multilingual-v2` (54 ai4privacy-style types).
# The vocabulary is the one our ai4privacy / isotonic gold uses, so each
# entry mirrors `_AI4PRIVACY_LABELS` / `_ISOTONIC_LABEL_MAP` /
# `_ISOTONIC_IGNORED` under the same or the obvious sibling name.
_OPENMED_PF_LABEL_MAP: dict[str, str | None] = {
    "FIRSTNAME": "private_person",
    "MIDDLENAME": "private_person",
    "LASTNAME": "private_person",
    "PREFIX": "private_person",          # isotonic / argilla PREFIX
    "USERNAME": "private_person",
    "EMAIL": "private_email",
    "PHONE": "private_phone",
    "URL": "private_url",
    "STREET": "private_address",
    "BUILDINGNUMBER": "private_address",
    "SECONDARYADDRESS": "private_address",
    "CITY": "private_address",
    "COUNTY": "private_address",
    "STATE": "private_address",
    "ZIPCODE": "private_address",
    "GPSCOORDINATES": "private_geolocation",
    "DATE": "private_date",
    "DATEOFBIRTH": "private_date",
    "TIME": "private_date",
    "SSN": "account_number",
    "BANKACCOUNT": "account_number",     # ACCOUNTNUMBER
    "IBAN": "account_number",
    "BIC": "account_number",
    "CREDITCARD": "account_number",
    "CVV": "account_number",             # isotonic CREDITCARDCVV
    "MASKEDNUMBER": "account_number",
    "BITCOINADDRESS": "account_number",
    "ETHEREUMADDRESS": "account_number",
    "LITECOINADDRESS": "account_number",
    "IMEI": "account_number",            # isotonic PHONEIMEI
    "IPADDRESS": "private_ip",           # isotonic IP
    "MACADDRESS": "private_mac",
    "VIN": "private_vehicle_id",         # VEHICLEVIN
    "VRM": "private_vehicle_id",         # VEHICLEVRM
    "PASSWORD": "secret",
    "PIN": "secret",
    # ─── Dropped: `_ISOTONIC_IGNORED` / `_AI4PRIVACY_IGNORED` ──────
    "ACCOUNTNAME": None,
    "AGE": None,                         # see the `age` note above
    "SEX": None,
    "GENDER": None,
    "EYECOLOR": None,
    "HEIGHT": None,
    "OCCUPATION": None,
    "JOBTITLE": None,
    "JOBDEPARTMENT": None,
    "ORGANIZATION": None,
    "AMOUNT": None,
    "CURRENCY": None,
    "CURRENCYCODE": None,
    "CURRENCYNAME": None,
    "CURRENCYSYMBOL": None,
    "CREDITCARDISSUER": None,
    "USERAGENT": None,
    "ORDINALDIRECTION": None,
}

OPENMED_PF_REPO = "OpenMed/privacy-filter-multilingual-v2"
OPENMED_PF_REVISION = "0d0c0430fa386435ace1d9f842f0f966903a9ac8"
_OPF_CHECKPOINT_CACHE = Path.home() / ".cache" / "nullpii-eval" / "opf-checkpoints"
_OPF_CALIBRATION_CACHE = Path.home() / ".cache" / "nullpii-eval" / "opf-calibration"


def openmed_privacy_filter_predictor(
    *, device: str | None = None, viterbi_biases: Mapping[str, float] | None = None
) -> Predictor:
    """`OpenMed/privacy-filter-multilingual-v2` — full fine-tune of
    `openai/privacy-filter` (same 1.4B-total / 50M-active MoE) with
    `opf train`, 54 types × BIOES, 16 languages.

    Served by the SAME `opf` runtime as the `openai-privacy-filter` row
    (constrained Viterbi, whitespace trim, CPU-default 4096-token
    window), so the two rows differ only in weights. The vendor ships the
    transformers layout only; `opf_convert` rebuilds the opf layout once,
    after checking the conversion bit-for-bit on the base model.
    """
    from .opf_convert import ensure_opf_checkpoint

    checkpoint = ensure_opf_checkpoint(OPENMED_PF_REPO, OPENMED_PF_REVISION, _OPF_CHECKPOINT_CACHE)
    _check_label_coverage(_opf_span_labels(checkpoint), _OPENMED_PF_LABEL_MAP, tool="openmed-pf")
    return openai_privacy_filter_predictor(
        device=device, model=checkpoint, label_map=_OPENMED_PF_LABEL_MAP, viterbi_biases=viterbi_biases
    )


def _opf_span_labels(checkpoint: Path) -> set[str]:
    config = json.loads((checkpoint / "config.json").read_text(encoding="utf-8"))
    return {str(name).upper() for name in config["span_class_names"] if name != "O"}


def _check_label_coverage(native: set[str], label_map: dict[str, str | None], *, tool: str) -> None:
    """Fail at load time, not mid-run, if the model can emit a label the
    map does not decide."""
    missing = sorted(native - set(label_map))
    if missing:
        raise ValueError(f"[{tool}] model labels missing from the label map: {missing}")


def _resolve_torch_device(device: str | None) -> str:
    """Default device for transformers tools; caps CPU threads like the
    other transformer adapters so a shared machine is not oversubscribed."""
    import torch

    if device is None:
        device = "mps" if torch.backends.mps.is_available() else (
            "cuda" if torch.cuda.is_available() else "cpu"
        )
    if device == "cpu":
        threads = max(1, (os.cpu_count() or 8) // 2)
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(max(1, threads // 4))
        except RuntimeError:
            pass
    return device


def _token_windows(tokenizer, text: str, window_tokens: int, overlap_tokens: int) -> list[tuple[int, str]]:
    """(char_offset, chunk) windows of at most `window_tokens` model tokens,
    consecutive windows sharing `overlap_tokens`, cut on token boundaries
    so the window honours the model's trained length in any language."""
    # The Rust backend is what the fast tokenizer's offset mapping comes
    # from; calling it directly skips the wrapper's over-length warning,
    # which does not apply to an offsets-only pass over the full text.
    # Some checkpoints ship `tokenizer.json` with truncation on (512 tokens
    # for openmed-small, 1024 for ettin-68m), which would silently cut the
    # offsets, and so the windows, to the first few thousand characters.
    # Truncation is off for this pass and put back as it was.
    backend = tokenizer.backend_tokenizer
    saved = backend.truncation
    backend.no_truncation()
    try:
        offsets = backend.encode(text, add_special_tokens=False).offsets
    finally:
        if saved is not None:
            backend.enable_truncation(**saved)
    if offsets and offsets[-1][1] < len(text.rstrip()):
        raise ValueError(f"token offsets end at char {offsets[-1][1]} of {len(text)}: the text was cut")
    if len(offsets) <= window_tokens:
        return [(0, text)]
    stride = window_tokens - overlap_tokens
    windows: list[tuple[int, str]] = []
    for i in range(0, len(offsets), stride):
        start, end = offsets[i][0], offsets[min(i + window_tokens, len(offsets)) - 1][1]
        windows.append((start, text[start:end]))
        if i + window_tokens >= len(offsets):
            break
    return windows


def _merge_adjacent_entities(results: list[dict]) -> list[dict]:
    """The ettin model card's `format_pii_entities`: merge same-label
    entities that touch or are one char apart (it repairs the sub-word
    fragments `aggregation_strategy="simple"` leaves). A merged entity
    keeps the highest score of its parts."""
    merged: list[dict] = []
    for r in sorted(results, key=lambda x: x["start"]):
        prev = merged[-1] if merged else None
        if prev and prev["entity_group"] == r["entity_group"] and r["start"] <= prev["end"] + 1:
            prev["end"] = max(prev["end"], r["end"])
            prev["score"] = max(prev["score"], float(r["score"]))
            continue
        merged.append({"entity_group": r["entity_group"], "start": r["start"], "end": r["end"], "score": float(r["score"])})
    return merged


def _strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Drop leading/trailing whitespace. BPE and SentencePiece offsets put
    the separating space inside the word's first token, so every raw span
    starts on a blank; trimming removes that tokenizer artifact only."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


@dataclass(frozen=True, slots=True)
class TokenClassifierSpec:
    """How to serve one HF token-classification checkpoint."""

    tool: str
    model_id: str
    revision: str
    label_map: dict[str, str | None]
    # Longest input the model was fine-tuned on, special tokens included.
    max_tokens: int
    overlap_tokens: int
    aggregation_strategy: str = "simple"
    merge_adjacent: bool = False


# Two special tokens ([CLS]/[SEP]) plus slack for a chunk re-tokenizing a
# few tokens longer than its slice of the full-text tokenization.
_WINDOW_RESERVED_TOKENS = 16
# Overlap between windows: pii-identifier's own training stride.
_WINDOW_OVERLAP_TOKENS = 128

# The ettin card gives no fine-tuning length (the encoder takes 8k), but its
# shipped `tokenizer.json` truncates at 1024 tokens, a setting saved from
# training; plus the card's own adjacent-entity merge.
ETTIN_68M = TokenClassifierSpec(
    tool="ettin-68m",
    model_id="kalyan-ks/ettin-68m-nemotron-pii",
    revision="500262a2aaf913825ef750ef255c3fe437cd8e64",
    label_map=_NEMOTRON_TOKEN_LABEL_MAP,
    max_tokens=1024,
    overlap_tokens=_WINDOW_OVERLAP_TOKENS,
    merge_adjacent=True,
)
# `preprocessing.json` in the repo: max_length 2048, stride 128 (the card
# prose says 8192; the shipped training config is the one followed).
PII_IDENTIFIER = TokenClassifierSpec(
    tool="pii-identifier",
    model_id="antoniogr7/pii-identifier-v0.1",
    revision="3d0f39eceaf0c95fc07943064c58fba3fff60243",
    label_map=_NEMOTRON_TOKEN_LABEL_MAP,
    max_tokens=2048,
    overlap_tokens=_WINDOW_OVERLAP_TOKENS,
)


def hf_token_classifier_predictor(
    spec: TokenClassifierSpec,
    *,
    device: str | None = None,
    batch_size: int = 32,
    o_bias: float = 0.0,
    label_cut: LabelCut | None = None,
) -> BatchPredictor:
    """Bare HF token classifier run the way its model card shows
    (`pipeline(..., aggregation_strategy="simple")`), with inputs cut into
    token windows no longer than the model's fine-tuning length.

    No nullpii post-processing; the only glue is the window stitch (IoU
    dedupe of spans repeated in an overlap), the whitespace trim of
    `_strip_span`, and the card's own merge where `spec.merge_adjacent`.
    """
    from transformers import pipeline

    device = _resolve_torch_device(device)
    pipe = pipeline(
        task="token-classification",
        model=spec.model_id,
        revision=spec.revision,
        aggregation_strategy=spec.aggregation_strategy,
        device=device,
        batch_size=batch_size,
    )
    native = {_strip_bioes(label) for label in pipe.model.config.id2label.values()} - {"O"}
    _check_label_coverage(native, spec.label_map, tool=spec.tool)
    _bias_background_logit(pipe.model, o_bias)
    # Window budget excludes special tokens; the pipeline's own
    # truncation is set to the trained length as a hard ceiling.
    window = spec.max_tokens - _WINDOW_RESERVED_TOKENS
    pipe.tokenizer.model_max_length = spec.max_tokens

    def _chunks(text: str) -> list[tuple[int, str]]:
        chunks = _token_windows(pipe.tokenizer, text, window, spec.overlap_tokens) if text else []
        for _, chunk in chunks:
            if len(pipe.tokenizer(chunk)["input_ids"]) > spec.max_tokens:
                raise ValueError(f"[{spec.tool}] window exceeds {spec.max_tokens} tokens; raise the reserve")
        return chunks

    def _decode(results: list[dict], text: str, offset: int) -> list[tuple[Span, float]]:
        entities = _merge_adjacent_entities(results) if spec.merge_adjacent else results
        spans: list[tuple[Span, float]] = []
        for r in entities:
            label = _map_native_label(str(r["entity_group"]), spec.label_map, tool=spec.tool)
            score = float(r["score"])
            if label is None or (label_cut is not None and not label_cut.keeps(label, score)):
                continue
            start, end = _strip_span(text, int(r["start"]) + offset, int(r["end"]) + offset)
            if start < end:
                spans.append((Span(label, start, end), score))
        return spans

    def _predict_batch(texts: list[str]) -> list[ToolResult]:
        t0 = time.perf_counter()
        per_input = [_chunks(text) for text in texts]
        flat = [chunk for chunks in per_input for _, chunk in chunks]
        flat_results = pipe(flat) if flat else []
        if flat_results and isinstance(flat_results[0], dict):
            flat_results = [flat_results]  # type: ignore[list-item]
        per_call = (time.perf_counter() - t0) * 1000 / max(1, len(texts))
        out: list[ToolResult] = []
        cursor = 0
        for text, chunks in zip(texts, per_input, strict=True):
            collected: list[tuple[Span, float]] = []
            for offset, _ in chunks:
                collected.extend(_decode(flat_results[cursor], text, offset))
                cursor += 1
            out.append(_scored_result(collected, _dedupe_spans_by_iou([sp for sp, _ in collected]), per_call))
        return out

    return _predict_batch


# lakshyakh93/deberta_finetuned_pii is a deberta-base fine-tune (512 positions).
_DEBERTA_MAX_TOKENS = 512
_DEBERTA_OVERLAP_TOKENS = 128

# Keyed by the model's own 59 native labels (`config.id2label`, BIO
# prefix stripped), checked at load. Same SYMMETRY RULE as the other maps:
# each label maps where `_AI4PRIVACY_LABELS` maps the same ai4privacy
# concept, and is dropped where that gold ignores it. Until 2026-10-19 the
# keys followed a different ai4privacy release (`PHONENUMBER`, `DOB`,
# `GPSCOORDINATES`), so phones, full names, usernames, IPs and MACs never
# reached scoring.
_DEBERTA_LABEL_MAP: dict[str, str | None] = {
    "FIRSTNAME": "private_person",
    "LASTNAME": "private_person",
    "MIDDLENAME": "private_person",
    "FULLNAME": "private_person",
    "NAME": "private_person",
    "DISPLAYNAME": "private_person",
    "PREFIX": "private_person",           # gold NAMEPREFIX
    "SUFFIX": "private_person",           # gold NAMESUFFIX
    "USERNAME": "private_person",
    "ACCOUNTNUMBER": "account_number",
    "BIC": "account_number",
    "IBAN": "account_number",
    "BITCOINADDRESS": "account_number",
    "ETHEREUMADDRESS": "account_number",
    "LITECOINADDRESS": "account_number",
    "MASKEDNUMBER": "account_number",
    "CREDITCARDNUMBER": "account_number",
    "CREDITCARDCVV": "account_number",
    "PHONEIMEI": "account_number",
    "SSN": "account_number",
    "VEHICLEVRM": "private_vehicle_id",
    "VEHICLEVIN": "private_vehicle_id",
    "PIN": "secret",
    "PASSWORD": "secret",
    "EMAIL": "private_email",
    "PHONE_NUMBER": "private_phone",
    "STREET": "private_address",
    "STREETADDRESS": "private_address",
    "SECONDARYADDRESS": "private_address",
    "BUILDINGNUMBER": "private_address",
    "ZIPCODE": "private_address",
    "CITY": "private_address",
    "STATE": "private_address",
    "COUNTY": "private_address",
    "NEARBYGPSCOORDINATE": "private_geolocation",
    "DATE": "private_date",
    "TIME": "private_date",
    "URL": "private_url",
    "IP": "private_ip",
    "IPV4": "private_ip",
    "IPV6": "private_ip",
    "MAC": "private_mac",
    # ─── Dropped: no gold counterpart, or ignored by the gold ─────
    "ACCOUNTNAME": None,                  # account nickname, not a number
    "USERAGENT": None,
    "CREDITCARDISSUER": None,             # gold CARDISSUER is ignored
    "COMPANY_NAME": None,
    "AMOUNT": None,
    "CURRENCY": None,
    "CURRENCYCODE": None,
    "CURRENCYNAME": None,
    "CURRENCYSYMBOL": None,
    # A generic number label: on isotonic-en tuning rows 133 of the 146
    # characters it covers are gold identifiers, so it masks, as unique_id.
    "NUMBER": "account_number",
    "ORDINALDIRECTION": None,
    "GENDER": None,
    "SEX": None,                          # gold SEX is ignored
    "SEXTYPE": None,
    "JOBAREA": None,
    "JOBDESCRIPTOR": None,
    "JOBTITLE": None,
    "JOBTYPE": None,
}


def deberta_pii_predictor(
    *,
    device: str | None = None,
    batch_size: int = 32,
    aggregation_strategy: str = "first",
    o_bias: float = 0.0,
    label_cut: LabelCut | None = None,
) -> BatchPredictor:
    """`lakshyakh93/deberta_finetuned_pii` — DeBERTa-base English-only PII
    detector with rich label set (~50+ categories). Mapped to nullpii's
    12-class schema (8 trained + 4 zero-shot extras).

    `aggregation_strategy` defaults to `"first"`. A/B tested against
    `"simple"` on 5 representative datasets (nullpii-bench, tab-echr,
    presidio-synthetic, ai4privacy-400k, isotonic-en): `"first"` wins
    every row, averaging +0.128 macro F1 over `"simple"`. The model
    card's example also uses `"first"`. Override via the
    `deberta-simple` bench tool only if you want to re-validate.
    """
    try:
        import torch  # noqa: I001
        from transformers import pipeline
    except ImportError as e:
        raise ImportError("transformers + torch required") from e

    if device is None:
        device = "mps" if torch.backends.mps.is_available() else (
            "cuda" if torch.cuda.is_available() else "cpu"
        )
    if device == "cpu":
        threads = max(1, (os.cpu_count() or 8) // 2)
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(max(1, threads // 4))
        except RuntimeError:
            pass

    pipe = pipeline(
        task="token-classification",
        model="lakshyakh93/deberta_finetuned_pii",
        aggregation_strategy=aggregation_strategy,
        device=device,
        batch_size=batch_size,
    )
    native = {_strip_bioes(label) for label in pipe.model.config.id2label.values()} - {"O"}
    _check_label_coverage(native, _DEBERTA_LABEL_MAP, tool="deberta")
    _bias_background_logit(pipe.model, o_bias)

    # The pipeline truncates each input to 512 tokens, so a long document
    # is cut into token windows first, as for the other HF classifiers.
    window = _DEBERTA_MAX_TOKENS - _WINDOW_RESERVED_TOKENS

    def _predict_batch(texts: list[str]) -> list[ToolResult]:
        t0 = time.perf_counter()
        per_input = [
            _token_windows(pipe.tokenizer, text, window, _DEBERTA_OVERLAP_TOKENS) if text else []
            for text in texts
        ]
        flat = [chunk for chunks in per_input for _, chunk in chunks]
        flat_results = pipe(flat) if flat else []
        if flat_results and isinstance(flat_results[0], dict):
            flat_results = [flat_results]  # type: ignore[list-item]
        per_call = (time.perf_counter() - t0) * 1000 / max(1, len(texts))
        out: list[ToolResult] = []
        cursor = 0
        for text, chunks in zip(texts, per_input, strict=True):
            spans: list[tuple[Span, float]] = []
            for offset, _ in chunks:
                for r in flat_results[cursor]:
                    entity = str(r.get("entity_group") or r.get("entity") or "")
                    label = _map_native_label(_strip_bioes(entity), _DEBERTA_LABEL_MAP, tool="deberta")
                    score = float(r["score"])
                    if label is None or (label_cut is not None and not label_cut.keeps(label, score)):
                        continue
                    start, end = _strip_span(text, int(r["start"]) + offset, int(r["end"]) + offset)
                    if start < end:
                        spans.append((Span(label, start, end), score))
                cursor += 1
            out.append(_scored_result(spans, _dedupe_spans_by_iou([sp for sp, _ in spans]), per_call))
        return out

    return _predict_batch


def boundary_refined_predictor(
    *,
    inner: Predictor,
    # Includes typographic apostrophes, guillemets, smart-quotes, low-9
    # quote — common in French / Italian / German prose; ASCII-only
    # leaves these as boundary noise on PII spans.
    trim_chars: str = " \t\n\r,.;:!?\"'()[]{}<>«»‹›‘’“”„‚",
) -> Predictor:
    """Wrap a predictor and refine span boundaries — trim leading/trailing
    whitespace + common punctuation. Helps partial-match scoring (IoU
    >= 0.5) where ML models include trailing dots / brackets that
    ground-truth annotations exclude."""

    def _refine(text: str, s: Span) -> Span | None:
        start, end = s.start, s.end
        while start < end and text[start] in trim_chars:
            start += 1
        while end > start and text[end - 1] in trim_chars:
            end -= 1
        if start >= end:
            return None
        return Span(s.label, start, end)

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        result = inner(text)
        out: list[Span] = []
        for s in result.spans:
            refined = _refine(text, s)
            if refined is not None:
                out.append(refined)
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(out, elapsed)

    return _predict


_REGEX_INPUT_MAX_BYTES = 1_000_000  # 1 MB ReDoS guard

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {c: i for i, c in enumerate(_BASE58_ALPHABET)}


def _base58check_valid(addr: str) -> bool:
    """Validate a base58check-encoded string (BIP-0013).

    Decodes base58 → bytes; payload + 4-byte checksum;
    SHA256(SHA256(payload))[:4] must equal checksum.

    drops false-positive matches on prose tokens that share
    the base58 charset shape (e.g. `Order ID: 1A2B3C4D5E6F7G8H9J1K2L3M4N`)
    but fail the cryptographic checksum.
    """
    if not (25 <= len(addr) <= 35):
        return False
    n = 0
    for ch in addr:
        idx = _BASE58_INDEX.get(ch)
        if idx is None:
            return False
        n = n * 58 + idx
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    # Re-attach leading-zero bytes encoded as leading `1`s in base58.
    leading_ones = 0
    for ch in addr:
        if ch == "1":
            leading_ones += 1
        else:
            break
    decoded = b"\x00" * leading_ones + body
    if len(decoded) < 5:
        return False
    payload, checksum = decoded[:-4], decoded[-4:]
    import hashlib
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return checksum == expected


def _label_validator(label: str, value: str) -> bool:
    """Per-label post-match validators that drop FPs the regex shape
    cannot reject by itself. Currently:

    - account_number: BTC Legacy/P2SH addresses (start with `1` or `3`,
      base58 charset, 26-34 chars) require base58check checksum match.
      Bech32 (`bc1...`) is left alone — its strict regex already
      rejects most non-addresses.
    """
    if label == "account_number" and len(value) >= 26 and len(value) <= 35:
        first = value[0]
        if first in ("1", "3") and all(c in _BASE58_ALPHABET for c in value):
            return _base58check_valid(value)
    return True


def regex_recognizer_predictor(
    *,
    patterns: list[tuple[str, str]],
) -> Predictor:
    """Lightweight regex-based predictor.

    `patterns` is a list of `(label, regex)` tuples; matches yield Spans
    with that label. Useful as a Tier-2 ensemble member to fill gaps
    where ML detectors miss structured formats (URLs, IBANs, etc.).
    Per-label validators (e.g. base58check on BTC addresses) drop
    false-positive matches before emission."""
    import re as _re

    compiled = [(label, _re.compile(pat)) for label, pat in patterns]

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        scores: list[float] = []
        # refuse to scan inputs > 1 MB. Unbounded `{N,}` quantifiers
        # in upstream secret patterns are quadratic on adversarial padding.
        # 1 MB is well above any realistic LLM prompt size.
        if len(text) > _REGEX_INPUT_MAX_BYTES:
            elapsed = (time.perf_counter() - t0) * 1000
            return ToolResult(spans, elapsed, scores=tuple(scores))
        for label, regex in compiled:
            prior = REGEX_LABEL_PRIORS.get(label, 0.9)
            for m in regex.finditer(text):
                if not _label_validator(label, m.group(0)):
                    continue
                spans.append(Span(label, m.start(), m.end()))
                scores.append(prior)
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(spans, elapsed, scores=tuple(scores))

    return _predict


# Per-label priors for regex matches. Used by score-based ensemble
# resolver. Reflects that regex is high-precision on distinctive
# structural patterns (`secret` covers AWS/GitHub/Stripe etc. with
# exact prefixes; `private_email` is RFC-shape; `private_url` is
# scheme-anchored) but noisier on category catch-alls (`account_number`
# bundles IBANs + SSN + IPs + MACs + crypto wallets — IP/MAC alone
# trigger many FPs on generic text). Tuned conservatively so distinctive
# regex always wins overlap with the model, broad regex defers to it.
REGEX_LABEL_PRIORS: dict[str, float] = {
    "secret": 0.95,
    "private_email": 0.95,
    "private_url": 0.90,
    "private_phone": 0.85,
    "account_number": 0.65,  # broad: IPs/MACs/crypto wallets included
    "private_address": 0.70,
    "private_date": 0.70,
    "private_person": 0.70,
}


# Default recognizer pack — merged set covering both the original
# small pack (URL/email/AKIA/etc.) and the `gitleaks/config/gitleaks.toml`
# self-anchored rules (MIT). Excluded the keyword-anchored gitleaks rules
# (those need a label like "adafruit" near the secret — useless on bare
# pasted tokens). Three extra patterns derived from failure_analysis.py
# on `gliner+regex/nullpii-bench`: db connection strings, AWS ARNs, and
# Italian Codice Fiscale — each consistently missed by the ML detector.
DEFAULT_REGEX_PATTERNS: list[tuple[str, str]] = [
    # ─── URL / Email ────────────────────────────────────────────────
    # URL — broad match. Public-domain whitelist filtering happens in
    # `regex_recognizer_predictor_with_url_filter` which wraps this
    # pack. Keep the broad regex here so the recognizer pack stays
    # composable; the filter step prunes whitelisted matches without
    # regex-engine acrobatics.
    ("private_url", r"\b(?:https?://|www\.)[^\s<>\"]+"),
    # Email
    ("private_email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    # IDN-aware pattern `(?<!\w)[\w.%+\-]+@[\w.\-]
    # +\.[\w]{2,24}(?!\w)` produced 336 FP / 500 matches on
    # nullpii-bench (Unicode `\w` matched arbitrary identifier-like
    # strings as email local parts). IDN coverage is now handled by
    # `_normalize_for_detection` (NFKC + unidecode) which converts
    # `john@münchen.de` → `john@munchen.de`, allowing the ASCII
    # pattern to match. True non-Latin emails (`用户@例え.jp`) remain
    # uncovered until a more restrictive Unicode pattern is designed.
    # ─── AWS ────────────────────────────────────────────────────────
    # All access-token prefixes (A3T*, AKIA, ASIA, ABIA, ACCA)
    ("secret", r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b"),
    # AWS Bedrock long-lived
    ("secret", r"\bABSK[A-Za-z0-9+/]{109,269}={0,2}"),
    # ─── GitHub ─────────────────────────────────────────────────────
    ("secret", r"\bghp_[A-Za-z0-9]{36,255}\b"),
    ("secret", r"\bghs_[A-Za-z0-9]{36,255}\b"),
    ("secret", r"\bgho_[A-Za-z0-9]{36,255}\b"),
    ("secret", r"\bghu_[A-Za-z0-9]{36,255}\b"),
    ("secret", r"\bghr_[A-Za-z0-9]{36,255}\b"),
    ("secret", r"\bgithub_pat_[A-Za-z0-9_]{82,255}\b"),
    # ─── OpenAI / Anthropic ─────────────────────────────────────────
    ("secret", r"\bsk-[A-Za-z0-9]{32,255}\b"),
    ("secret", r"\bsk-ant-[A-Za-z0-9_-]{50,255}\b"),
    ("secret", r"\bsk-ant-admin01-[a-zA-Z0-9_\-]{93}AA\b"),
    ("secret", r"\bsk-ant-api03-[a-zA-Z0-9_\-]{93}AA\b"),
    # ─── Stripe ─────────────────────────────────────────────────────
    ("secret", r"\bsk_(?:live|test)_[A-Za-z0-9]{24,255}\b"),
    # ─── 1Password / Adobe / Age / Airtable / Alibaba ──────────────
    ("secret", r"\bA3-[A-Z0-9]{6}-(?:[A-Z0-9]{11}|[A-Z0-9]{6}-[A-Z0-9]{5})-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}\b"),
    ("secret", r"\bops_eyJ[a-zA-Z0-9+/]{250,2048}={0,3}"),
    ("secret", r"\bp8e-[a-zA-Z0-9]{32}\b"),
    ("secret", r"AGE-SECRET-KEY-1[QPZRY9X8GF2TVDW0S3JN54KHCE6MUA7L]{58}"),
    ("secret", r"\bpat[a-zA-Z0-9]{14}\.[a-f0-9]{64}\b"),
    ("secret", r"\bLTAI[a-zA-Z0-9]{20}\b"),
    # ─── Artifactory / Atlassian ───────────────────────────────────
    ("secret", r"\bAKCp[A-Za-z0-9]{69}\b"),
    ("secret", r"\bcmVmd[A-Za-z0-9]{59}\b"),
    ("secret", r"\bATATT3[A-Za-z0-9_\-=]{186}\b"),
    # ─── Misc cloud / SaaS providers ───────────────────────────────
    ("secret", r"\b4b1d[A-Za-z0-9]{38}\b"),
    ("secret", r"(?i)\bCLOJARS_[a-z0-9]{60}\b"),
    ("secret", r"\bv1\.0-[a-f0-9]{24}-[a-f0-9]{146}\b"),
    ("secret", r"\bdapi[a-f0-9]{32}(?:-\d)?\b"),
    ("secret", r"\bdoo_v1_[a-f0-9]{64}\b"),
    ("secret", r"\bdop_v1_[a-f0-9]{64}\b"),
    ("secret", r"\bdor_v1_[a-f0-9]{64}\b"),
    # ─── Slack ──────────────────────────────────────────────────────
    ("secret", r"\bxox[baprs]-[A-Za-z0-9-]{10,255}\b"),
    ("secret", r"\bxoxe\.xoxp-[0-9]+-[A-Za-z0-9]+\b"),
    # ─── GitLab / SendGrid / Twilio / NPM / PyPI / HF / GitLab ──
    ("secret", r"\bglpat-[A-Za-z0-9_\-]{20,255}\b"),
    ("secret", r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b"),
    ("secret", r"\bAC[a-f0-9]{32}\b"),
    ("secret", r"\bSK[a-f0-9]{32}\b"),
    ("secret", r"\bnpm_[A-Za-z0-9]{36,255}\b"),
    ("secret", r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,255}\b"),
    ("secret", r"\bhf_[A-Za-z0-9]{34,255}\b"),
    ("secret", r"\b[a-f0-9]{32}-us[0-9]{1,2}\b"),  # Mailchimp
    ("secret", r"\bsecret_[A-Za-z0-9]{43}\b"),  # Notion
    ("secret", r"\blin_api_[A-Za-z0-9]{40,255}\b"),
    # ─── PEM private keys / JWT ─────────────────────────────────────
    ("secret", r"-----BEGIN (?:RSA|DSA|EC|OPENSSH|PGP) PRIVATE KEY-----"),
    ("secret", r"\beyJ[A-Za-z0-9_\-]{8,2048}\.[A-Za-z0-9_\-]{8,2048}\.[A-Za-z0-9_\-]{8,2048}\b"),
    # ─── Account-number patterns ────────────────────────────────────
    # IBAN (rough — IT, GB, DE, FR, ES)
    # was `[ \t]?` — only ASCII space/tab. PDF / online-banking
    # copy-paste injects U+00A0 NBSP / U+202F narrow no-break / U+2009 thin
    # space between IBAN groups; widened to `\s?` to catch them.
    ("account_number", r"\b[A-Z]{2}\d{2}[A-Z0-9]{1,4}(?:\s?\d{4}){2,5}(?:\s?\d{1,4})?\b"),
    # SSN US
    ("account_number", r"\b\d{3}-\d{2}-\d{4}\b"),
    # Bitcoin Legacy P2PKH (starts with 1, base58, 25-34 chars)
    ("account_number", r"\b1[A-HJ-NP-Za-km-z1-9]{25,34}\b"),
    # Bitcoin P2SH (starts with 3, base58)
    ("account_number", r"\b3[A-HJ-NP-Za-km-z1-9]{25,34}\b"),
    # Bitcoin Bech32 (segwit, bc1...)
    ("account_number", r"\bbc1[a-z0-9]{39,59}\b"),
    # Note: BTC Legacy/P2SH patterns above match by shape; the
    # `regex_recognizer_predictor` post-filter validates the
    # base58check checksum to drop prose tokens that share the shape
    # (e.g. `Order 1A2B3C4D5E6F7G8H9J1K2L3M4N`).
    # Ethereum address (0x prefix + 40 hex)
    ("account_number", r"\b0x[a-fA-F0-9]{40}\b"),
    # UUID v4 (often used as account/customer id)
    ("account_number", r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"),
    # MAC address (hardware identifier).
    # lookbehind/lookahead added so `00:11:22:33:44:55:66`
    # (7-octet bus address) is not mis-matched as a 6-octet MAC.
    ("account_number", r"(?<![:0-9A-Fa-f])[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?![:0-9A-Fa-f])"),
    # IPv4 address — octet-bounded so `version 3.14.15.92`
    # and `package 2.16.840.1.113883` no longer match.
    ("account_number", r"\b(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"),
    # IPv6 standard (8 hex groups separated by colons)
    ("account_number", r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"),
    # IPv6 compressed (with `::` once). Common formats:
    #   ::1, fe80::1, 2001:db8::, 2001:db8::1, ::ffff:1.2.3.4
    # Loose pattern: requires `::` plus enough flanking hex groups.
    ("account_number", r"\b(?:[0-9a-fA-F]{1,4}:){1,7}:|:(?::[0-9a-fA-F]{1,4}){1,7}|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b"),
    # ─── Additional secret patterns (distinct prefix-anchored) ───
    # Google API key
    ("secret", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    # Discord webhook URL
    ("secret", r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+"),
    # Discord bot token
    ("secret", r"\b[MN][A-Za-z\d]{23}\.[\w-]{6}\.[\w-]{27,255}\b"),
    # Telegram bot token (8-10 digit id : 35-char secret)
    ("secret", r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),
    # Mailgun API key
    ("secret", r"\bkey-[a-f0-9]{32}\b"),
    # Mapbox token
    ("secret", r"\bpk\.eyJ1Ijoi[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    # Square access token
    # bound to {200,400} — Square access tokens are 218 chars;
    # unbounded `{200,}` enabled quadratic backtrack on adversarial pad input.
    ("secret", r"\bEAA[A-Za-z0-9_\-]{200,400}\b"),
    # PayPal Braintree access token
    ("secret", r"\baccess_token\$production\$[a-z0-9]{16}\$[a-f0-9]{32}\b"),
    # Heroku API key (UUID-shaped — labelled secret due to context)
    ("secret", r"\bheroku_api_key=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b"),
    # ─── Country-specific national IDs (Presidio-derived, MIT) ────
    # Spanish DNI (8 digits + 1 control letter, no spaces)
    ("account_number", r"\b\d{8}[A-HJ-NP-TV-Z]\b"),
    # Brazilian CPF (XXX.XXX.XXX-XX)
    ("account_number", r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    # US Passport (1 letter + 8 digits, no separator)
    ("account_number", r"\b[A-CEFGHJ-NPR-Z]\d{8}\b"),
    # US EIN (XX-XXXXXXX)
    ("account_number", r"\b\d{2}-\d{7}\b"),
    # Italian Codice Fiscale — 6 alpha + 2 digit + month-letter
    # (one of A-EHLMPRST) + 2 digit day + alpha + 3 digit + control letter.
    # Comment claimed it was added; the pattern was missing.
    ("account_number", r"\b[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]\b"),
    # ─── Phone — international format anchored on `+` ──────────────
    # `+CC NNN NNN NNNN` / `+CC-NNN-NNN-NNNN` / `+CC NNNNNNNNNN` etc.
    # Anchored on the leading `+` to avoid matching version strings,
    # IDs, etc. that have similar digit groupings.
    ("private_phone", r"\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{3,8}"),
    # domestic formats with REQUIRED context anchor.
    # Initial unanchored variants (`\b0\d{1,2}...`, `\b[6-9]\d{2}...`)
    # had massive false-positive rate on nullpii-bench (17 + 6 FP, 0
    # in gold) because they overlap with credit-card / SSN digit
    # groups. Anchored to a leading phone-context token so they only
    # fire on explicit phone fields, e.g. `Tel: 02 3456789` /
    # `Teléfono 612 345 678`.
    ("private_phone",
     r"(?i)\b(?:tel|telefono|phone|cell|cellulare|mobile)[\s:.]+"
     r"(0\d{1,2}[\s\-.]?\d{6,9})\b"),
    ("private_phone",
     r"(?i)\b(?:tel|t[eé]l[eé]phone|portable|mobile|gsm)[\s:.]+"
     r"(0[1-9](?:[\s\-.]?\d{2}){4})\b"),
    ("private_phone",
     r"(?i)\b(?:tel|tel[eé]fono|m[oó]vil|cell|cellular|phone)[\s:.]+"
     r"([6-9]\d{2}[\s\-.]?\d{3}[\s\-.]?\d{2}[\s\-.]?\d{2})\b"),
]


# Public-domain whitelist for URL filtering. Matches against the
# *host* of a detected URL. URLs whose host ends in any of these
# suffixes are dropped — they are public references (search engines,
# code hosts, package registries, OS vendors, social platforms,
# canonical docs sites), not PII. The filter is conservative: only
# adds 30-50 well-known suffixes; anything else still gets flagged.
PUBLIC_URL_HOSTS: tuple[str, ...] = (
    "google.com", "google.de", "google.fr", "google.it", "google.co.uk",
    "youtube.com", "youtu.be",
    "github.com", "github.io", "githubusercontent.com",
    "gitlab.com", "bitbucket.org",
    "stackoverflow.com", "stackexchange.com", "askubuntu.com",
    "microsoft.com", "msdn.microsoft.com", "docs.microsoft.com", "learn.microsoft.com",
    "apple.com", "developer.apple.com", "support.apple.com",
    "mozilla.org", "developer.mozilla.org", "mdn.io",
    "wikipedia.org", "wikimedia.org",
    "npmjs.com", "npmjs.org", "yarnpkg.com",
    "pypi.org", "pypi.python.org", "readthedocs.io",
    "crates.io", "rust-lang.org", "docs.rs",
    "go.dev", "golang.org", "pkg.go.dev",
    "nodejs.org", "deno.land",
    "redhat.com", "ubuntu.com", "debian.org", "archlinux.org",
    "amazon.com", "aws.amazon.com", "docs.aws.amazon.com",
    "cloudflare.com", "developers.cloudflare.com",
    "twitter.com", "x.com", "facebook.com", "linkedin.com",
    "reddit.com", "medium.com", "dev.to",
    "huggingface.co", "openai.com", "anthropic.com",
    "stripe.com", "twilio.com",
)


# re-finditer over `https?://` inside an outer URL match,
# so that `https://outer.com/?next=https://inner.private/...` returns
# both URLs and the whitelist filter checks each independently.
_NESTED_URL_RE = re.compile(r"https?://[^\s<>\"]+")


def url_filter_predictor(*, patterns: list[tuple[str, str]]) -> Predictor:
    """Wraps a regex pack with a host-based public-URL whitelist.

    Same semantics as `regex_recognizer_predictor`, but for any matched
    span labelled `private_url`, parses the URL host and drops the span
    if the host ends in one of `PUBLIC_URL_HOSTS`. Spans with other
    labels pass through unchanged.

    Used in the production ensemble so the URL regex can stay broad
    (catches `https://admin.dev/`, `http://10.0.0.5/`, `https://internal-
    api.example.test/`) while still dropping the obvious-not-PII case
    of public docs / package registries / search engines etc.
    """
    import re as _re
    from urllib.parse import urlparse

    compiled = [(label, _re.compile(pat)) for label, pat in patterns]

    def _is_public(span_text: str) -> bool:
        try:
            host = urlparse(
                span_text if "://" in span_text else f"http://{span_text}",
            ).hostname
        except (ValueError, TypeError):
            return False
        if not host:
            return False
        host = host.lower()
        return any(host == h or host.endswith("." + h) for h in PUBLIC_URL_HOSTS)

    def _all_urls_public(span_text: str) -> bool:
        """when a single URL match contains query-param URLs
        (e.g. OAuth/redirect chains), require ALL embedded URLs to be
        public for the whole match to be dropped. A greedy `https?://…`
        match like `https://github.com/?next=https://victim.private/...`
        previously had its public outer host (github.com) dominate the
        whitelist check, silently leaking the private inner URL.
        """
        urls = _NESTED_URL_RE.findall(span_text)
        if len(urls) <= 1:
            return _is_public(span_text)
        return all(_is_public(u) for u in urls)

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        scores: list[float] = []
        for label, regex in compiled:
            prior = REGEX_LABEL_PRIORS.get(label, 0.9)
            for m in regex.finditer(text):
                if label == "private_url" and _all_urls_public(m.group()):
                    continue
                spans.append(Span(label, m.start(), m.end()))
                scores.append(prior)
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(spans, elapsed, scores=tuple(scores))

    return _predict


# Alias retained for bench-harness import compatibility — identical to
# `DEFAULT_REGEX_PATTERNS`. New code should reference the default name.
EXTENDED_REGEX_PATTERNS: list[tuple[str, str]] = DEFAULT_REGEX_PATTERNS


# Minimal universal-only regex pack — paired with the v8 multi-domain
# fine-tune in the `legal` / `medical` profiles. Strips the cloud /
# SaaS / crypto / national-ID patterns from `DEFAULT_REGEX_PATTERNS`
# (irrelevant noise on legal & medical text) and keeps only the
# universally non-controversial patterns: URL, email, IBAN, US SSN,
# IPv4/IPv6, and international phone. The v8 backbone handles
# PERSON / DATETIME / LOC / ORG / national-ID directly via ML, so
# regex coverage of those domains would just add false positives.
MINIMAL_REGEX_PATTERNS: list[tuple[str, str]] = [
    # URL
    ("private_url", r"\b(?:https?://|www\.)[^\s<>\"]+"),
    # Email
    ("private_email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    # IDN-aware pattern `(?<!\w)[\w.%+\-]+@[\w.\-]
    # +\.[\w]{2,24}(?!\w)` produced 336 FP / 500 matches on
    # nullpii-bench (Unicode `\w` matched arbitrary identifier-like
    # strings as email local parts). IDN coverage is now handled by
    # `_normalize_for_detection` (NFKC + unidecode) which converts
    # `john@münchen.de` → `john@munchen.de`, allowing the ASCII
    # pattern to match. True non-Latin emails (`用户@例え.jp`) remain
    # uncovered until a more restrictive Unicode pattern is designed.
    # IBAN (rough — IT, GB, DE, FR, ES)
    # was `[ \t]?` — only ASCII space/tab. PDF / online-banking
    # copy-paste injects U+00A0 NBSP / U+202F narrow no-break / U+2009 thin
    # space between IBAN groups; widened to `\s?` to catch them.
    ("account_number", r"\b[A-Z]{2}\d{2}[A-Z0-9]{1,4}(?:\s?\d{4}){2,5}(?:\s?\d{1,4})?\b"),
    # SSN US
    ("account_number", r"\b\d{3}-\d{2}-\d{4}\b"),
    # IPv4
    ("account_number", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    # IPv6 standard
    ("account_number", r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"),
    # IPv6 compressed (`::` once)
    ("account_number", r"\b(?:[0-9a-fA-F]{1,4}:){1,7}:|:(?::[0-9a-fA-F]{1,4}){1,7}|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b"),
    # Phone — international format anchored on `+`
    ("private_phone", r"\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{3,8}"),
    # domestic formats with REQUIRED context anchor.
    # Initial unanchored variants (`\b0\d{1,2}...`, `\b[6-9]\d{2}...`)
    # had massive false-positive rate on nullpii-bench (17 + 6 FP, 0
    # in gold) because they overlap with credit-card / SSN digit
    # groups. Anchored to a leading phone-context token so they only
    # fire on explicit phone fields, e.g. `Tel: 02 3456789` /
    # `Teléfono 612 345 678`.
    ("private_phone",
     r"(?i)\b(?:tel|telefono|phone|cell|cellulare|mobile)[\s:.]+"
     r"(0\d{1,2}[\s\-.]?\d{6,9})\b"),
    ("private_phone",
     r"(?i)\b(?:tel|t[eé]l[eé]phone|portable|mobile|gsm)[\s:.]+"
     r"(0[1-9](?:[\s\-.]?\d{2}){4})\b"),
    ("private_phone",
     r"(?i)\b(?:tel|tel[eé]fono|m[oó]vil|cell|cellular|phone)[\s:.]+"
     r"([6-9]\d{2}[\s\-.]?\d{3}[\s\-.]?\d{2}[\s\-.]?\d{2})\b"),
]


# Universal-non-PII constants — RFC-reserved technical values that
# can never be real PII regardless of context. Identified from the
# adversarial-bench `decoys` subset (480-sample suite testing FP rate
# on infrastructure-like patterns: loopback IPs, broadcast MACs, null
# UUIDs, etc.). NOT bench-failure-derived for `nullpii-bench` — these
# are RFC-defined reserved values that never identify a person.
#
# Excluded on purpose:
# - RFC1918 private ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
#   can be PII when shared in a prompt (internal-network identifier)
# - 555-prefix phones — fictional convention but not RFC-defined
# - Specific UUID-zero variants beyond the canonical all-zero
NEVER_PII_CONSTANTS: frozenset[str] = frozenset({
    # IPv4 reserved
    "0.0.0.0",
    "127.0.0.1",
    "255.255.255.255",
    # IPv6 reserved
    "::",
    "::1",
    "ff02::1",
    "ff02::2",
    # MAC reserved (zero + broadcast)
    "00:00:00:00:00:00",
    "ff:ff:ff:ff:ff:ff",
    # UUID null (RFC 4122 nil UUID)
    "00000000-0000-0000-0000-000000000000",
})


# RFC 6761 reserved special-use domains. Hostnames in these zones are
# universally non-PII by IETF reservation — never resolve to real
# people, organisations or services. Match-by-suffix on hostname.
NEVER_PII_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "localhost",
    ".localhost",
    ".test",
    ".example",
    ".invalid",
    ".example.com",
    ".example.net",
    ".example.org",
)

# NANP fictional phone prefix. Only the subscriber range 555-0100
# through 555-0199 is universally fictional per ITU-T E.164. Matching
# all `555-XXXX` would drop legitimate `1-555-XXX-XXXX` calls in
# regions that publish 555-numbers as real subscriber lines.
import re as _NEVER_PII_RE
_NANP_555_FICTIONAL = _NEVER_PII_RE.compile(
    r"^[+]?\s*1?\s*[(]?555[)]?[\s\-.]*01\d{2}(?:[\s\-.]*\d{0,4})?$",
)


def _is_private_or_link_local_ip(s: str) -> bool:
    """True if `s` is a syntactically-valid IP address in an RFC1918
    private range (10/8, 172.16/12, 192.168/16), the RFC 6598 shared
    range (100.64/10), an IPv6 ULA (fc00::/7), or a link-local range
    (169.254/16, fe80::/10). Wraps `ipaddress` stdlib classification."""
    import ipaddress
    try:
        ip = ipaddress.ip_address(s.strip())
    except (ValueError, TypeError):
        return False
    return bool(ip.is_private) or bool(ip.is_link_local)


_OBFUSCATION_CHARS = frozenset("​‌‍﻿­")  # zero-width + soft-hyphen


def _has_valid_tld(host: str) -> bool:
    """Best-effort check that `host` has a syntactically-valid TLD.

    Valid TLD per ICANN rules:
      - hostname contains at least one `.`
      - last label (TLD) is ≥ 2 characters
      - TLD is all alphabetic (legacy ASCII TLDs) OR starts with `xn--`
        (IDN punycode encoding for non-Latin TLDs like `.中国`)

    Returns False for hostnames with no `.` (`noreply`), single-char
    TLDs (`y.z`), or TLDs containing digits/symbols. Only does
    syntactic validation — does NOT verify against IANA registry, so
    syntactically-valid but unallocated TLDs (e.g. `.invalid` — caught
    separately as RFC 6761 reserved) still pass this check.

    Conservative: returns True (= valid, don't drop) when host contains
    any non-ASCII character (homoglyph attack or pre-encoded IDN) or
    zero-width / soft-hyphen obfuscation chars. Those are real PII
    attempting to evade detection — leave them to other layers, not
    the TLD checker.
    """
    if any(ord(c) > 127 or c in _OBFUSCATION_CHARS for c in host):
        return True
    if "." not in host:
        return False
    tld = host.rsplit(".", 1)[1]
    if len(tld) < 2:
        return False
    if tld.startswith("xn--"):
        return True
    return tld.isalpha()


def _is_never_pii(
    text_span: str,
    *,
    label: str | None = None,
    drop_rfc1918: bool = False,
) -> bool:
    """Universal-non-PII test for a span surface form. Returns True if
    the span is an RFC-reserved technical constant (loopback/broadcast
    IPs, zero MACs, null UUIDs, RFC 6761 reserved domains, NANP
    fictional phone numbers) or has a syntactically-invalid TLD when
    the predicted label is `private_email` / `private_url`.

    With `drop_rfc1918=True`, additionally drops any IP in RFC1918
    private ranges (10/8, 172.16/12, 192.168/16) plus link-local
    (169.254/16, fe80::/10) and ULA (fc00::/7). Off by default — those
    ranges can carry internal-network PII when shared in a prompt."""
    s = text_span.strip().lower()
    if s in NEVER_PII_CONSTANTS:
        return True
    if drop_rfc1918 and _is_private_or_link_local_ip(s):
        return True
    # Hostname (URL or email host part) ending in a reserved suffix.
    # Strip scheme/path — we only need the host segment.
    candidate_host: str | None = None
    if "://" in s:
        # URL: extract authority
        rest = s.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
        candidate_host = rest
    elif "@" in s:
        # Email: extract domain
        candidate_host = s.split("@", 1)[1].split(":", 1)[0]
    elif ":" in s and s.count(":") == 1:
        # `localhost:5432`-style host:port without scheme
        candidate_host = s.split(":", 1)[0]
    else:
        candidate_host = s
    if candidate_host:
        for suffix in NEVER_PII_DOMAIN_SUFFIXES:
            if candidate_host == suffix.lstrip(".") or candidate_host.endswith(suffix):
                return True
    # TLD validity check — applies only to email + URL labels.
    if label in ("private_email", "private_url") and candidate_host:
        # Skip IP-address hostnames (validity check applies to domains).
        try:
            import ipaddress
            ipaddress.ip_address(candidate_host)
        except (ValueError, TypeError):
            if not _has_valid_tld(candidate_host):
                return True
    if _NANP_555_FICTIONAL.match(s):
        return True
    return False


def never_pii_filter_predictor(
    *,
    inner: Predictor,
    drop_rfc1918: bool = False,
) -> Predictor:
    """Drops predicted spans whose surface form is an RFC-reserved
    technical constant or an IETF-reserved special-use identifier:

      - `NEVER_PII_CONSTANTS` (loopback/broadcast IPs, zero MACs,
        null UUID — RFC reserved values)
      - hostnames ending in `localhost` / `.test` / `.example` /
        `.invalid` (RFC 6761 special-use domains)
      - phone numbers in the NANP `555` fictional block (ITU-T E.164)

    With `drop_rfc1918=True` (opt-in), additionally drops any IP in
    RFC1918 private ranges + link-local + ULA. Off by default since
    those ranges can carry internal-network PII (e.g. `10.0.0.5` may
    identify a specific dev VM in a corporate prompt). Enable when
    the workload is consumer-facing (no internal-IP PII expected)."""

    def _predict(text: str) -> ToolResult:
        result = inner(text)
        kept = [
            sp for sp in result.spans
            if not _is_never_pii(
                text[sp.start:sp.end], label=sp.label, drop_rfc1918=drop_rfc1918,
            )
        ]
        return ToolResult(kept, result.elapsed_ms)

    return _predict


# Per-label stopword filter — drops spans whose surface form matches a
# known universally-non-PII word. Conservative: only entries that are
# never PII regardless of schema or context.
#
# Excluded on purpose (schema-dependent or borderline):
# - demographic terms (male, female) — quasi-identifier under GDPR
# - relationship words (patient, client) — sensitive in healthcare
# - job/political titles (engineer, governor, mayoress) — PII when
#   prefixed to a name in employment / legal records
# - generic articles (other) — context-dependent
STOPWORD_BY_LABEL: dict[str, frozenset[str]] = {
    "private_person": frozenset({"i"}),  # pronoun, never PII
    "private_email": frozenset({"email"}),  # noun, never an address
    "private_phone": frozenset({
        "phone", "smartphone", "cellphone", "mobile", "cellular",
    }),  # nouns, never numbers
    "secret": frozenset({"confidentiality", "assets"}),  # abstract nouns
}


# Anchor texts per PII label, used by the zero-shot semantic verifier.
# Derived from category definitions (what each label means in the
# nullpii 8-category schema), NOT from bench-failure analysis. The
# verifier embeds each predicted span's local context and compares
# the cosine similarity to the label's anchor list; spans whose
# context is far from the label's semantic neighbourhood are dropped.
PII_ANCHOR_TEXTS: dict[str, list[str]] = {
    "secret": [
        "an API secret key",
        "an access token",
        "a password",
        "a private credential",
        "a JWT bearer token",
        "an SSH or PEM private key",
    ],
    "private_email": [
        "an email address",
        "a personal email contact",
    ],
    "private_url": [
        "a private web URL",
        "an internal admin link",
    ],
    "private_phone": [
        "a telephone phone number",
        "a mobile phone contact",
    ],
    "account_number": [
        "a bank account number",
        "an IBAN code",
        "a social security number",
        "an IP address",
        "a MAC hardware address",
        "a cryptocurrency wallet address",
        "a credit card number",
    ],
    "private_address": [
        "a street address",
        "a city or postal location",
        "a country region or zip code",
    ],
    "private_date": [
        "a date of birth",
        "a calendar date",
    ],
    "private_person": [
        "a person full name",
        "a personal first name and surname",
    ],
}


def multi_ensemble_predictor(
    *,
    predictors: list[Predictor],
    strategy: str = "primary",
    score_min: float = 0.5,
) -> Predictor:
    """Generic N-way ensemble. Four strategies:

    - **primary**: predictors[0] wins, others fill non-overlapping gaps.
      Pre-iter-v7 default; +0.046 F1 vs primary alone in 11-dataset bench.
    - **union**: all spans, longest-wins on overlap. Higher recall, more
      false positives. Lost vs primary by -0.026 in iter-15.
    - **score_ranked**: score-based overlap resolver. All predicted spans
      are pooled with their per-span scores (model confidence for ML
      predictors, per-label prior `REGEX_LABEL_PRIORS` for regex). Sorted
      by score descending; iterate keep-or-drop based on overlap with
      already-kept spans. Spans below `score_min` are dropped outright.
      Generalist alternative to `primary` — addresses the FP cascade on
      structured-PII templates where regex over-fires while preserving
      regex wins on distinctive structural patterns.
    - **confidence_max**: like `score_ranked` but does NOT filter by
      `score_min` — every predicted span is eligible, only the
      overlap-resolution step uses the per-span confidence (highest
      score keeps; ties broken by length, then by predictor order).
      Used by the v6/v8 ensemble where both predictors already apply
      their own threshold and we want to preserve every prediction.
    """
    if strategy not in {"union", "primary", "score_ranked", "confidence_max"}:
        raise ValueError(f"unknown strategy: {strategy}")
    if not predictors:
        raise ValueError("at least one predictor required")

    def _overlaps(a: Span, b: Span) -> bool:
        return a.start < b.end and b.start < a.end

    def _dedupe_longest(spans: list[Span]) -> list[Span]:
        if len(spans) <= 1:
            return spans
        sorted_spans = sorted(spans, key=lambda s: (s.start, -s.end))
        out: list[Span] = []
        for s in sorted_spans:
            replaced = False
            for i in range(len(out) - 1, -1, -1):
                prev = out[i]
                if prev.end <= s.start:
                    break
                if not _overlaps(prev, s):
                    continue
                if prev.label != s.label:
                    continue
                if (s.end - s.start) > (prev.end - prev.start):
                    out[i] = s
                replaced = True
                break
            if not replaced:
                out.append(s)
        return sorted(out, key=lambda s: s.start)

    def _merge_union(spans_per_tool: list[list[Span]]) -> list[Span]:
        flat: list[Span] = []
        for spans in spans_per_tool:
            flat.extend(spans)
        return _dedupe_longest(flat)

    def _merge_primary(spans_per_tool: list[list[Span]]) -> list[Span]:
        primary = list(spans_per_tool[0])
        for other_spans in spans_per_tool[1:]:
            for s in other_spans:
                if any(_overlaps(s, p) for p in primary):
                    continue
                primary.append(s)
        return sorted(primary, key=lambda s: s.start)

    def _merge_score_ranked(
        results: list[ToolResult],
    ) -> list[Span]:
        scored: list[tuple[float, Span]] = []
        for r in results:
            spans = list(r.spans)
            scores = list(r.scores) if r.scores else [1.0] * len(spans)
            if len(scores) != len(spans):
                # Mismatch (e.g. a wrapper that mutated spans without
                # adjusting scores) — fall back to neutral 1.0 priors.
                scores = [1.0] * len(spans)
            for sp, sc in zip(spans, scores, strict=False):
                if sc < score_min:
                    continue
                scored.append((sc, sp))
        scored.sort(key=lambda x: x[0], reverse=True)
        kept: list[Span] = []
        for _sc, sp in scored:
            if any(_overlaps(sp, k) for k in kept):
                continue
            kept.append(sp)
        return sorted(kept, key=lambda s: s.start)

    def _merge_confidence_max(
        results: list[ToolResult],
    ) -> list[Span]:
        # Like score_ranked but does NOT filter by `score_min` (every
        # span is eligible). Tie-break: higher score, then longer span,
        # then earlier predictor index.
        # Sort key is a (sc, length, -tool_idx) tuple — Span is not in
        # the key so no fallback comparison on un-orderable Span objects.
        scored: list[tuple[tuple[float, int, int], Span]] = []
        for tool_idx, r in enumerate(results):
            spans = list(r.spans)
            scores = list(r.scores) if r.scores else [1.0] * len(spans)
            if len(scores) != len(spans):
                scores = [1.0] * len(spans)
            for sp, sc in zip(spans, scores, strict=False):
                length = sp.end - sp.start
                scored.append(((sc, length, -tool_idx), sp))
        scored.sort(key=lambda x: x[0], reverse=True)
        kept: list[Span] = []
        for _key, sp in scored:
            if any(_overlaps(sp, k) for k in kept):
                continue
            kept.append(sp)
        return sorted(kept, key=lambda s: s.start)

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        results = [pred(text) for pred in predictors]
        if strategy == "score_ranked":
            merged = _merge_score_ranked(results)
        elif strategy == "confidence_max":
            merged = _merge_confidence_max(results)
        else:
            spans_per_tool = [list(r.spans) for r in results]
            merger = {"union": _merge_union, "primary": _merge_primary}[strategy]
            merged = merger(spans_per_tool)
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(merged, elapsed)

    return _predict


_DEV_PASTE_SIGNALS = (
    "```",  # markdown fenced code
    "function ",
    "const ",
    "import ",
    "from ",  # python imports / SQL / etc.
    "def ",
    "class ",
    "return ",
    "console.",
    "print(",
    "throw ",
    "try {",
    "catch (",
    "=>",
    "===",
    "!==",
    "</",
    "/>",
    "<html",
    "<div",
    "<script",
    "Traceback",
    "Error:",
    "Exception:",
    "stderr",
    "stdout",
    "$ ",
    "# ",
    "//",
    "/*",
    "*/",
    "npm ",
    "yarn ",
    "pip ",
    "git ",
    "docker ",
    "kubectl ",
    "ssh ",
    "curl ",
    "http://",
    "https://",
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "ENV[",
    "process.env",
    "TODO",
    "FIXME",
    "NOTE:",
    "DEBUG",
    "INFO",
    "WARN",
    "ERROR",
)

_LEGAL_FORMAL_SIGNALS = (
    "the Court",
    "the Tribunal",
    "Article ",
    "Article ",
    "Defendant",
    "Plaintiff",
    "Applicant",
    "Respondent",
    "the Government",
    "Whereas",
    "WHEREAS",
    "hereby",
    "pursuant to",
    "in accordance with",
    "Convention",
    "judgment",
    "Judgment",
    "paragraph ",
    "ECHR",
    "European Court",
    "Human Rights",
    "Section ",
    "section ",
    "subsection",
    "the Chamber",
    "Grand Chamber",
    # Honorifics ("Mr ", "Mrs ", "Ms ") deliberately omitted — they
    # appear in dev-paste customer-support text and would false-route
    # that content to the v8 backbone.
    # ─── Italian ────────────────────────────────────────────────
    "la Corte",
    "il Tribunale",
    "Articolo ",
    "Imputato",
    "Ricorrente",
    "Resistente",
    "il Governo",
    "Considerato che",
    "in conformità",
    "Convenzione",
    "sentenza",
    "Sentenza",
    "paragrafo ",
    "Grande Camera",
    "comma ",
    # ─── French ─────────────────────────────────────────────────
    "la Cour",
    "le Tribunal",
    "Article premier",
    "Défendeur",
    "Demandeur",
    "Requérant",
    "le Gouvernement",
    "Attendu que",
    "conformément",
    "Convention européenne",
    "arrêt",
    "Arrêt",
    "paragraphe ",
    "la Chambre",
    "Grande Chambre",
    "Considérant",
    # ─── German ─────────────────────────────────────────────────
    "der Gerichtshof",
    "das Gericht",
    "Artikel ",
    "Beschwerdeführer",
    "Antragsteller",
    "Beklagte",
    "die Regierung",
    "Im Hinblick auf",
    "gemäß",
    "Konvention",
    "Urteil",
    "Absatz ",
    "die Kammer",
    "Große Kammer",
    "Erwägungsgrund",
    # ─── Spanish ────────────────────────────────────────────────
    "el Tribunal",
    "la Sala",
    "Artículo ",
    "Demandante",
    "Demandado",
    "Recurrente",
    "el Gobierno",
    "Considerando",
    "conforme a",
    "Convenio",
    "sentencia",
    "Sentencia",
    "apartado ",
    "Gran Sala",
)


def _is_dev_paste_like(text: str) -> bool:
    """Heuristic: classify `text` as dev-paste-style (returns True) vs.
    structured/legal/formal (returns False).

    Used by the `complementary` strategy of the v6/v8 ensemble to route
    each input to the better-suited backbone. Heuristic features are
    fixed a priori — DO NOT tune on bench eval datasets.

    Signals are simple substring counts:
    - dev-paste signals: code fences, language keywords, shell output,
      common log/error markers, URL schemes, loopback IPs.
    - legal/formal signals: court/tribunal vocabulary, treaty/section
      references, formal honorifics with non-breaking spaces.

    Tie / no-signal default: dev-paste (matches the historical primary
    use case for nullpii — paste-into-LLM dev workflow).
    """
    if not text:
        return True
    sample = text[:8000]
    dev_hits = sum(1 for s in _DEV_PASTE_SIGNALS if s in sample)
    legal_hits = sum(1 for s in _LEGAL_FORMAL_SIGNALS if s in sample)
    if dev_hits == 0 and legal_hits == 0:
        # No signal either way — fall back on length + alpha density.
        # Long, prose-heavy text without dev signals → treat as formal.
        if len(sample) > 1500:
            alpha = sum(1 for c in sample if c.isalpha())
            if alpha / max(len(sample), 1) > 0.7:
                return False
        return True
    return dev_hits >= legal_hits


_NULLPII_8 = [
    # The 8 ML-trained categories. Retained as an explicit constant so
    # bench scripts that want the trained-only baseline (e.g. ablation
    # studies or `openai/privacy-filter` parity) can request it directly.
    "account_number",
    "private_address",
    "private_date",
    "private_email",
    "private_person",
    "private_phone",
    "private_url",
    "secret",
]

# Canonical 12-class inference prompt set — mirrors `GLINER_LABELS`
# in `src/nullpii.ts` (the 8 trained labels + 4 zero-shot extras the
# base model generalises to). Default for `gliner_v2_predictor` so the
# bench harness prompts nullpii's wrapped GLiNER with the same vocabulary
# users get in production.
_NULLPII_LABELS = [
    *_NULLPII_8,
    "private_passport",
    "private_driver_license",
    "private_vehicle_id",
    "private_geolocation",
]

# ─── GLiNER competitors: prompted with their cards' vocabularies ───
# GLiNER embeds each label string, so the strings matter. Rule change 10:
# each model is prompted with the label strings its card documents, plus
# zero-shot extras only for gold concepts that list lacks, listed apart and
# disclosed. Each map follows the SYMMETRY RULE of `_NEMOTRON_TOKEN_LABEL_MAP`:
# a label maps to X iff our gold loaders map the same concept to X, and to
# None where the gold has no such category.

# knowledgator/gliner-pii-large-v1.0 card, its five "predefined PII
# categories" lists, plus the labels the sibling gliner-stream-pii-v1.0
# card prompts with ("person", "street address", "credit card number").
_KNOWLEDGATOR_CARD_LABELS = [
    # personal_labels
    "name", "first name", "last name", "name medical professional", "dob", "age", "gender", "marital status",
    # contact_labels
    "email address", "phone number", "ip address", "url", "location address", "location street",
    "location city", "location state", "location country", "location zip",
    # financial_labels
    "account number", "bank account", "routing number", "credit card", "credit card expiration", "cvv", "ssn", "money",
    # healthcare_labels
    "condition", "medical process", "drug", "dose", "blood type", "injury", "organization medical facility",
    "healthcare number", "medical code",
    # id_labels
    "passport number", "driver license", "username", "password", "vehicle id",
    # gliner-stream-pii-v1.0 card
    "person", "street address", "credit card number",
]
# Gold concepts the knowledgator lists lack: dates other than birth dates,
# times, MAC addresses, API keys and GPS coordinates.
_KNOWLEDGATOR_EXTRA_LABELS = ["date", "time", "mac address", "api key", "gps coordinate"]
_KNOWLEDGATOR_LABELS = _KNOWLEDGATOR_CARD_LABELS + _KNOWLEDGATOR_EXTRA_LABELS

_KNOWLEDGATOR_TO_NULLPII: dict[str, str | None] = {
    "name": "private_person",
    "first name": "private_person",
    "last name": "private_person",
    "name medical professional": "private_person",
    "person": "private_person",
    "username": "private_person",           # gold USERNAME
    "dob": "private_date",
    "date": "private_date",
    "time": "private_date",                 # gold TIME
    "credit card expiration": "private_date",
    "email address": "private_email",
    "phone number": "private_phone",
    "ip address": "private_ip",
    "mac address": "private_mac",
    "url": "private_url",
    "location address": "private_address",
    "location street": "private_address",
    "location city": "private_address",
    "location state": "private_address",
    "location country": "private_address",  # gold COUNTRY
    "location zip": "private_address",
    "street address": "private_address",
    "gps coordinate": "private_geolocation",
    "account number": "account_number",
    "bank account": "account_number",
    "routing number": "account_number",
    "credit card": "account_number",
    "credit card number": "account_number",
    "cvv": "account_number",                # gold CREDITCARDCVV
    "ssn": "account_number",
    "healthcare number": "account_number",  # as health_plan_beneficiary_number
    "passport number": "private_passport",
    "driver license": "private_driver_license",
    "vehicle id": "private_vehicle_id",
    "password": "secret",
    "api key": "secret",
    # ─── Dropped: no gold category ───────────────────────────────
    "age": None,
    "gender": None,
    "marital status": None,
    "money": None,
    "condition": None,
    "medical process": None,
    "drug": None,
    "dose": None,
    "blood type": None,
    "injury": None,
    "organization medical facility": None,
    "medical code": None,
}

# urchade/gliner_multi_pii-v1 card: "including but not limited to these
# entity types", in the card's order and spelling (its two snake_case
# duplicates included). Served by onnx-community/gliner_multi_pii-v1.
_URCHADE_CARD_LABELS = [
    "person", "organization", "phone number", "address", "passport number", "email", "credit card number",
    "social security number", "health insurance id number", "date of birth", "mobile phone number",
    "bank account number", "medication", "cpf", "driver's license number", "tax identification number",
    "medical condition", "identity card number", "national id number", "ip address", "email address", "iban",
    "credit card expiration date", "username", "health insurance number", "registration number",
    "student id number", "insurance number", "flight number", "landline phone number", "blood type", "cvv",
    "reservation number", "digital signature", "social media handle", "license plate number", "cnpj",
    "postal code", "passport_number", "serial number", "vehicle registration number", "credit card brand",
    "fax number", "visa number", "insurance company", "identity document number", "transaction number",
    "national health insurance number", "cvc", "birth certificate number", "train ticket number",
    "passport expiration date", "social_security_number",
]
# Gold concepts the urchade list lacks: dates other than birth and expiry
# dates, times, URLs, MAC addresses, passwords, API keys, GPS coordinates.
_URCHADE_EXTRA_LABELS = ["date", "time", "url", "mac address", "password", "api key", "gps coordinate"]
_URCHADE_LABELS = _URCHADE_CARD_LABELS + _URCHADE_EXTRA_LABELS

_URCHADE_TO_NULLPII: dict[str, str | None] = {
    "person": "private_person",
    "username": "private_person",                    # gold USERNAME
    "social media handle": "private_person",         # a username
    "phone number": "private_phone",
    "mobile phone number": "private_phone",
    "landline phone number": "private_phone",
    "fax number": "private_phone",                   # gold FAX
    "address": "private_address",
    "postal code": "private_address",
    "email": "private_email",
    "email address": "private_email",
    "ip address": "private_ip",
    "mac address": "private_mac",
    "url": "private_url",
    "date of birth": "private_date",
    "date": "private_date",
    "time": "private_date",
    "credit card expiration date": "private_date",
    "passport expiration date": "private_date",
    "gps coordinate": "private_geolocation",
    "passport number": "private_passport",
    "passport_number": "private_passport",
    "driver's license number": "private_driver_license",
    "license plate number": "private_vehicle_id",
    "vehicle registration number": "private_vehicle_id",
    "credit card number": "account_number",
    "social security number": "account_number",
    "social_security_number": "account_number",
    "health insurance id number": "account_number",
    "health insurance number": "account_number",
    "national health insurance number": "account_number",
    "insurance number": "account_number",
    "bank account number": "account_number",
    "iban": "account_number",
    "cvv": "account_number",
    "cvc": "account_number",
    "cpf": "account_number",                         # national tax id, gold TAXNUM
    "cnpj": "account_number",
    "tax identification number": "account_number",
    "identity card number": "account_number",        # gold IDCARDNUM
    "national id number": "account_number",
    "identity document number": "account_number",
    "visa number": "account_number",
    "birth certificate number": "account_number",
    "student id number": "account_number",           # as employee_id / customer_id
    "password": "secret",
    "api key": "secret",
    # ─── Dropped: no gold category ───────────────────────────────
    "organization": None,
    "medication": None,
    "medical condition": None,
    "blood type": None,
    # Identifiers of a person's records, documents or devices, as
    # nemotron's unique_id / device_identifier: masked, not dropped.
    "registration number": "account_number",
    "reservation number": "account_number",
    "serial number": "account_number",
    "transaction number": "account_number",
    "train ticket number": "account_number",
    "digital signature": "secret",                   # a credential, as biometric_identifier
    # ─── Dropped: no gold category, or one nullpii's core regime disables
    "flight number": None,                           # a public timetable code, not a person's
    "credit card brand": None,                       # gold CARDISSUER is ignored
    "insurance company": None,                       # an organisation
}

# Expanded inference-time prompt set. GLiNER is prompt-based (model
# interprets the semantic meaning of each label string), so we can
# query with finer-grained labels at inference and map back to the
# 12-class schema for output. Goal: lift recall on Nemotron-style
# US-business records (`cvv`, `swift_bic`, `health_plan_beneficiary_
# number`, `coordinate`, `vehicle_identifier`, etc.) without retraining.
_NULLPII_EXPANDED_PROMPTS = [
    # private_person family
    "private_person", "first name", "last name", "full name",
    # private_email
    "private_email", "email address",
    # private_phone
    "private_phone", "phone number",
    # private_address
    "private_address", "street address", "postal code", "city",
    "country", "GPS coordinate",
    # private_date
    "private_date", "date of birth",
    # private_url
    "private_url", "website url",
    # account_number — fine-grained
    "account_number", "social security number", "credit card number",
    "IBAN", "SWIFT code", "CVV", "passport number", "driver license",
    "medical record number", "vehicle VIN", "license plate",
    "MAC address", "IP address",
    # secret
    "secret", "password", "PIN code", "API key",
]

_EXPANDED_PROMPT_TO_NULLPII8 = {
    "private_person": "private_person",
    "first name": "private_person",
    "last name": "private_person",
    "full name": "private_person",
    "private_email": "private_email",
    "email address": "private_email",
    "private_phone": "private_phone",
    "phone number": "private_phone",
    "private_address": "private_address",
    "street address": "private_address",
    "postal code": "private_address",
    "city": "private_address",
    "country": "private_address",
    "GPS coordinate": "private_geolocation",
    "private_date": "private_date",
    "date of birth": "private_date",
    "private_url": "private_url",
    "website url": "private_url",
    "account_number": "account_number",
    "social security number": "account_number",
    "credit card number": "account_number",
    "IBAN": "account_number",
    "SWIFT code": "account_number",
    "CVV": "account_number",
    "passport number": "private_passport",
    "driver license": "private_driver_license",
    "medical record number": "account_number",
    "vehicle VIN": "private_vehicle_id",
    "license plate": "private_vehicle_id",
    "MAC address": "private_mac",
    "IP address": "private_ip",
    "secret": "secret",
    "password": "secret",
    "PIN code": "secret",
    "API key": "secret",
}

# nvidia/gliner-PII is prompted with the 55 Nemotron-PII types, in the order
# of NVIDIA's own serving default (`DEFAULT_LABELS` in NeMo Guardrails,
# examples/deployment/gliner_server/src/gliner_server/pii_utils.py @ af242f0).
# Its predictions map through `_NEMOTRON_TOKEN_LABEL_MAP`, the map of the
# four Nemotron-trained token classifiers, so the same type is scored the
# same way for every Nemotron-trained tool.
_NEMOTRON_PII_LABELS = [
    "occupation", "certificate_license_number", "first_name", "date_of_birth", "ssn", "medical_record_number",
    "password", "unique_id", "phone_number", "national_id", "swift_bic", "company_name", "country",
    "license_plate", "tax_id", "employee_id", "pin", "state", "email", "date_time", "api_key",
    "biometric_identifier", "credit_debit_card", "coordinate", "device_identifier", "city", "postcode",
    "bank_routing_number", "vehicle_identifier", "health_plan_beneficiary_number", "url", "ipv4", "last_name",
    "cvv", "customer_id", "date", "user_name", "street_address", "ipv6", "account_number", "time", "age",
    "fax_number", "county", "gender", "sexuality", "political_view", "race_ethnicity", "religious_belief",
    "language", "blood_type", "mac_address", "http_cookie", "employment_status", "education_level"
]

# Gold map of the nemotron-pii-test report set (`public_datasets.py`).
_NEMOTRON_TO_NULLPII8 = {
    "first_name": "private_person",
    "last_name": "private_person",
    "user_name": "private_person",
    "email": "private_email",
    "phone_number": "private_phone",
    "street_address": "private_address",
    "city": "private_address",
    "county": "private_address",
    "state": "private_address",
    "postcode": "private_address",
    "country": "private_address",
    "coordinate": "private_geolocation",
    "date": "private_date",
    "time": "private_date",
    "date_time": "private_date",
    "date_of_birth": "private_date",
    "age": "private_date",
    "url": "private_url",
    "ssn": "account_number",
    "account_number": "account_number",
    "bank_routing_number": "account_number",
    "swift_bic": "account_number",
    "cvv": "account_number",
    "credit_debit_card": "account_number",
    "employee_id": "account_number",
    "customer_id": "account_number",
    "medical_record_number": "account_number",
    "health_plan_beneficiary_number": "account_number",
    # v0.3 schema split — vehicle/license get their own labels.
    "vehicle_identifier": "private_vehicle_id",
    "license_plate": "private_vehicle_id",
    "certificate_license_number": "account_number",
    "mac_address": "private_mac",
    "ipv4": "private_ip",
    "device_identifier": "account_number",
    "password": "secret",
    "pin": "secret",
    "biometric_identifier": "secret",
}


# GLiNER's own word splitter (`WhitespaceTokenSplitter`).
_GLINER_WORD = re.compile(r"\w+(?:[-_]\w+)*|\S")
# Windows of one document go to `inference` together, as the GLiNER docs
# recommend for many texts; batching changes padding only.
_GLINER_BATCH_SIZE = 8


def _gliner_windows(text: str, max_words: int, overlap_words: int) -> list[tuple[int, str]]:
    """(offset, chunk) windows of at most `max_words` GLiNER words, each
    starting on a word, consecutive windows sharing `overlap_words` words.
    GLiNER drops every word past its `max_len` without an error, so a longer
    text has to be split; an overlap of the model's `max_width`, the longest
    span it can emit, keeps an entity cut by one window whole in the next."""
    words = [(m.start(), m.end()) for m in _GLINER_WORD.finditer(text)]
    if len(words) <= max_words:
        return [(0, text)]
    stride = max_words - overlap_words
    windows: list[tuple[int, str]] = []
    for i in range(0, len(words), stride):
        start, end = words[i][0], words[min(i + max_words, len(words)) - 1][1]
        windows.append((start, text[start:end]))
        if i + max_words >= len(words):
            return windows
    return windows


def _dedupe_gliner_spans(spans_with_scores: list[tuple[Span, float]]) -> list[tuple[Span, float]]:
    """Collapse a span repeated across window overlaps: of two overlapping
    same-label spans the longer is kept."""
    out: list[tuple[Span, float]] = []
    for item in sorted(spans_with_scores, key=lambda x: (x[0].start, -x[0].end)):
        if not _replace_overlapping_same_label(out, item):
            out.append(item)
    return sorted(out, key=lambda x: x[0].start)


def _replace_overlapping_same_label(out: list[tuple[Span, float]], item: tuple[Span, float]) -> bool:
    """True if `item` overlaps a kept same-label span; the longer of the two
    is then the one kept. `out` is sorted by start."""
    span = item[0]
    for i in range(len(out) - 1, -1, -1):
        prev = out[i][0]
        if prev.end <= span.start:
            return False
        if prev.label != span.label:
            continue
        if (span.end - span.start) > (prev.end - prev.start):
            out[i] = item
        return True
    return False


def gliner_v2_predictor(
    model_path: str,
    *,
    revision: str | None = None,
    onnx_file: str | None = None,
    device: str = "cuda",
    dtype: str | None = None,
    threshold: float = 0.5,
    local_files_only: bool = False,
    labels: list[str] | None = None,
    label_map: Mapping[str, str | None] | None = None,
    label_cut: LabelCut | None = None,
    max_window_words: int | None = None,
    batch_size: int = _GLINER_BATCH_SIZE,
) -> Predictor:
    """A GLiNER model run the way the GLiNER library documents it: the
    model's `inference` over the label strings it was trained on, at
    `threshold`, with the library's defaults otherwise (flat NER).

    `labels` are the strings to prompt (the competitors pass their card's
    vocabulary); `label_map` projects each onto nullpii's schema and must
    decide every prompted label. Without `labels`, nullpii's own label set
    is prompted and returned unmapped (nullpii's merged models).

    A text longer than the model's `max_len` words, or than
    `max_window_words` where the hardware cannot hold `max_len`, is cut into
    word windows (`_gliner_windows`), `batch_size` at a time; spans repeated
    across an overlap are collapsed. No other glue: no normalisation,
    recognizers or filters.

    `onnx_file` loads an exported ONNX model on the CPU, the library's
    default provider. `dtype` follows the card where it names one
    (gliner-stream-pii: bf16 on CUDA). `threshold` is the run threshold;
    `label_cut` then keeps a span only if its score reaches its label's
    operating point (rule change 9).
    """
    from gliner import GLiNER

    kwargs: dict = {"revision": revision, "local_files_only": local_files_only}
    if onnx_file:
        model = GLiNER.from_pretrained(model_path, load_onnx_model=True, onnx_model_file=onnx_file, **kwargs)
    else:
        model = GLiNER.from_pretrained(model_path, map_location=device, dtype=dtype, **kwargs)
        model.eval()

    inference_labels = list(labels) if labels is not None else list(_NULLPII_LABELS)
    if label_map is not None:
        _check_label_coverage(set(inference_labels), dict(label_map), tool=model_path)
    max_words = min(int(model.config.max_len), max_window_words or int(model.config.max_len))
    overlap_words = int(model.config.max_width)
    if overlap_words >= max_words:
        raise ValueError(f"[{model_path}] window of {max_words} words cannot overlap by max_width {overlap_words}")

    def _project(native: str, score: float) -> str | None:
        label = native if label_map is None else _map_native_label(native, dict(label_map), tool=model_path)
        if label is None or (label_cut is not None and not label_cut.keeps(label, score)):
            return None
        return label

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        windows = _gliner_windows(text, max_words, overlap_words)
        per_window = model.inference(
            [chunk for _, chunk in windows], inference_labels, threshold=threshold, batch_size=batch_size,
        )
        spans_with_scores: list[tuple[Span, float]] = []
        for (offset, _), entities in zip(windows, per_window, strict=True):
            for e in entities:
                score = float(e["score"])
                label = _project(e["label"], score)
                if label is not None:
                    spans_with_scores.append((Span(label, int(e["start"]) + offset, int(e["end"]) + offset), score))
        kept = _dedupe_gliner_spans(spans_with_scores) if len(windows) > 1 else spans_with_scores
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult([sp for sp, _ in kept], elapsed, scores=tuple(sc for _, sc in kept))

    return _predict


def gliner_lora_predictor(
    base_model_path: str,
    adapter_dir: str | Path,
    *,
    device: str = "cuda",
    threshold: float = 0.5,
    chunk_chars: int = 1400,
    overlap_chars: int = 200,
    normalize_input: bool = False,
    use_expanded_prompts: bool = False,
) -> Predictor:
    """Predictor that loads a base GLiNER model and applies a LoRA
    adapter on top. Pure-LoRA inference: base weights stay frozen at
    the v6 checkpoint, only the adapter delta modifies behaviour.

    `adapter_dir` is the directory produced by `train_lora.py`'s
    `peft_inner.save_pretrained(adapter_dir, save_embedding_layers=False)`
    (typically ~3.4 MB; contains `adapter_model.safetensors` +
    `adapter_config.json`).

    Used by the per-domain profile tool defs in `bench_full.py`.
    """
    try:
        from gliner import GLiNER
        from peft import PeftModel
    except ImportError as e:
        raise ImportError("gliner + peft required") from e

    model = GLiNER.from_pretrained(base_model_path, local_files_only=True).to(device)
    model.eval()
    inner = model.model.token_rep_layer.bert_layer.model
    peft_inner = PeftModel.from_pretrained(inner, str(adapter_dir))
    model.model.token_rep_layer.bert_layer.model = peft_inner

    def _dedupe(spans: list[Span]) -> list[Span]:
        if len(spans) <= 1:
            return spans
        sorted_spans = sorted(spans, key=lambda s: (s.start, -s.end))
        out: list[Span] = []
        for s in sorted_spans:
            merged = False
            for i in range(len(out) - 1, -1, -1):
                prev = out[i]
                if prev.end <= s.start:
                    break
                if prev.label != s.label:
                    continue
                if (s.end - s.start) > (prev.end - prev.start):
                    out[i] = s
                merged = True
                break
            if not merged:
                out.append(s)
        return sorted(out, key=lambda s: s.start)

    # optionally use the expanded prompt set (`_NULLPII_EXPANDED_
    # PROMPTS`) and remap finer-grained predictions back to nullpii's
    # canonical 12-class schema via `_EXPANDED_PROMPT_TO_NULLPII8`.
    # When `use_expanded_prompts=False` we still prompt with the 12-class
    # set (matches `GLINER_LABELS` in src/nullpii.ts) so the bench mirrors
    # the runtime. The trained-only 8-class subset stays available as
    # `_NULLPII_8` for ablation runs that need it.
    prompts_for_inference = (
        _NULLPII_EXPANDED_PROMPTS if use_expanded_prompts else _NULLPII_LABELS
    )

    def _label_out(raw: str) -> str:
        if not use_expanded_prompts:
            return raw
        return _EXPANDED_PROMPT_TO_NULLPII8.get(raw, raw)

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        scores: list[float] = []
        if normalize_input:
            inference_text, norm_to_orig = _normalize_for_detection(text)
        else:
            inference_text = text
            norm_to_orig = None  # identity mapping
        text_len = len(inference_text)
        if text_len <= chunk_chars:
            for e in model.predict_entities(inference_text, prompts_for_inference, threshold=threshold):
                ns, ne = int(e["start"]), int(e["end"])
                if norm_to_orig is not None:
                    os_, oe = _remap_span(ns, ne, norm_to_orig)
                else:
                    os_, oe = ns, ne
                spans.append(Span(_label_out(e["label"]), os_, oe))
                scores.append(float(e.get("score", threshold)))
        else:
            stride = chunk_chars - overlap_chars
            spans_with_scores: list[tuple[Span, float]] = []
            for offset in range(0, text_len, stride):
                chunk = inference_text[offset:offset + chunk_chars]
                if not chunk:
                    break
                for e in model.predict_entities(chunk, prompts_for_inference, threshold=threshold):
                    ns_chunk, ne_chunk = int(e["start"]), int(e["end"])
                    ns_full, ne_full = ns_chunk + offset, ne_chunk + offset
                    if norm_to_orig is not None:
                        os_, oe = _remap_span(ns_full, ne_full, norm_to_orig)
                    else:
                        os_, oe = ns_full, ne_full
                    spans_with_scores.append((
                        Span(_label_out(e["label"]), os_, oe),
                        float(e.get("score", threshold)),
                    ))
                if offset + chunk_chars >= text_len:
                    break
            kept = _dedupe([sp for sp, _ in spans_with_scores])
            score_by_id = {id(sp): sc for sp, sc in spans_with_scores}
            for sp in kept:
                spans.append(sp)
                scores.append(score_by_id.get(id(sp), threshold))
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(spans, elapsed, scores=tuple(scores))

    return _predict


def domain_routed_predictor(
    *,
    detector: Callable[[str], str],
    routes: dict[str, Predictor],
    fallback: Predictor,
) -> Predictor:
    """Per-text router that delegates to one of `routes` based on the
    domain `detector`.

    Each routed predictor is invoked exactly as a normal `Predictor`,
    so timing and span output stay compatible. The router itself adds
    only the regex-based detect call (~µs) on top.

    Used by the router tool def in `bench_full.py`. Underlying
    predictors are constructed up-front by the caller (lazy
    instantiation is the caller's responsibility — typically via
    `bench_full.py`'s lambda dict).
    """
    def _predict(text: str) -> ToolResult:
        domain = detector(text)
        predictor = routes.get(domain, fallback)
        return predictor(text)
    return _predict


def _strip_bioes(entity: str) -> str:
    """`B-private_email` / `I-private_email` / `private_email` → `private_email`."""
    if entity.startswith(("B-", "I-", "E-", "S-")):
        return entity[2:]
    return entity


_SCRUBADUB_LABEL_MAP = {
    "credential": "secret",
    "credit_card": "account_number",
    "email": "private_email",
    "phone": "private_phone",
    "twitter": "private_person",  # username
    "url": "private_url",
    "social_security_number": "account_number",
}


# ─── Cloud-API competitor predictors (Tier 1, paid) ────────────────
#
# Each adapter requires the corresponding cloud SDK + credentials in
# the environment. Bench cost: ~$50–100 total for n=2000 samples × 9
# datasets across all three providers (AWS / GCP / Azure). One-shot —
# these are not part of the recurring bench.

_AWS_COMPREHEND_TO_NULLPII: dict[str, str] = {
    "NAME": "private_person",
    "EMAIL": "private_email",
    "PHONE": "private_phone",
    "ADDRESS": "private_address",
    "DATE_TIME": "private_date",
    "URL": "private_url",
    "SSN": "account_number",
    "BANK_ACCOUNT_NUMBER": "account_number",
    "BANK_ROUTING": "account_number",
    "CREDIT_DEBIT_NUMBER": "account_number",
    "CREDIT_DEBIT_CVV": "secret",
    "CREDIT_DEBIT_EXPIRY": "private_date",
    "PIN": "secret",
    "PASSWORD": "secret",
    "AWS_ACCESS_KEY": "secret",
    "AWS_SECRET_KEY": "secret",
    "IP_ADDRESS": "private_ip",
    "MAC_ADDRESS": "private_mac",
    "PASSPORT_NUMBER": "private_passport",
    "DRIVER_ID": "private_driver_license",
    "LICENSE_PLATE": "private_vehicle_id",
}


_GCP_DLP_TO_NULLPII: dict[str, str] = {
    "PERSON_NAME": "private_person",
    "EMAIL_ADDRESS": "private_email",
    "PHONE_NUMBER": "private_phone",
    "STREET_ADDRESS": "private_address",
    "LOCATION": "private_address",
    "DATE": "private_date",
    "DATE_OF_BIRTH": "private_date",
    "URL": "private_url",
    "US_SOCIAL_SECURITY_NUMBER": "account_number",
    "IBAN_CODE": "account_number",
    "CREDIT_CARD_NUMBER": "account_number",
    # v0.4 schema split — keep parity with AWS / Presidio so GCP isn't
    # silently penalized when gold uses the dedicated network labels.
    "IP_ADDRESS": "private_ip",
    "MAC_ADDRESS": "private_mac",
    "AUTH_TOKEN": "secret",
    "AWS_CREDENTIALS": "secret",
    "ENCRYPTION_KEY": "secret",
    "GCP_API_KEY": "secret",
    "GCP_CREDENTIALS": "secret",
    "JSON_WEB_TOKEN": "secret",
    "PASSWORD": "secret",
}


_AZURE_PII_TO_NULLPII: dict[str, str] = {
    "Person": "private_person",
    "Email": "private_email",
    "PhoneNumber": "private_phone",
    "Address": "private_address",
    "DateTime": "private_date",
    "URL": "private_url",
    "USSocialSecurityNumber": "account_number",
    "InternationalBankingAccountNumber": "account_number",
    "EUDebitCardNumber": "account_number",
    "CreditCardNumber": "account_number",
    # v0.4 schema split — Azure has no native MAC entity; only IP routes.
    "IPAddress": "private_ip",
    "Password": "secret",
}


# ─── TAB (Text Anonymization Benchmark) loader stub ────────────────
# TAB = ECHR court rulings annotated for legal PII (ACL 2022).
# Public dataset, third-party gold standard. Loader stub — actual data
# location to be confirmed (HF: pieldolce/TAB or similar). Filling in
# requires download + label-schema mapping ECHR → nullpii 12 categories.
def _load_tab_stub(_n: int | None) -> list:
    raise NotImplementedError(
        "TAB loader stub — locate ECHR-PII dataset on HF + map labels "
        "(PERSON/CODE/LOC/DATETIME/QUANTITY/MISC) → nullpii 12 categories.",
    )


def has_artifacts() -> bool:
    return DEFAULT_MODEL_DIR.is_dir() and (DEFAULT_MODEL_DIR / "tokenizer.json").is_file()


def has_nullpii_built() -> bool:
    return (REPO_ROOT / "dist" / "index.js").is_file()


def hf_token() -> str | None:
    return os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")
