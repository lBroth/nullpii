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

    pipe = pipeline(
        task="token-classification",
        model="openai/privacy-filter",
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
