# SPDX-License-Identifier: Apache-2.0
"""Tool adapters: each takes `text` and returns a list of `Span`.

The nullpii adapter spawns a long-running `nullpii serve` process and
talks to it via JSON-lines on stdin/stdout — keeps the model in memory
across calls (one model load, not one per sample).

Presidio runs in-process via its Python API.
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import threading
import time
from collections.abc import Callable
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


Predictor = Callable[[str], ToolResult]


class _NullpiiServer:
    def __init__(
        self,
        *,
        model_dir: Path,
        backend: str,
        variant: str,
        enter_bias: float | None = None,
        background_bias: float | None = None,
        continue_bias: float | None = None,
        threshold: float | None = None,
        threads: int | None = None,
    ) -> None:
        argv = [
            "node",
            str(NULLPII_BIN),
            "serve",
            "--model-dir", str(model_dir),
            "--backend", backend,
            "--variant", variant,
        ]
        if enter_bias is not None:
            argv += ["--enter-bias", str(enter_bias)]
        if background_bias is not None:
            argv += ["--background-bias", str(background_bias)]
        if continue_bias is not None:
            argv += ["--continue-bias", str(continue_bias)]
        if threshold is not None:
            argv += ["--threshold", str(threshold)]
        if threads is not None:
            argv += ["--threads", str(threads)]
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(REPO_ROOT),
        )
        if self.proc.stderr is None:
            raise RuntimeError("nullpii serve: failed to capture stderr")
        # Some backends (e.g. CoreML) log warnings to stderr before our
        # ready signal. Drain lines until we see ready or the process exits.
        seen: list[str] = []
        while True:
            line = self.proc.stderr.readline()
            if line == "":
                self.proc.kill()
                raise RuntimeError(
                    "nullpii serve did not become ready: " + " | ".join(s.strip() for s in seen)
                )
            seen.append(line)
            if "ready" in line:
                break
        # stdin/stdout are a single full-duplex pipe pair to one daemon.
        # Multiple threads writing/reading concurrently would interleave
        # request and response lines. Serialize via a per-server lock.
        self._lock = threading.Lock()
        atexit.register(self.close)

    def request(self, text: str) -> tuple[list[Span], float]:
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("nullpii serve: pipes closed")
        t0 = time.perf_counter()
        with self._lock:
            self.proc.stdin.write(f"{json.dumps({'text': text})}\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        elapsed = (time.perf_counter() - t0) * 1000
        if line == "":
            raise RuntimeError(f"nullpii serve died: {self._stderr_tail()}")
        resp = json.loads(line)
        if "error" in resp and resp["error"]:
            raise RuntimeError(f"nullpii serve error: {resp['error']}")
        spans = [Span(s["label"], int(s["start"]), int(s["end"])) for s in resp.get("spans", [])]
        return spans, elapsed

    def _stderr_tail(self) -> str:
        if self.proc.stderr is None:
            return ""
        try:
            return self.proc.stderr.read() or ""
        except Exception:  # noqa: BLE001
            return ""

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                if self.proc.stdin is not None:
                    self.proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class _NullpiiServerPool:
    """A pool of N independent `nullpii serve` daemons.

    Each daemon owns its own ORT session and stdin/stdout pipe, so
    `request()` calls dispatched to different daemons execute in true
    parallel (no shared lock). Round-robin assignment via an index lock.
    """

    def __init__(self, *, size: int, **server_kwargs) -> None:
        if size < 1:
            raise ValueError("pool size must be >= 1")
        self.servers = [_NullpiiServer(**server_kwargs) for _ in range(size)]
        self._next = 0
        self._next_lock = threading.Lock()

    def request(self, text: str) -> tuple[list[Span], float]:
        with self._next_lock:
            srv = self.servers[self._next % len(self.servers)]
            self._next += 1
        return srv.request(text)

    def close(self) -> None:
        for s in self.servers:
            s.close()


def nullpii_pool_predictor(
    *,
    pool_size: int = 4,
    threads_each: int = 2,
    model_dir: Path = DEFAULT_MODEL_DIR,
    backend: str = "cpu",
    variant: str = "fp16",
    enter_bias: float | None = None,
    background_bias: float | None = None,
    continue_bias: float | None = None,
    threshold: float | None = None,
) -> Predictor:
    """Pool-backed predictor — N nullpii daemons with capped per-daemon
    threads. Total threads = pool_size × threads_each. Round-robin
    dispatch lets multiple eval threads run truly concurrently."""
    if not NULLPII_BIN.is_file():
        raise FileNotFoundError(f"nullpii CLI not found at {NULLPII_BIN}")
    pool = _NullpiiServerPool(
        size=pool_size,
        model_dir=model_dir,
        backend=backend,
        variant=variant,
        threads=threads_each,
        enter_bias=enter_bias,
        background_bias=background_bias,
        continue_bias=continue_bias,
        threshold=threshold,
    )

    def _predict(text: str) -> ToolResult:
        spans, elapsed = pool.request(text)
        return ToolResult(spans, elapsed)

    return _predict


def nullpii_predictor(
    *,
    model_dir: Path = DEFAULT_MODEL_DIR,
    backend: str = "cpu",
    # fp16 beats int8 on CPU for this model: same F1, ~17% faster on Apple
    # M-series. MPS path is slower because only ~24 of 365 ops are CoreML-
    # eligible — partition overhead dominates.
    variant: str = "fp16",
    enter_bias: float | None = None,
    background_bias: float | None = None,
    continue_bias: float | None = None,
    threshold: float | None = None,
    threads: int | None = None,
) -> Predictor:
    if not NULLPII_BIN.is_file():
        raise FileNotFoundError(f"nullpii CLI not found at {NULLPII_BIN}")
    server = _NullpiiServer(
        model_dir=model_dir,
        backend=backend,
        variant=variant,
        enter_bias=enter_bias,
        background_bias=background_bias,
        continue_bias=continue_bias,
        threshold=threshold,
        threads=threads,
    )

    def _predict(text: str) -> ToolResult:
        spans, elapsed = server.request(text)
        return ToolResult(spans, elapsed)

    return _predict


BatchPredictor = Callable[[list[str]], list[ToolResult]]


def openai_pipeline_batch_predictor(
    *,
    device: str | None = None,
    batch_size: int = 32,
) -> BatchPredictor:
    """Batched HF predictor — runs the pipeline on a list of texts in
    one call, vastly faster than one-at-a-time on MPS where the
    per-call dispatch overhead dominates."""
    try:
        import torch  # noqa: I001
        from transformers import pipeline
    except ImportError as e:
        raise ImportError("transformers + torch required") from e

    if device is None:
        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"

    # Force torch to actually use multiple cores on Apple Silicon.
    # Default is often 1 — leaves 13 idle on M5 Pro.
    if device == "cpu":
        threads = max(1, (os.cpu_count() or 8) // 2)
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(max(1, threads // 4))
        except RuntimeError:
            pass  # already set, ignore

    pipe = pipeline(
        task="token-classification",
        model="openai/privacy-filter",
        aggregation_strategy="simple",
        device=device,
        batch_size=batch_size,
        trust_remote_code=True,
    )

    def _predict_batch(texts: list[str]) -> list[ToolResult]:
        t0 = time.perf_counter()
        results_list = pipe(texts)
        elapsed = (time.perf_counter() - t0) * 1000
        per_call = elapsed / max(1, len(texts))
        out: list[ToolResult] = []
        # Pipeline returns either a list of lists (batch) or a single list
        # (single text). Normalize.
        if results_list and isinstance(results_list[0], dict):
            results_list = [results_list]  # type: ignore[list-item]
        for results in results_list:
            spans: list[Span] = []
            for r in results:
                entity = str(r.get("entity_group") or r.get("entity") or "")
                label = _strip_bioes(entity)
                if label not in _OPENAI_LABELS:
                    continue
                spans.append(Span(label, int(r["start"]), int(r["end"])))
            out.append(ToolResult(spans, per_call))
        return out

    return _predict_batch


def openai_pipeline_predictor(
    *,
    device: str | None = None,
    batch_size: int = 1,
) -> Predictor:
    """Upstream-reference predictor: `transformers.pipeline` on the bare HF
    weights. No chunking, no Viterbi biases — just HF's default token
    classification decoder. Used to verify that nullpii's runtime adds
    value beyond what the model alone would produce.

    `device='mps'` on Apple Silicon offloads to the GPU via MPS, ~3-5×
    faster than CPU for transformer inference. `batch_size>1` lets the
    pipeline parallelize when called via `pipe(list_of_texts)`.
    """
    try:
        import torch  # noqa: I001
        from transformers import pipeline
    except ImportError as e:
        raise ImportError(
            "transformers not installed; run `pip install transformers torch` to use this adapter",
        ) from e

    if device is None:
        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"

    pipe = pipeline(
        task="token-classification",
        model="openai/privacy-filter",
        aggregation_strategy="simple",
        device=device,
        batch_size=batch_size,
        trust_remote_code=True,
    )

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        results = pipe(text)
        elapsed = (time.perf_counter() - t0) * 1000
        spans: list[Span] = []
        for r in results:
            entity = str(r.get("entity_group") or r.get("entity") or "")
            label = _strip_bioes(entity)
            if label not in _OPENAI_LABELS:
                continue
            spans.append(Span(label, int(r["start"]), int(r["end"])))
        return ToolResult(spans, elapsed)

    return _predict


_PIIRANHA_LABEL_MAP = {
    "ACCOUNTNUM": "account_number",
    "CREDITCARDNUMBER": "account_number",
    "IDCARDNUM": "account_number",
    "SOCIALNUM": "account_number",
    "TAXNUM": "account_number",
    "DRIVERLICENSENUM": "account_number",
    "BUILDINGNUM": "private_address",
    "CITY": "private_address",
    "STREET": "private_address",
    "ZIPCODE": "private_address",
    "DATEOFBIRTH": "private_date",
    "EMAIL": "private_email",
    "GIVENNAME": "private_person",
    "SURNAME": "private_person",
    "TELEPHONENUM": "private_phone",
    "PASSWORD": "secret",
}


def piiranha_predictor(
    *,
    device: str | None = None,
    batch_size: int = 32,
) -> BatchPredictor:
    """`iiiorg/piiranha-v1-detect-personal-information` — DeBERTa-v3-based
    multilingual PII detector (en/es/fr/de/it/nl, 17 PII labels, 256-tok
    max). Smaller than openai/privacy-filter (~278M params vs 1.3B), no
    chunking, no Viterbi — bare HF token-classification pipeline."""
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

    def _predict_batch(texts: list[str]) -> list[ToolResult]:
        t0 = time.perf_counter()
        results_list = pipe(texts)
        elapsed = (time.perf_counter() - t0) * 1000
        per_call = elapsed / max(1, len(texts))
        out: list[ToolResult] = []
        if results_list and isinstance(results_list[0], dict):
            results_list = [results_list]  # type: ignore[list-item]
        for results in results_list:
            spans: list[Span] = []
            for r in results:
                entity = str(r.get("entity_group") or r.get("entity") or "")
                key = _strip_bioes(entity).upper()
                label = _PIIRANHA_LABEL_MAP.get(key)
                if label is None:
                    continue
                spans.append(Span(label, int(r["start"]), int(r["end"])))
            out.append(ToolResult(spans, per_call))
        return out

    return _predict_batch


_DEBERTA_LABEL_MAP = {
    "FIRSTNAME": "private_person",
    "LASTNAME": "private_person",
    "MIDDLENAME": "private_person",
    "PREFIX": "private_person",
    "ACCOUNTNAME": None,
    "ACCOUNTNUMBER": "account_number",
    "BIC": "account_number",
    "IBAN": "account_number",
    "BITCOINADDRESS": "account_number",
    "ETHEREUMADDRESS": "account_number",
    "LITECOINADDRESS": "account_number",
    "MASKEDNUMBER": "account_number",
    "CREDITCARDNUMBER": "account_number",
    "CREDITCARDCVV": "account_number",
    "VEHICLEVRM": "account_number",
    "VEHICLEVIN": "account_number",
    "PIN": "secret",
    "PASSWORD": "secret",
    "SSN": "account_number",
    "EMAIL": "private_email",
    "PHONENUMBER": "private_phone",
    "PHONEIMEI": "account_number",
    "STREET": "private_address",
    "STREETADDRESS": "private_address",
    "BUILDINGNUMBER": "private_address",
    "ZIPCODE": "private_address",
    "CITY": "private_address",
    "STATE": "private_address",
    "COUNTY": "private_address",
    "COUNTRY": "private_address",
    "GPSCOORDINATES": "private_address",
    "DOB": "private_date",
    "DATE": "private_date",
    "TIME": "private_date",
    "URL": "private_url",
    "USERAGENT": None,
    "USERNAME": None,
    "IP": None,
    "IPV4": None,
    "IPV6": None,
    "MAC": None,
}


def deberta_pii_predictor(
    *,
    device: str | None = None,
    batch_size: int = 32,
) -> BatchPredictor:
    """`lakshyakh93/deberta_finetuned_pii` — DeBERTa-base English-only PII
    detector with rich label set (~50+ categories). Mapped down to
    nullpii's 8 categories."""
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
        aggregation_strategy="first",
        device=device,
        batch_size=batch_size,
    )

    def _predict_batch(texts: list[str]) -> list[ToolResult]:
        t0 = time.perf_counter()
        results_list = pipe(texts)
        elapsed = (time.perf_counter() - t0) * 1000
        per_call = elapsed / max(1, len(texts))
        out: list[ToolResult] = []
        if results_list and isinstance(results_list[0], dict):
            results_list = [results_list]  # type: ignore[list-item]
        for results in results_list:
            spans: list[Span] = []
            for r in results:
                entity = str(r.get("entity_group") or r.get("entity") or "")
                key = _strip_bioes(entity).upper()
                label = _DEBERTA_LABEL_MAP.get(key)
                if label is None:
                    continue
                spans.append(Span(label, int(r["start"]), int(r["end"])))
            out.append(ToolResult(spans, per_call))
        return out

    return _predict_batch


_GLINER_LABELS = [
    "person",
    "email",
    "phone number",
    "mobile phone number",
    "address",
    "postal code",
    "date of birth",
    "credit card number",
    "bank account number",
    "IBAN",
    "social security number",
    "passport number",
    "driver's license",
    "national identification number",
    "URL",
    "API key",
    "password",
    "username",
]

_GLINER_LABEL_MAP = {
    "person": "private_person",
    "email": "private_email",
    "phone number": "private_phone",
    "mobile phone number": "private_phone",
    "address": "private_address",
    "postal code": "private_address",
    "date of birth": "private_date",
    "credit card number": "account_number",
    "bank account number": "account_number",
    "IBAN": "account_number",
    "social security number": "account_number",
    "passport number": "account_number",
    "driver's license": "account_number",
    "national identification number": "account_number",
    "URL": "private_url",
    "API key": "secret",
    "password": "secret",
    "username": None,
}


def gliner_pii_predictor(
    *,
    threshold: float = 0.5,
) -> Predictor:
    """`urchade/gliner_multi_pii-v1` — GLiNER zero-shot NER. Supports
    arbitrary label sets at inference; we pass a curated PII list and
    map to nullpii's 8 categories."""
    try:
        from gliner import GLiNER  # noqa: I001
    except ImportError as e:
        raise ImportError(
            "gliner not installed; run `pip install gliner` to use this adapter",
        ) from e

    model = GLiNER.from_pretrained("urchade/gliner_multi_pii-v1")

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        entities = model.predict_entities(text, _GLINER_LABELS, threshold=threshold)
        elapsed = (time.perf_counter() - t0) * 1000
        spans: list[Span] = []
        for e in entities:
            label = _GLINER_LABEL_MAP.get(e.get("label"))
            if label is None:
                continue
            spans.append(Span(label, int(e["start"]), int(e["end"])))
        return ToolResult(spans, elapsed)

    return _predict


def make_best_ensemble(
    *,
    pool_size: int = 4,
    threads_each: int = 4,
    gliner_threshold: float = 0.8,
) -> Predictor:
    """Production-default ensemble derived from the iter-22 sweep.

    Stack:
      - **nullpii** pool (4 daemons × 4 ORT threads, cpu+fp16)
      - **GLiNER** (urchade/gliner_multi_pii-v1, threshold 0.8, chunked)
      - **regex pack** (URL http(s)/www, email, AWS/GitHub/Stripe/OpenAI keys,
        IBAN, SSN, phone)
      - **boundary refinement** (trim trailing whitespace + punctuation)

    Strategy: nullpii primary, GLiNER + regex fill non-overlapping gaps.
    Best measured F1: 0.6712 across 4271 samples (bundled multi-locale,
    long-prompts-en, isotonic 4 locales). Latency p50 207 ms / p95 278 ms
    single-call on Apple M5 Pro 48 GB."""
    np_pred = nullpii_pool_predictor(
        pool_size=pool_size, threads_each=threads_each,
        backend="cpu", variant="fp16",
    )
    gl_pred = gliner_chunked_predictor(threshold=gliner_threshold)
    rg_pred = regex_recognizer_predictor(patterns=DEFAULT_REGEX_PATTERNS)
    ens = multi_ensemble_predictor(
        predictors=[np_pred, gl_pred, rg_pred], strategy="primary",
    )
    return boundary_refined_predictor(inner=ens)


def boundary_refined_predictor(
    *,
    inner: Predictor,
    trim_chars: str = " \t\n\r,.;:!?\"'()[]{}<>",
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


def regex_recognizer_predictor(
    *,
    patterns: list[tuple[str, str]],
) -> Predictor:
    """Lightweight regex-based predictor.

    `patterns` is a list of `(label, regex)` tuples; matches yield Spans
    with that label. Useful as a Tier-2 ensemble member to fill gaps
    where ML detectors miss structured formats (URLs, IBANs, etc.)."""
    import re as _re

    compiled = [(label, _re.compile(pat)) for label, pat in patterns]

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        for label, regex in compiled:
            for m in regex.finditer(text):
                spans.append(Span(label, m.start(), m.end()))
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(spans, elapsed)

    return _predict


# Pre-baked recognizer patterns covering nullpii's biggest miss-rate
# categories. Keeps the regex set small, defensible, and composable.
DEFAULT_REGEX_PATTERNS: list[tuple[str, str]] = [
    # URL: nullpii misses 66% of these. Only http(s):// + www. — bare
    # domain.tld pattern dropped because it creates many FPs (matches
    # filenames, user.email-like fragments, etc.) without real recall lift.
    ("private_url", r"\b(?:https?://|www\.)[^\s<>\"]+"),
    # Email — straightforward. nullpii already low miss but cheap to add.
    ("private_email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    # AWS access key
    ("secret", r"\bAKIA[0-9A-Z]{16}\b"),
    # GitHub PAT (classic + fine-grained)
    ("secret", r"\bghp_[A-Za-z0-9]{36,}\b"),
    ("secret", r"\bghs_[A-Za-z0-9]{36,}\b"),
    ("secret", r"\bgithub_pat_[A-Za-z0-9_]{82,}\b"),
    # Stripe keys
    ("secret", r"\bsk_(?:live|test)_[A-Za-z0-9]{24,}\b"),
    # OpenAI/Anthropic keys
    ("secret", r"\bsk-[A-Za-z0-9]{32,}\b"),
    ("secret", r"\bsk-ant-[A-Za-z0-9_-]{50,}\b"),
    # IBAN (rough — IT, GB, DE, FR, ES; trims at non-alphanum)
    ("account_number", r"\b[A-Z]{2}\d{2}[A-Z0-9]{1,4}(?:[ \t]?\d{4}){2,5}(?:[ \t]?\d{1,4})?\b"),
    # Credit card 16-digit pattern dropped: matches phone numbers,
    # version strings, dataset row IDs etc. — too many FPs.
    # SSN US
    ("account_number", r"\b\d{3}-\d{2}-\d{4}\b"),
    # Phone (international)
    ("private_phone", r"\+\d{1,3}[\s-]?(?:\(\d+\)[\s-]?)?\d{2,4}[\s-]?\d{2,4}[\s-]?\d{2,4}\b"),
]


def multi_ensemble_predictor(
    *,
    predictors: list[Predictor],
    strategy: str = "union",
) -> Predictor:
    """Generic N-way ensemble. Strategies:

    - **union**: all spans, longest-wins on overlap (recall++)
    - **primary**: predictors[0] wins, others fill non-overlapping gaps
    - **intersection**: keep span only if ≥2 predictors agree
    - **majority**: keep span only if >N/2 predictors agree
    """
    if strategy not in {"union", "primary", "intersection", "majority"}:
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

    def _merge_intersection(spans_per_tool: list[list[Span]]) -> list[Span]:
        # Span is kept if ≥2 predictors find an overlapping same-label span.
        out: list[Span] = []
        for i, spans in enumerate(spans_per_tool):
            for s in spans:
                hits = 0
                for j, other in enumerate(spans_per_tool):
                    if i == j:
                        continue
                    if any(_overlaps(s, o) and s.label == o.label for o in other):
                        hits += 1
                        break
                if hits > 0:
                    out.append(s)
        return _dedupe_longest(out)

    def _merge_majority(spans_per_tool: list[list[Span]]) -> list[Span]:
        threshold = len(spans_per_tool) / 2
        candidates = _dedupe_longest([s for spans in spans_per_tool for s in spans])
        out: list[Span] = []
        for s in candidates:
            agree = sum(
                1
                for spans in spans_per_tool
                if any(_overlaps(s, o) and s.label == o.label for o in spans)
            )
            if agree > threshold:
                out.append(s)
        return out

    mergers = {
        "union": _merge_union,
        "primary": _merge_primary,
        "intersection": _merge_intersection,
        "majority": _merge_majority,
    }
    merger = mergers[strategy]

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        results = [pred(text) for pred in predictors]
        spans_per_tool = [list(r.spans) for r in results]
        merged = merger(spans_per_tool)
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(merged, elapsed)

    return _predict


def category_routing_predictor(
    *,
    routing: dict[str, Predictor],
    fallback: Predictor | None = None,
) -> Predictor:
    """Route output by PII category — pick the best-performing tool per
    label based on per-category miss-rate analysis. Each tool is
    queried, then we keep only the spans whose label matches that
    tool's responsibility per `routing`. Optional `fallback` covers
    labels not in the routing map."""
    if not routing:
        raise ValueError("routing map required")

    # Deduplicate predictors so we don't call the same one twice.
    unique_preds: dict[int, Predictor] = {}
    for pred in routing.values():
        unique_preds[id(pred)] = pred
    if fallback is not None:
        unique_preds[id(fallback)] = fallback
    pred_list = list(unique_preds.values())

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        per_pred_spans: dict[int, list[Span]] = {}
        for pred in pred_list:
            per_pred_spans[id(pred)] = list(pred(text).spans)
        out: list[Span] = []
        for label, pred in routing.items():
            for s in per_pred_spans[id(pred)]:
                if s.label == label:
                    out.append(s)
        if fallback is not None:
            covered = set(routing.keys())
            for s in per_pred_spans[id(fallback)]:
                if s.label not in covered:
                    out.append(s)
        # Dedupe (in case overlap from multiple tools assigned same label).
        out_sorted = sorted(out, key=lambda s: s.start)
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(out_sorted, elapsed)

    return _predict


def nullpii_gliner_ensemble_predictor(
    *,
    nullpii_pred: Predictor,
    gliner_pred: Predictor,
    strategy: str = "union",
) -> Predictor:
    """Combine nullpii and GLiNER outputs.

    Strategies:
    - **union**: merge spans from both, dedupe overlapping (longest wins;
      ties go to higher score). Maximizes recall.
    - **nullpii_primary**: keep all nullpii spans; add GLiNER spans only
      where they don't overlap nullpii output. Mirrors the
      ML+recognizer fill-the-gaps philosophy.
    - **intersection**: keep only spans both tools agree on (same label,
      overlapping range). Maximizes precision.
    """
    if strategy not in {"union", "nullpii_primary", "intersection"}:
        raise ValueError(f"unknown strategy: {strategy}")

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
                # Keep the longer one.
                if (s.end - s.start) > (prev.end - prev.start):
                    out[i] = s
                replaced = True
                break
            if not replaced:
                out.append(s)
        return sorted(out, key=lambda s: s.start)

    def _union(np_spans: list[Span], gl_spans: list[Span]) -> list[Span]:
        return _dedupe_longest(np_spans + gl_spans)

    def _nullpii_primary(np_spans: list[Span], gl_spans: list[Span]) -> list[Span]:
        added: list[Span] = list(np_spans)
        for g in gl_spans:
            if any(_overlaps(g, n) for n in np_spans):
                continue
            added.append(g)
        return sorted(added, key=lambda s: s.start)

    def _intersection(np_spans: list[Span], gl_spans: list[Span]) -> list[Span]:
        out: list[Span] = []
        for n in np_spans:
            for g in gl_spans:
                if n.label == g.label and _overlaps(n, g):
                    out.append(n)
                    break
        return out

    merger = {"union": _union, "nullpii_primary": _nullpii_primary, "intersection": _intersection}[strategy]

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        np_result = nullpii_pred(text)
        gl_result = gliner_pred(text)
        merged = merger(list(np_result.spans), list(gl_result.spans))
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(merged, elapsed)

    return _predict


def gliner_chunked_predictor(
    *,
    threshold: float = 0.5,
    chunk_chars: int = 1400,
    overlap_chars: int = 200,
) -> Predictor:
    """nullpii-style pipeline (chunking + span dedupe) on top of GLiNER's
    zero-shot NER. Tests whether nullpii's runtime ideas transfer to a
    different backbone — bare GLiNER hits 0.000 on long-prompts-en
    because of max-sequence-length truncation; chunked GLiNER should
    recover the spans past that boundary the same way nullpii does
    over openai/privacy-filter.

    Char-level chunking (4 chars/token approximation): 1400 chars ≈ 350
    tokens, well under GLiNER's mBERT-base 512-tok cap. 200 char overlap
    keeps any short span fully visible in at least one chunk."""
    try:
        from gliner import GLiNER  # noqa: I001
    except ImportError as e:
        raise ImportError("gliner required") from e

    model = GLiNER.from_pretrained("urchade/gliner_multi_pii-v1")

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
                prev_len = prev.end - prev.start
                s_len = s.end - s.start
                if s_len > prev_len:
                    out[i] = s
                merged = True
                break
            if not merged:
                out.append(s)
        return sorted(out, key=lambda s: s.start)

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        if len(text) <= chunk_chars:
            entities = model.predict_entities(text, _GLINER_LABELS, threshold=threshold)
            for e in entities:
                label = _GLINER_LABEL_MAP.get(e.get("label"))
                if label is None:
                    continue
                spans.append(Span(label, int(e["start"]), int(e["end"])))
        else:
            stride = chunk_chars - overlap_chars
            for offset in range(0, len(text), stride):
                chunk = text[offset : offset + chunk_chars]
                if not chunk:
                    break
                entities = model.predict_entities(chunk, _GLINER_LABELS, threshold=threshold)
                for e in entities:
                    label = _GLINER_LABEL_MAP.get(e.get("label"))
                    if label is None:
                        continue
                    spans.append(
                        Span(label, int(e["start"]) + offset, int(e["end"]) + offset),
                    )
                if offset + chunk_chars >= len(text):
                    break
            spans = _dedupe(spans)
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(spans, elapsed)

    return _predict


_OPENAI_LABELS = {
    "account_number",
    "private_address",
    "private_date",
    "private_email",
    "private_person",
    "private_phone",
    "private_url",
    "secret",
}


def _strip_bioes(entity: str) -> str:
    """`B-private_email` / `I-private_email` / `private_email` → `private_email`."""
    if entity.startswith(("B-", "I-", "E-", "S-")):
        return entity[2:]
    return entity


def presidio_predictor(*, language: str = "en") -> Predictor:
    """In-process Presidio analyzer. Maps Presidio entities → our 8 categories."""
    try:
        from presidio_analyzer import AnalyzerEngine  # noqa: I001
    except ImportError as e:
        raise ImportError(
            "presidio not installed; run `pip install -e '.[presidio]'`",
        ) from e

    analyzer = AnalyzerEngine()

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        results = analyzer.analyze(text=text, language=language)
        elapsed = (time.perf_counter() - t0) * 1000
        spans: list[Span] = []
        for r in results:
            label = _map_presidio_entity(r.entity_type)
            if label is None:
                continue
            spans.append(Span(label, int(r.start), int(r.end)))
        return ToolResult(spans, elapsed)

    return _predict


_PRESIDIO_TO_NULLPII = {
    "PERSON": "private_person",
    "EMAIL_ADDRESS": "private_email",
    "PHONE_NUMBER": "private_phone",
    "LOCATION": "private_address",
    "STREET_ADDRESS": "private_address",
    "DATE_TIME": "private_date",
    "URL": "private_url",
    "IBAN_CODE": "account_number",
    "CREDIT_CARD": "account_number",
    "US_SSN": "account_number",
    "API_KEY": "secret",
    "AWS_ACCESS_KEY": "secret",
    "AWS_SECRET_KEY": "secret",
}


def _map_presidio_entity(entity_type: str) -> str | None:
    return _PRESIDIO_TO_NULLPII.get(entity_type)


# Per-locale spaCy model name. Each is `<lang>_core_news_lg` (or `_web_lg` for en/zh).
_SPACY_MODEL_BY_LOCALE: dict[str, str] = {
    "en": "en_core_web_lg",
    "it": "it_core_news_lg",
    "de": "de_core_news_lg",
    "fr": "fr_core_news_lg",
    "es": "es_core_news_lg",
    "ja": "ja_core_news_lg",
    "zh": "zh_core_web_lg",
}

_SPACY_LABEL_TO_NULLPII = {
    "PERSON": "private_person",
    "PER": "private_person",
    "PERS": "private_person",
    "GPE": "private_address",
    "LOC": "private_address",
    "FAC": "private_address",
    "DATE": "private_date",
    "TIME": "private_date",
    "URL": "private_url",
    "MONEY": None,
    "ORG": None,
    "MISC": None,
}


def spacy_predictor(*, locale: str = "en") -> Predictor:
    """Bare spaCy NER. Uses `_core_news_lg` for non-English locales,
    `en_core_web_lg` for English. Maps NER labels onto our 8 categories."""
    try:
        import spacy  # noqa: I001
    except ImportError as e:
        raise ImportError(
            "spacy not installed; run `pip install spacy` to use this predictor",
        ) from e

    model_name = _SPACY_MODEL_BY_LOCALE.get(locale)
    if model_name is None:
        raise ValueError(f"spacy_predictor: no model registered for locale '{locale}'")
    try:
        nlp = spacy.load(model_name)
    except OSError as e:
        raise OSError(
            f"spaCy model '{model_name}' not installed; "
            f"run `python -m spacy download {model_name}`",
        ) from e

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        doc = nlp(text)
        elapsed = (time.perf_counter() - t0) * 1000
        spans: list[Span] = []
        for ent in doc.ents:
            label = _SPACY_LABEL_TO_NULLPII.get(ent.label_)
            if label is None:
                continue
            spans.append(Span(label, int(ent.start_char), int(ent.end_char)))
        return ToolResult(spans, elapsed)

    return _predict


def has_artifacts() -> bool:
    return DEFAULT_MODEL_DIR.is_dir() and (DEFAULT_MODEL_DIR / "tokenizer.json").is_file()


def has_nullpii_built() -> bool:
    return (REPO_ROOT / "dist" / "index.js").is_file()


def hf_token() -> str | None:
    return os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")
