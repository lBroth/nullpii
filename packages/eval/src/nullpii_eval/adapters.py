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
import re
import subprocess
import sys
import threading
import time
import unicodedata
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
    # Optional parallel scores per span. Empty tuple = no scores
    # available (resolver will default to 1.0). Populated by predictors
    # that have native confidence (e.g. GLiNER) or by the regex layer
    # which assigns per-label priors.
    scores: tuple[float, ...] = ()


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
        # Used inside an already-failing path (e.g. "daemon died" message
        # construction). MUST return a string — raising here replaces the
        # original error with this one and erases the actual cause.
        # Read errors are surfaced as the returned diagnostic string.
        if self.proc.stderr is None:
            return "<no stderr captured>"
        try:
            data = self.proc.stderr.read()
        except (OSError, ValueError) as e:
            return f"<could not read stderr: {type(e).__name__}: {e}>"
        return data if data else "<empty stderr>"

    def close(self) -> None:
        # `atexit`-registered cleanup. We MUST not crash interpreter
        # shutdown for unrelated daemons; but any unexpected error here
        # gets re-raised so test harnesses see it. BrokenPipe on a
        # daemon that already exited is the only routine condition.
        if self.proc.poll() is None:
            if self.proc.stdin is not None:
                try:
                    self.proc.stdin.close()
                except BrokenPipeError as e:
                    print(f"[nullpii-pool] stdin already closed: {e}",
                          file=sys.stderr, flush=True)
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


def nullpii_runtime_predictor(
    *,
    backend: str = "cpu",
    variant: str = "int4",
    threshold: float | None = None,
) -> Predictor:
    """Predictor backed by the npm package's `scan --ndjson` mode.

    Spawns `node bin/nullpii.mjs scan --ndjson` once, loads the engine
    in that subprocess, then streams texts in NDJSON form on stdin and
    reads JSON-per-line span results from stdout. One model load for
    the whole bench — no per-call startup cost.

    This is the **npm runtime** path: `openai/privacy-filter` ONNX +
    constrained Viterbi BIOES + chunking + recognizer post-pass +
    in-memory vault. Tests whether the runtime adds value beyond the
    bare model with proper Viterbi (\`openai-official\`).
    """
    if not NULLPII_BIN.is_file():
        raise FileNotFoundError(f"nullpii CLI not found at {NULLPII_BIN}")

    argv = [
        "node", str(NULLPII_BIN), "scan", "--ndjson",
        "--backend", backend, "--variant", variant,
    ]
    if threshold is not None:
        argv += ["--threshold", str(threshold)]

    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    if proc.stdin is None or proc.stdout is None:
        raise RuntimeError("nullpii subprocess: stdin/stdout pipes failed to open")

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        proc.stdin.write(json.dumps({"text": text}) + "\n")  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]
        line = proc.stdout.readline()  # type: ignore[union-attr]
        elapsed = (time.perf_counter() - t0) * 1000
        if not line:
            raise RuntimeError(
                "nullpii subprocess closed stdout unexpectedly. "
                f"return code: {proc.poll()}",
            )
        result = json.loads(line)
        if "error" in result:
            raise RuntimeError(f"nullpii ndjson error: {result['error']}")
        spans: list[Span] = []
        for s in result.get("spans", []):
            label = str(s.get("label", "")).lower()
            if label not in _OPENAI_LABELS:
                continue
            spans.append(Span(label, int(s["start"]), int(s["end"])))
        return ToolResult(spans, elapsed)

    return _predict


def nullpii_pool_predictor(
    *,
    pool_size: int = 4,
    threads_each: int = 2,
    model_dir: Path = DEFAULT_MODEL_DIR,
    backend: str = "cpu",
    variant: str = "int4",
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
    variant: str = "int4",
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


def openai_official_predictor(*, device: str = "cpu") -> Predictor:
    """Official `opf` CLI Python API — full constrained Viterbi BIOES decoder.

    Uses `opf` (`github.com/openai/privacy-filter`, Apache-2.0). This is
    the **reference predictor** for `openai/privacy-filter` quality:
    the model card prescribes constrained Viterbi over BIOES, and this
    adapter calls the actual implementation rather than a re-derived
    approximation. Replaces the strawman comparison against our own
    Python BIOES decoder (`openai_bioes_predictor`) with the upstream
    truth.
    """
    try:
        from opf._api import OPF
    except ImportError as e:
        raise ImportError(
            "opf not installed; clone github.com/openai/privacy-filter "
            "and run `pip install -e .` to use this adapter",
        ) from e

    if device not in ("cpu", "cuda"):
        device = "cpu"
    opf_runtime = OPF(device=device, output_mode="typed", decode_mode="viterbi")  # type: ignore[arg-type]

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        res = opf_runtime.redact(text)
        elapsed = (time.perf_counter() - t0) * 1000
        spans: list[Span] = []
        # Returned type is RedactionResult when output_mode='typed'.
        for sp in getattr(res, "detected_spans", ()) or ():
            label = str(getattr(sp, "label", "")).lower()
            if label not in _OPENAI_LABELS:
                continue
            spans.append(Span(label, int(sp.start), int(sp.end)))
        return ToolResult(spans, elapsed)

    return _predict


def openai_bioes_predictor(
    *,
    device: str | None = None,
    max_length: int = 4096,
) -> Predictor:
    """`openai/privacy-filter` with a Python BIOES decoder.

    The model card prescribes a constrained Viterbi BIOES decoder, but the
    HF `transformers` integration only exposes per-token logits via
    `pipeline()` with `aggregation_strategy="simple"`, which produces
    fragmented spans. This predictor closes most of that gap by running
    the raw model and decoding tags greedily (BIOES adjacency, no Viterbi
    transition cost). Reference for the model's actual quality without
    the official `opf` CLI.
    """
    try:
        import torch  # noqa: I001
        from transformers import AutoModelForTokenClassification, AutoTokenizer
    except ImportError as e:
        raise ImportError("transformers + torch required") from e

    if device is None:
        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"

    if device == "cpu":
        threads = max(1, (os.cpu_count() or 8) // 2)
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(max(1, threads // 4))
        except RuntimeError:
            pass

    tok = AutoTokenizer.from_pretrained("openai/privacy-filter", trust_remote_code=True)
    model = (
        AutoModelForTokenClassification.from_pretrained(
            "openai/privacy-filter", trust_remote_code=True,
        )
        .to(device)
        .eval()
    )
    id2lab = model.config.id2label

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        enc = tok(
            text, return_tensors="pt", return_offsets_mapping=True,
            truncation=True, max_length=max_length,
        )
        offsets = enc.pop("offset_mapping").squeeze(0).tolist()
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            logits = model(**enc).logits.argmax(dim=-1).squeeze(0).tolist()

        spans: list[Span] = []
        cur_label: str | None = None
        cur_start: int | None = None
        cur_end: int | None = None

        def _close() -> None:
            nonlocal cur_label, cur_start, cur_end
            if (
                cur_label is not None
                and cur_start is not None
                and cur_end is not None
                and cur_end > cur_start
            ):
                lab = cur_label.lower()
                if lab in _OPENAI_LABELS:
                    spans.append(Span(lab, cur_start, cur_end))
            cur_label = cur_start = cur_end = None

        for tok_id, (st, en) in zip(logits, offsets):
            if st == en == 0:
                _close()
                continue
            lab = id2lab[tok_id]
            if lab == "O":
                _close()
                continue
            prefix, _, cat = lab.partition("-")
            if prefix == "S":
                _close()
                low = cat.lower()
                if low in _OPENAI_LABELS:
                    spans.append(Span(low, st, en))
            elif prefix == "B":
                _close()
                cur_label, cur_start, cur_end = cat, st, en
            elif prefix in ("I", "E"):
                if cur_label == cat:
                    cur_end = en
                    if prefix == "E":
                        _close()
                else:
                    _close()
        _close()

        elapsed = (time.perf_counter() - t0) * 1000
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
    # AUDIT F12: extended with typographic apostrophes, guillemets,
    # smart-quotes, low-9 quote — common in modern French / Italian /
    # German prose. ASCII-only set previously left these as boundary
    # noise on PII spans.
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


_REGEX_INPUT_MAX_BYTES = 1_000_000  # 1 MB ReDoS guard, AUDIT F22

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {c: i for i, c in enumerate(_BASE58_ALPHABET)}


def _base58check_valid(addr: str) -> bool:
    """Validate a base58check-encoded string (BIP-0013).

    Decodes base58 → bytes; payload + 4-byte checksum;
    SHA256(SHA256(payload))[:4] must equal checksum.

    AUDIT F07: drops false-positive matches on prose tokens that share
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
        # AUDIT F22: refuse to scan inputs > 1 MB. Unbounded `{N,}` quantifiers
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
    # AUDIT F20 REVERTED: IDN-aware pattern `(?<!\w)[\w.%+\-]+@[\w.\-]
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
    # AUDIT F05: was `[ \t]?` — only ASCII space/tab. PDF / online-banking
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
    # AUDIT F07: Bitcoin Legacy address — same regex shape as before
    # (kept for backwards compat) but the `regex_recognizer_predictor`
    # post-filter will validate the base58check checksum. Without
    # validation, any 26-34 char base58-charset prose token (`Order
    # 1A2B3C4D5E6F7G8H9J1K2L3M4N`) was wrongly tagged.
    # Ethereum address (0x prefix + 40 hex)
    ("account_number", r"\b0x[a-fA-F0-9]{40}\b"),
    # UUID v4 (often used as account/customer id)
    ("account_number", r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"),
    # MAC address (hardware identifier).
    # AUDIT F06: lookbehind/lookahead added so `00:11:22:33:44:55:66`
    # (7-octet bus address) is not mis-matched as a 6-octet MAC.
    ("account_number", r"(?<![:0-9A-Fa-f])[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?![:0-9A-Fa-f])"),
    # IPv4 address — AUDIT F06: octet-bounded so `version 3.14.15.92`
    # and `package 2.16.840.1.113883` no longer match.
    ("account_number", r"\b(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"),
    # IPv6 standard (8 hex groups separated by colons)
    ("account_number", r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"),
    # IPv6 compressed (with `::` once). Common formats:
    #   ::1, fe80::1, 2001:db8::, 2001:db8::1, ::ffff:1.2.3.4
    # Loose pattern: requires `::` plus enough flanking hex groups.
    ("account_number", r"\b(?:[0-9a-fA-F]{1,4}:){1,7}:|:(?::[0-9a-fA-F]{1,4}){1,7}|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b"),
    # ─── Additional secret patterns (non-hacky, distinct prefix) ───
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
    # AUDIT F22: bound to {200,400} — Square access tokens are 218 chars;
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
    # AUDIT F19: Italian Codice Fiscale — 6 alpha + 2 digit + month-letter
    # (one of A-EHLMPRST) + 2 digit day + alpha + 3 digit + control letter.
    # Comment claimed it was added; the pattern was missing.
    ("account_number", r"\b[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]\b"),
    # ─── Phone — international format anchored on `+` ──────────────
    # `+CC NNN NNN NNNN` / `+CC-NNN-NNN-NNNN` / `+CC NNNNNNNNNN` etc.
    # Anchored on the leading `+` to avoid matching version strings,
    # IDs, etc. that have similar digit groupings.
    ("private_phone", r"\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{3,8}"),
    # AUDIT F09: domestic formats with REQUIRED context anchor.
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


# AUDIT F08: re-finditer over `https?://` inside an outer URL match,
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
        """AUDIT F08: when a single URL match contains query-param URLs
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


# Backwards-compat alias — `EXTENDED_REGEX_PATTERNS` was the merged
# default+gitleaks pack while we A/B'd the two. After the merge it's
# identical to `DEFAULT_REGEX_PATTERNS`. Kept to avoid breaking the
# bench harness that imported it; new code should use
# `DEFAULT_REGEX_PATTERNS` directly.
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
    # AUDIT F20 REVERTED: IDN-aware pattern `(?<!\w)[\w.%+\-]+@[\w.\-]
    # +\.[\w]{2,24}(?!\w)` produced 336 FP / 500 matches on
    # nullpii-bench (Unicode `\w` matched arbitrary identifier-like
    # strings as email local parts). IDN coverage is now handled by
    # `_normalize_for_detection` (NFKC + unidecode) which converts
    # `john@münchen.de` → `john@munchen.de`, allowing the ASCII
    # pattern to match. True non-Latin emails (`用户@例え.jp`) remain
    # uncovered until a more restrictive Unicode pattern is designed.
    # IBAN (rough — IT, GB, DE, FR, ES)
    # AUDIT F05: was `[ \t]?` — only ASCII space/tab. PDF / online-banking
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
    # AUDIT F09: domestic formats with REQUIRED context anchor.
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

# NANP fictional phone prefix (ITU-T E.164 / NANP-reserved). Only the
# subscriber range 555-0100 through 555-0199 is universally fictional.
# AUDIT F18: previous regex matched ANY 555-prefixed number with a
# 7-digit subscriber, dropping legitimate `1-555-XXX-XXXX` calls in
# any region. Restricted to the reserved 0100-0199 block (subscriber
# starts with `01` followed by two digits).
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


def encoding_deobf_predictor(*, inner: Predictor) -> Predictor:
    """De-obfuscate base64 / URL-encoded / HTML-entity wrapped PII.

    Detects encoded substrings and tries to decode them; if the decoded
    text contains PII per the inner predictor, flags the *encoded*
    substring (in the original text) with the union of detected labels.

    Detectors:
      - base64 candidate: `[A-Za-z0-9+/]{16,}={0,2}`, length divisible
        by 4, decoded bytes valid UTF-8
      - URL-encoded: substring containing `%[0-9A-Fa-f]{2}` patterns
      - HTML entity: substring containing `&#\\d+;` patterns

    Strict: only flags the encoded span if the decoded text passes a
    PII check via the inner predictor. False-positive risk on legit
    base64 / URL-encoded data (cert bytes, JSON tokens, encoded files)
    is mitigated by requiring the decoded result to actually pass PII
    detection — random base64 won't decode to email/phone/secret-shape
    text.

    Off by default. Enable via `--enable-deobf-encoding` for workloads
    where evasion via encoding is likely (chat platforms with active
    blocking, content moderation pipelines)."""
    import base64 as _base64
    import html as _html
    import re as _re
    import urllib.parse as _urlparse

    _BASE64_RE = _re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
    _URL_ENC_RE = _re.compile(r"(?:%[0-9A-Fa-f]{2}){2,}[A-Za-z0-9._%+\-@/:]*")
    _HTML_ENT_RE = _re.compile(r"(?:&#\d+;)+[A-Za-z0-9._@\-+]*")

    def _try_b64(s: str) -> str | None:
        if len(s) % 4 != 0:
            return None
        try:
            decoded = _base64.b64decode(s, validate=True)
            return decoded.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    def _try_url(s: str) -> str | None:
        try:
            decoded = _urlparse.unquote(s)
            if decoded == s:
                return None
            return decoded
        except (ValueError, UnicodeDecodeError):
            return None

    def _try_html(s: str) -> str | None:
        try:
            decoded = _html.unescape(s)
            if decoded == s:
                return None
            return decoded
        except (ValueError, UnicodeDecodeError):
            return None

    def _predict(text: str) -> ToolResult:
        original = inner(text)
        spans: list[Span] = list(original.spans)
        for regex, decoder in (
            (_BASE64_RE, _try_b64),
            (_URL_ENC_RE, _try_url),
            (_HTML_ENT_RE, _try_html),
        ):
            for m in regex.finditer(text):
                encoded = m.group()
                decoded = decoder(encoded)
                if not decoded or len(decoded) < 4:
                    continue
                sub = inner(decoded)
                if not sub.spans:
                    continue
                # Flag the encoded substring with each detected label.
                seen_labels: set[str] = set()
                for sp in sub.spans:
                    if sp.label in seen_labels:
                        continue
                    seen_labels.add(sp.label)
                    spans.append(Span(sp.label, m.start(), m.end()))
        # Dedupe identical spans.
        unique: list[Span] = []
        seen: set[tuple[str, int, int]] = set()
        for sp in spans:
            key = (sp.label, sp.start, sp.end)
            if key in seen:
                continue
            seen.add(key)
            unique.append(sp)
        unique.sort(key=lambda s: s.start)
        return ToolResult(unique, original.elapsed_ms)

    return _predict


def whitespace_deobf_predictor(*, inner: Predictor) -> Predictor:
    """De-obfuscate whitespace-separated PII before detection.

    Marketplace / chat / e-commerce vendors often face users trying to
    evade contact-info detection by inserting spaces between letters
    (`g i a n l u c a @ g m a i l . c o m`, `+ 3 9 3 3 3 1 2 3 4 5 6 7`).
    This wrapper:

      1. Runs `inner` on the original text → first-pass spans.
      2. Detects runs of 5+ consecutive single-char tokens separated
         by single spaces (`(?:[\\w@.+\\-]\\s){4,}[\\w@.+\\-]\\b`).
      3. Collapses each run (removes spaces), runs `inner` on the
         collapsed text, maps detected spans back to the original
         positions.
      4. Returns the union (de-duplicated by label + overlap).

    Off by default in the production pipeline. Enable via
    `--enable-deobf-whitespace` for marketplace / dating / chat
    workloads where users actively try to share contact info despite
    a vendor-side block.
    """
    import re as _re

    _SPACED_RUN = _re.compile(r"(?:[\w@.+\-]\s){4,}[\w@.+\-]\b")

    def _collapse(text: str, start: int, end: int) -> tuple[str, list[int]]:
        out_chars: list[str] = []
        pos_map: list[int] = []
        for i in range(start, end):
            ch = text[i]
            if ch != " ":
                out_chars.append(ch)
                pos_map.append(i)
        return "".join(out_chars), pos_map

    def _overlaps(a: Span, b: Span) -> bool:
        return a.start < b.end and b.start < a.end

    def _predict(text: str) -> ToolResult:
        original = inner(text)
        spans: list[Span] = list(original.spans)
        for m in _SPACED_RUN.finditer(text):
            run_start, run_end = m.start(), m.end()
            collapsed, pos_map = _collapse(text, run_start, run_end)
            if len(collapsed) < 5:
                continue
            sub = inner(collapsed)
            for sp in sub.spans:
                if sp.end <= 0 or sp.end > len(pos_map):
                    continue
                orig_start = pos_map[sp.start]
                orig_end = pos_map[sp.end - 1] + 1
                spans.append(Span(sp.label, orig_start, orig_end))
        # Dedupe: drop spans fully contained by another span with same label.
        spans.sort(key=lambda s: (s.start, -s.end))
        kept: list[Span] = []
        for sp in spans:
            redundant = False
            for k in kept:
                if k.label == sp.label and _overlaps(sp, k):
                    if k.start <= sp.start and k.end >= sp.end:
                        redundant = True
                        break
            if not redundant:
                kept.append(sp)
        return ToolResult(kept, original.elapsed_ms)

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


def stopword_filter_predictor(
    *,
    inner: Predictor,
    stopwords: dict[str, frozenset[str]] = STOPWORD_BY_LABEL,
) -> Predictor:
    """Wraps a predictor and drops predicted spans whose surface form
    (case-insensitive, stripped) matches the per-label stopword set.

    Used to suppress generic-noun FPs the model emits as named entities
    (e.g. `Male`/`Female`/`I` flagged as `private_person`, `email` as
    `private_email`, `phone` as `private_phone`).
    """

    def _predict(text: str) -> ToolResult:
        result = inner(text)
        kept: list[Span] = []
        for sp in result.spans:
            pool = stopwords.get(sp.label)
            if pool is None:
                kept.append(sp)
                continue
            surface = text[sp.start:sp.end].strip().lower()
            if surface in pool:
                continue
            kept.append(sp)
        return ToolResult(kept, result.elapsed_ms)

    return _predict


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


def semantic_verifier_predictor(
    *,
    inner: Predictor,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    context_chars: int = 30,
    anchors: dict[str, list[str]] = PII_ANCHOR_TEXTS,
    threshold: float | None = None,
    calibration_samples: list | None = None,
    calibration_percentile: float = 5.0,
    threshold_cache_path: Path | None = None,
) -> Predictor:
    """Zero-shot semantic verifier — drops predicted spans whose local
    context is semantically far from their predicted label.

    Pipeline per call:
      1. Run `inner` predictor → raw spans + scores.
      2. For each span, embed `text[start - context_chars : end + context_chars]`.
      3. Compute cosine sim to all anchors of the predicted label, take max.
      4. Drop the span if max sim < threshold.

    Threshold derivation (no bench leakage):
      If `threshold` is None, calibrate on `calibration_samples` (a list
      of `Sample` objects with gold spans). For each gold span: embed
      its local context, compute max cosine similarity to its label's
      anchors. Threshold is set at the `calibration_percentile`-th
      percentile of these similarities (default 5th — keep ~95% of
      true-positive contexts above the bar). The calibration corpus
      MUST be disjoint from any bench evaluation set; ai4privacy rows
      0–50k are recommended as the default disjoint slice (bench eval
      uses rows 300k+).
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise ImportError("sentence-transformers required") from e

    import numpy as np  # noqa: I001

    model = SentenceTransformer(model_name)
    label_to_emb: dict[str, np.ndarray] = {}
    for label, texts in anchors.items():
        embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        label_to_emb[label] = np.asarray(embs)

    if threshold is None:
        # Try cached threshold first.
        cache_key = f"{model_name}|p{calibration_percentile}|c{context_chars}"
        if threshold_cache_path and threshold_cache_path.is_file():
            try:
                cached = json.loads(threshold_cache_path.read_text())
                if cached.get("key") == cache_key:
                    threshold = float(cached["threshold"])
            except (json.JSONDecodeError, ValueError, KeyError):
                pass
        if threshold is None:
            if not calibration_samples:
                raise ValueError(
                    "threshold is None and no calibration_samples / cache "
                    "provided — pass either an explicit threshold or a "
                    "disjoint calibration corpus.",
                )
            sims_list: list[float] = []
            for sample in calibration_samples:
                if not sample.spans:
                    continue
                contexts = []
                labels = []
                for sp in sample.spans:
                    if sp.label not in label_to_emb:
                        continue
                    ctx_start = max(0, sp.start - context_chars)
                    ctx_end = min(len(sample.text), sp.end + context_chars)
                    contexts.append(sample.text[ctx_start:ctx_end])
                    labels.append(sp.label)
                if not contexts:
                    continue
                ctx_embs = np.asarray(
                    model.encode(
                        contexts,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    ),
                )
                for k, lab in enumerate(labels):
                    sims = ctx_embs[k] @ label_to_emb[lab].T
                    sims_list.append(float(sims.max()))
            if not sims_list:
                raise ValueError(
                    "calibration produced no similarities — calibration "
                    "corpus may be missing labels in the anchor map.",
                )
            threshold = float(np.percentile(sims_list, calibration_percentile))
            if threshold_cache_path:
                threshold_cache_path.parent.mkdir(parents=True, exist_ok=True)
                threshold_cache_path.write_text(json.dumps({
                    "key": cache_key,
                    "threshold": threshold,
                    "n_samples": len(sims_list),
                    "percentile": calibration_percentile,
                }, indent=2))

    def _predict(text: str) -> ToolResult:
        result = inner(text)
        if not result.spans:
            return result
        # Build parallel arrays: span index -> (context, label) for spans
        # whose label has anchors. Spans with unknown label pass through.
        verifiable: list[tuple[int, str, str]] = []  # (span_idx, ctx, label)
        kept: list[Span] = []
        for i, sp in enumerate(result.spans):
            if sp.label not in label_to_emb:
                kept.append(sp)
                continue
            ctx_start = max(0, sp.start - context_chars)
            ctx_end = min(len(text), sp.end + context_chars)
            verifiable.append((i, text[ctx_start:ctx_end], sp.label))
        if not verifiable:
            kept.sort(key=lambda s: s.start)
            return ToolResult(kept, result.elapsed_ms)
        ctx_embs = np.asarray(
            model.encode(
                [v[1] for v in verifiable],
                normalize_embeddings=True,
                show_progress_bar=False,
            ),
        )
        for j, (span_idx, _ctx, label) in enumerate(verifiable):
            sims = ctx_embs[j] @ label_to_emb[label].T
            if float(sims.max()) >= threshold:
                kept.append(result.spans[span_idx])
        kept.sort(key=lambda s: s.start)
        return ToolResult(kept, result.elapsed_ms)

    return _predict


def tiny_verifier_predictor(
    *,
    inner: Predictor,
    model_dir: Path,
    context_chars: int = 50,
    threshold: float = 0.5,
    batch_size: int = 32,
    max_length: int = 192,
    device: str | None = None,
) -> Predictor:
    """Trained binary verifier — drops predicted spans whose
    `(span, context, label)` triple is classified as non-PII by a
    fine-tuned MiniLM/DistilBERT classifier.

    Pipeline per call:
      1. Run `inner` predictor → raw spans.
      2. For each span, build `(span_text, context_string, label)`.
      3. Batched forward pass through verifier model → P(is_pii).
      4. Drop spans with P < `threshold`.

    Training (off-bench):
      Verifier is trained on disjoint corpus (e.g. ai4privacy rows
      0–N where N < bench eval offset). Bench eval distributions
      (nullpii-bench, isotonic, oasst, presidio-synthetic, ai4privacy
      300k+) are NOT seen during training — clean held-out evaluation.

    Format must match the training script's input format:
      `[CLS] {span_text} [SEP] {context}<span>{span}</span>... [LABEL] {label} [SEP]`
    """
    try:
        import torch  # noqa: I001
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )
    except ImportError as e:
        raise ImportError("torch + transformers required") from e

    if device is None:
        device = (
            "mps" if torch.backends.mps.is_available()
            else "cuda" if torch.cuda.is_available()
            else "cpu"
        )

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
    model = model.to(device)
    model.eval()

    def _build_context(text: str, start: int, end: int) -> str:
        left = text[max(0, start - context_chars):start]
        span = text[start:end]
        right = text[end:min(len(text), end + context_chars)]
        return f"{left}<span>{span}</span>{right}"

    def _predict(text: str) -> ToolResult:
        result = inner(text)
        if not result.spans:
            return result
        # Build (span_text, second_text) pairs matching training format.
        pairs: list[tuple[str, str]] = []
        for sp in result.spans:
            ctx = _build_context(text, sp.start, sp.end)
            second = f"{ctx} [LABEL] {sp.label}"
            pairs.append((text[sp.start:sp.end], second))

        kept: list[Span] = []
        with torch.no_grad():
            for i in range(0, len(pairs), batch_size):
                batch = pairs[i:i + batch_size]
                texts_a = [p[0] for p in batch]
                texts_b = [p[1] for p in batch]
                enc = tokenizer(
                    texts_a, texts_b,
                    truncation=True,
                    max_length=max_length,
                    padding=True,
                    return_tensors="pt",
                ).to(device)
                logits = model(**enc).logits
                probs = torch.softmax(logits, dim=-1)[:, 1]
                for j, p in enumerate(probs.cpu().tolist()):
                    if p >= threshold:
                        kept.append(result.spans[i + j])
        kept.sort(key=lambda s: s.start)
        return ToolResult(kept, result.elapsed_ms)

    return _predict


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
    # NOTE: honorifics "Mr ", "Mrs ", "Ms " removed — they appear
    # constantly in dev-paste customer-support text and false-route
    # dev-paste content to the v8 backbone (per iter-v8 compliance review).
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


def complementary_v6_v8_predictor(
    *,
    v6_predictor: Predictor,
    v8_predictor: Predictor,
    extra_predictors: list[Predictor] | None = None,
) -> Predictor:
    """Domain-routing ensemble: pick v6 OR v8 per-input based on a fixed
    a-priori heuristic (`_is_dev_paste_like`). On dev-paste-style text
    v6 wins; on structured/legal text v8 wins. `extra_predictors` (e.g.
    a regex/url-filter pass) always run and their spans are unioned in
    via longest-wins overlap resolution (same as `union` strategy).

    Heuristic is NOT tuned on bench eval datasets — see
    `_is_dev_paste_like` docstring."""
    extras = list(extra_predictors or [])

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
                if (s.end - s.start) > (prev.end - prev.start):
                    out[i] = s
                replaced = True
                break
            if not replaced:
                out.append(s)
        return sorted(out, key=lambda s: s.start)

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        chosen = v6_predictor if _is_dev_paste_like(text) else v8_predictor
        primary_result = chosen(text)
        all_spans: list[Span] = list(primary_result.spans)
        for extra in extras:
            r = extra(text)
            for s in r.spans:
                if not any(_overlaps(s, p) for p in all_spans):
                    all_spans.append(s)
        merged = _dedupe_longest(all_spans)
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(merged, elapsed)

    return _predict


def gliner_chunked_predictor(
    *,
    model_path: str = "urchade/gliner_multi_pii-v1",
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

    `model_path` defaults to the PII-specialised v1 baseline. Pass
    `urchade/gliner_multi-v2.1` to compare a generic-NER GLiNER v2.1
    backbone (no PII fine-tuning) on the same chunking + dedupe path.

    Char-level chunking (4 chars/token approximation): 1400 chars ≈ 350
    tokens, well under GLiNER's mBERT-base 512-tok cap. 200 char overlap
    keeps any short span fully visible in at least one chunk."""
    try:
        from gliner import GLiNER  # noqa: I001
    except ImportError as e:
        raise ImportError("gliner required") from e

    model = GLiNER.from_pretrained(model_path)

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


_NULLPII_8 = [
    "account_number",
    "private_address",
    "private_date",
    "private_email",
    "private_person",
    "private_phone",
    "private_url",
    "secret",
]

# Expanded inference-time prompt set. GLiNER is prompt-based (model
# interprets the semantic meaning of each label string), so we can
# query with finer-grained labels at inference and map back to the
# 8-class schema for output. Goal: lift recall on Nemotron-style
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
    "GPS coordinate": "private_address",
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
    "passport number": "account_number",
    "driver license": "account_number",
    "medical record number": "account_number",
    "vehicle VIN": "account_number",
    "license plate": "account_number",
    "MAC address": "account_number",
    "IP address": "account_number",
    "secret": "secret",
    "password": "secret",
    "PIN code": "secret",
    "API key": "secret",
}

# nvidia/gliner-PII (Nemotron PII) was trained on 55+ entity types
# (`nvidia/Nemotron-PII` dataset). Pass these labels at inference; the
# wrapper `_NEMOTRON_TO_NULLPII8` then maps each predicted label back
# to nullpii's 8-class schema for a fair F1 comparison.
_NEMOTRON_PII_LABELS = [
    "first_name", "last_name", "user_name",
    "email", "phone_number",
    "street_address", "city", "county", "state", "postcode", "country",
    "coordinate",
    "date", "time", "date_time", "date_of_birth", "age",
    "url",
    "ssn", "account_number", "bank_routing_number", "swift_bic", "cvv",
    "credit_debit_card", "employee_id", "customer_id",
    "medical_record_number", "health_plan_beneficiary_number",
    "vehicle_identifier", "license_plate", "certificate_license_number",
    "mac_address", "ipv4", "device_identifier",
    "password", "pin", "biometric_identifier",
]

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
    "coordinate": "private_address",
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
    "vehicle_identifier": "account_number",
    "license_plate": "account_number",
    "certificate_license_number": "account_number",
    "mac_address": "account_number",
    "ipv4": "account_number",
    "device_identifier": "account_number",
    "password": "secret",
    "pin": "secret",
    "biometric_identifier": "secret",
}


def gliner_v2_predictor(
    model_path: str,
    *,
    onnx_file: str | None = None,
    device: str = "cuda",
    threshold: float = 0.5,
    local_files_only: bool = True,
    chunk_chars: int = 1400,
    overlap_chars: int = 200,
    normalize_input: bool = False,
) -> Predictor:
    """Predictor for our fine-tuned GLiNER (v2). Trained directly on the
    nullpii 8-category schema, so no label remap — labels passed verbatim.

    Loads either the PyTorch checkpoint (`onnx_file=None`) on the chosen
    device, or an exported ONNX model (`onnx_file="model_int4.onnx"`,
    forced to CPU since onnxruntime CPUExecutionProvider is what we ship).
    Chunking + dedupe identical to gliner_chunked_predictor.
    """
    try:
        from gliner import GLiNER
    except ImportError as e:
        raise ImportError("gliner required") from e

    kwargs: dict = {"local_files_only": local_files_only}
    if onnx_file:
        kwargs["load_onnx_model"] = True
        kwargs["onnx_model_file"] = onnx_file
        model = GLiNER.from_pretrained(model_path, **kwargs)
    else:
        model = GLiNER.from_pretrained(model_path, **kwargs).to(device)
        model.eval()

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

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        scores: list[float] = []
        if normalize_input:
            inference_text, norm_to_orig = _normalize_for_detection(text)
        else:
            inference_text = text
            norm_to_orig = None
        text_len = len(inference_text)
        if text_len <= chunk_chars:
            for e in model.predict_entities(inference_text, _NULLPII_8, threshold=threshold):
                ns, ne = int(e["start"]), int(e["end"])
                if norm_to_orig is not None:
                    os_, oe = _remap_span(ns, ne, norm_to_orig)
                else:
                    os_, oe = ns, ne
                spans.append(Span(e["label"], os_, oe))
                scores.append(float(e.get("score", threshold)))
        else:
            stride = chunk_chars - overlap_chars
            spans_with_scores: list[tuple[Span, float]] = []
            for offset in range(0, text_len, stride):
                chunk = inference_text[offset : offset + chunk_chars]
                if not chunk:
                    break
                for e in model.predict_entities(chunk, _NULLPII_8, threshold=threshold):
                    ns_chunk, ne_chunk = int(e["start"]), int(e["end"])
                    ns_full, ne_full = ns_chunk + offset, ne_chunk + offset
                    if norm_to_orig is not None:
                        os_, oe = _remap_span(ns_full, ne_full, norm_to_orig)
                    else:
                        os_, oe = ns_full, ne_full
                    spans_with_scores.append((
                        Span(e["label"], os_, oe),
                        float(e.get("score", threshold)),
                    ))
                if offset + chunk_chars >= text_len:
                    break
            # Dedupe preserving the highest score per kept span.
            kept = _dedupe([sp for sp, _ in spans_with_scores])
            score_by_id = {id(sp): sc for sp, sc in spans_with_scores}
            for sp in kept:
                spans.append(sp)
                scores.append(score_by_id.get(id(sp), threshold))
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(spans, elapsed, scores=tuple(scores))

    return _predict


_HTML_ENTITY_RE = re.compile(r"&#(\d+);|&#x([0-9a-fA-F]+);")
_URL_PERCENT_RE = re.compile(r"%([0-9a-fA-F]{2})")
_ZERO_WIDTH_CHARS = frozenset("​‌‍﻿⁠­")
# Detect whitespace-obfuscated PII (e.g. `+ 4 9   3 0   1 2 3 4 5 6 7 8`).
# AUDIT F01/F02: tightened from `{5,}` to `{3,}` (catches `+ 4 9 3 0`)
# AND anchored at non-word boundary `(?<!\w)` (does not start mid-word —
# avoids mangling "Mary J. Doe age 4 7" by chopping the suffix `y J . D
# e 4 7`). Char class adds `:` and `/` (catches spaced URLs / IPs).
# Post-check requires ≥4 digits OR (≥1 `@` + ≥1 letter) so prose like
# "I a m a g i r l" still does not despace.
_SPACED_PII_RE = re.compile(r"(?<!\w)(?:[\w@.+\-:/]\s+){3,}[\w@.+\-:/]")


_NORMALIZE_INPUT_MAX_BYTES = 1_000_000  # AUDIT F23 cap


def _is_pure_ascii_no_decode_needed(text: str) -> bool:
    """Fast-path test for `_normalize_for_detection`. AUDIT F24.

    Returns True iff the input is pure ASCII AND has no triggers for
    the despace / URL %XX / HTML entity decode paths. The narrower-
    than-Python-proposal check matches the TS port — despace and
    decode legitimately apply to ASCII input, so an unconditional
    "ASCII → identity passthrough" would lose correctness.
    """
    if "&#" in text or "%" in text:
        return False
    if any(ord(c) > 127 for c in text):
        return False
    if _SPACED_PII_RE.search(text):
        return False
    return True


def _normalize_for_detection(text: str) -> tuple[str, list[int]]:
    """Adversarial-resistant input normalisation with offset map.

    Applies, in order:
    - HTML numeric entity decode (`&#115;` → `s`)
    - Zero-width / soft-hyphen strip
    - Per-char NFKC + unidecode for non-ASCII (Cyrillic homoglyphs,
      fullwidth digits, mathematical fonts → ASCII equivalent)

    Returns `(normalized_text, norm_to_orig)`. `norm_to_orig[i]` is
    the original-text index of the i-th char in the normalized text;
    sentinel at the end equals `len(text)` so span ends remap cleanly.

    The adapter receives the normalised text; output spans are remapped
    back to original-text offsets via the index map. Original gold
    spans use original offsets, so this preserves bench correctness
    while letting the model see a cleaner input.

    AUDIT F23: input length cap. `_SPACED_PII_RE.match(text, i)` per
    position is O(N²) on whitespace-rich adversarial input (100 KB
    of `a a a a` → ~5 s in CPython). 1 MB cap matches the regex pack
    upstream guard; oversized input falls through as identity
    passthrough. Any realistic LLM prompt is far below this cap.
    """
    if len(text) > _NORMALIZE_INPUT_MAX_BYTES:
        return text, list(range(len(text) + 1))
    # AUDIT F24: ASCII fast-path. Per-char NFKC + Python loop costs
    # ~100 ms on a 50 KB ASCII input (no work to do). Skip entirely
    # if the text has no non-ASCII bytes, no `&#` (HTML entity
    # candidate), no `%` (URL %XX candidate), and no whitespace run
    # of length ≥ 4 single chars (despace candidate). Mirrors the TS
    # port's `isPureAsciiNoDecodeNeeded` check.
    if _is_pure_ascii_no_decode_needed(text):
        return text, list(range(len(text) + 1))
    try:
        from unidecode import unidecode
    except ImportError:
        unidecode = None
    out: list[str] = []
    norm_to_orig: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        # Whitespace-obfuscated PII collapse (e.g. "1 2 3 4 5" → "12345").
        # AUDIT F01/F02: gated by stricter post-check — require ≥4 digits OR
        # (≥1 `@` + ≥1 letter). Without this guard, a sentence with sparse
        # digits could despace into a phone-shaped string (`Mary J. Doe age
        # 4 7` → `yJ.De47`).
        m_sp = _SPACED_PII_RE.match(text, i)
        if m_sp:
            run = m_sp.group(0)
            digit_count = sum(1 for c in run if c.isdigit())
            has_at = "@" in run
            has_alpha = any(c.isalpha() for c in run)
            if digit_count >= 4 or (has_at and has_alpha):
                for j, c in enumerate(run):
                    if c.isspace():
                        continue
                    out.append(c)
                    norm_to_orig.append(i + j)
                i += len(run)
                continue
        # URL percent-encoding decode (`%40` → `@`)
        m_url = _URL_PERCENT_RE.match(text, i)
        if m_url:
            try:
                decoded_char = chr(int(m_url.group(1), 16))
            except (ValueError, OverflowError):
                decoded_char = ""
            # AUDIT F03 (mirror): preserve email-anchor chars in original
            # form so the email regex can still match.
            if decoded_char in ("@", ".", "+", "-"):
                decoded_char = ""
            if decoded_char:
                # AUDIT F04: map decoded char to the END of the triplet
                # (last byte of `%XX`) so a span that ends at this
                # decoded char remaps to the original-text END of the
                # triplet, not its start. Previously every decoded char
                # mapped to the same start index → only the first
                # triplet of a multi-decoded URL was redacted.
                out.append(decoded_char)
                norm_to_orig.append(i + 2)
                i += 3
                continue
        # HTML numeric entity decode
        m = _HTML_ENTITY_RE.match(text, i)
        if m:
            try:
                if m.group(1):
                    decoded = chr(int(m.group(1)))
                else:
                    decoded = chr(int(m.group(2), 16))
            except (ValueError, OverflowError):
                decoded = ""
            # AUDIT F03: do NOT decode `@` / `.` / `+` / `-` because the
            # downstream email regex anchors on those literals; an
            # unconditional decode of `j&#x40;ohn@example.com` produces
            # `j@ohn@example.com` (two `@`) which the email regex
            # rejects entirely. Keep the entity intact for those chars.
            if decoded in ("@", ".", "+", "-"):
                decoded = ""
            if decoded:
                for c in decoded:
                    out.append(c)
                    norm_to_orig.append(i)
                i += len(m.group(0))
                continue
        c = text[i]
        if c in _ZERO_WIDTH_CHARS:
            i += 1
            continue
        nfkc = unicodedata.normalize("NFKC", c)
        if any(ord(ch) > 127 for ch in nfkc) and unidecode is not None:
            transliterated = unidecode(nfkc)
            if transliterated:
                for tc in transliterated:
                    out.append(tc)
                    norm_to_orig.append(i)
                i += 1
                continue
        for nc in nfkc:
            out.append(nc)
            norm_to_orig.append(i)
        i += 1
    norm_to_orig.append(n)
    return "".join(out), norm_to_orig


def _remap_span(norm_start: int, norm_end: int, norm_to_orig: list[int]) -> tuple[int, int]:
    """Map a normalized [start, end) span to the original text.

    AUDIT F10: previous `>=` clamp truncated by one character when the
    model predicted `end == len(normalised)`. The sentinel at index
    `len(norm_to_orig) - 1` is exactly the valid end-exclusive
    position, not out-of-bounds. Use strict `min(..., max_idx)` clamp.
    """
    max_idx = len(norm_to_orig) - 1
    ns = max(0, min(norm_start, max_idx))
    ne = max(0, min(norm_end, max_idx))
    return norm_to_orig[ns], norm_to_orig[ne]


def gliner_nemotron_pii_predictor(
    *,
    model_path: str = "nvidia/gliner-pii",
    device: str = "cpu",
    threshold: float = 0.3,
    chunk_chars: int = 1400,
    overlap_chars: int = 200,
    normalize_input: bool = False,
) -> Predictor:
    """Wrapper for `nvidia/gliner-PII` (Nemotron PII model). Predicts
    on the 55+ Nemotron PII labels and maps each result back to nullpii's
    8-class schema via `_NEMOTRON_TO_NULLPII8` so F1 is computed against
    the same gold labels as our adapters.

    Default threshold 0.3 follows Nvidia's evaluation recipe (model card).
    Backbone is `urchade/gliner_large-v2.1` (~600M params, 2× the size
    of our v6/v10 backbone `urchade/gliner_multi_pii-v1` ~280M).
    """
    try:
        from gliner import GLiNER
    except ImportError as e:
        raise ImportError("gliner required") from e

    model = GLiNER.from_pretrained(model_path, local_files_only=False).to(device)
    model.eval()

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

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        scores: list[float] = []
        if normalize_input:
            inference_text, norm_to_orig = _normalize_for_detection(text)
        else:
            inference_text = text
            norm_to_orig = None
        text_len = len(inference_text)
        if text_len <= chunk_chars:
            entities = model.predict_entities(
                inference_text, _NEMOTRON_PII_LABELS, threshold=threshold,
            )
            for e in entities:
                mapped = _NEMOTRON_TO_NULLPII8.get(e["label"])
                if mapped is None:
                    continue
                ns, ne = int(e["start"]), int(e["end"])
                if norm_to_orig is not None:
                    os_, oe = _remap_span(ns, ne, norm_to_orig)
                else:
                    os_, oe = ns, ne
                spans.append(Span(mapped, os_, oe))
                scores.append(float(e.get("score", threshold)))
        else:
            stride = chunk_chars - overlap_chars
            spans_with_scores: list[tuple[Span, float]] = []
            for offset in range(0, text_len, stride):
                chunk = inference_text[offset:offset + chunk_chars]
                if not chunk:
                    break
                for e in model.predict_entities(chunk, _NEMOTRON_PII_LABELS, threshold=threshold):
                    mapped = _NEMOTRON_TO_NULLPII8.get(e["label"])
                    if mapped is None:
                        continue
                    ns_chunk, ne_chunk = int(e["start"]), int(e["end"])
                    ns_full, ne_full = ns_chunk + offset, ne_chunk + offset
                    if norm_to_orig is not None:
                        os_, oe = _remap_span(ns_full, ne_full, norm_to_orig)
                    else:
                        os_, oe = ns_full, ne_full
                    spans_with_scores.append((
                        Span(mapped, os_, oe),
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


def gliner2_predictor(
    *,
    model_path: str = "fastino/gliner2-large-v1",
    device: str = "cpu",
    threshold: float = 0.3,
    chunk_chars: int = 1400,
    overlap_chars: int = 200,
) -> Predictor:
    """Wrapper for `fastino/gliner2-{base,large,multi}-v1` (GLiNER2,
    fastino-ai). Schema-agnostic information-extraction model;
    backbone `microsoft/deberta-v3-{base,large}` per variant.
    Output is span-level (`include_spans=True` returns `{text, start,
    end, confidence}` per entity), so it slots into the bench's
    IoU-based F1 metric directly.

    Bare-mode usage: no nullpii post-processing (no boundary refine,
    never_pii filter, or regex pack). Chunking is preserved at the
    standard 1400/200 stride to handle long inputs (TAB ECHR, dev
    pastes); same chunking that wraps `nemotron-pii-raw` and
    `gliner-onnx-pii-fp32`.

    Predicts directly on the 8-class nullpii schema (`_NULLPII_8`);
    GLiNER2 is schema-agnostic, so the labels become the prompt at
    inference time. No re-mapping required.
    """
    try:
        from gliner2 import GLiNER2  # type: ignore
    except ImportError as e:
        raise ImportError("gliner2 required (pip install gliner2)") from e

    model = GLiNER2.from_pretrained(model_path)
    if hasattr(model, "to") and device != "cpu":
        try:
            model = model.to(device)
        except Exception:
            pass

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

    def _flatten(result: dict) -> list[tuple[str, dict]]:
        ents = result.get("entities", {}) if isinstance(result, dict) else {}
        out: list[tuple[str, dict]] = []
        for label, items in ents.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict) and "start" in it and "end" in it:
                    out.append((label, it))
        return out

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        scores: list[float] = []
        text_len = len(text)
        if text_len <= chunk_chars:
            r = model.extract_entities(
                text, list(_NULLPII_8),
                threshold=threshold,
                include_spans=True,
                include_confidence=True,
            )
            for label, e in _flatten(r):
                spans.append(Span(label, int(e["start"]), int(e["end"])))
                scores.append(float(e.get("confidence", threshold)))
        else:
            stride = chunk_chars - overlap_chars
            spans_with_scores: list[tuple[Span, float]] = []
            for offset in range(0, text_len, stride):
                chunk = text[offset:offset + chunk_chars]
                if not chunk:
                    break
                r = model.extract_entities(
                    chunk, list(_NULLPII_8),
                    threshold=threshold,
                    include_spans=True,
                    include_confidence=True,
                )
                for label, e in _flatten(r):
                    s, en = int(e["start"]) + offset, int(e["end"]) + offset
                    spans_with_scores.append((
                        Span(label, s, en),
                        float(e.get("confidence", threshold)),
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

    Used by the v10 per-domain profile tool defs in `bench_full.py`.
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

    # AUDIT_B: optionally use the expanded prompt set (`_NULLPII_EXPANDED_
    # PROMPTS`) and remap finer-grained predictions back to the 8-class
    # schema via `_EXPANDED_PROMPT_TO_NULLPII8`. Goal: lift recall on
    # Nemotron-style US-business records (`cvv`, `swift_bic`, `gps`,
    # `passport`, `medical record number`, etc.) without retraining.
    prompts_for_inference = (
        _NULLPII_EXPANDED_PROMPTS if use_expanded_prompts else _NULLPII_8
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

    Used by the v10 router tool def in `bench_full.py`. Underlying
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


def scrubadub_predictor() -> Predictor:
    """Wrap scrubadub (Apache-2.0, regex+detector chain) as a PII predictor.

    Uses the default Scrubber detector set (credential, credit_card,
    email, phone, twitter handle, url, SSN). NameDetector is not
    enabled by default — would require spaCy install and adds noise.
    """
    try:
        import scrubadub
    except ImportError as e:
        raise ImportError(
            "scrubadub not installed; run `pip install scrubadub`",
        ) from e

    scrubber = scrubadub.Scrubber()

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        for f in scrubber.iter_filth(text):
            label = _SCRUBADUB_LABEL_MAP.get(f.type)
            if label is None:
                continue
            spans.append(Span(label, int(f.beg), int(f.end)))
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(spans, elapsed)

    return _predict


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
    "IP_ADDRESS": "account_number",
    "MAC_ADDRESS": "account_number",
    "PASSPORT_NUMBER": "account_number",
    "DRIVER_ID": "account_number",
    "LICENSE_PLATE": "account_number",
}


def aws_comprehend_predictor(*, language: str = "en", region: str = "us-east-1") -> Predictor:
    """AWS Comprehend `detect_pii_entities` predictor. Requires AWS
    credentials + boto3. Cost: $1.20 per 1M chars (50–100 USD for full
    bench). Bench-only — not for production."""
    try:
        import boto3
    except ImportError as e:
        raise ImportError("boto3 required; run `pip install boto3`") from e
    client = boto3.client("comprehend", region_name=region)

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        # Comprehend has 5kb (5000 char) limit per request; chunk & merge
        chunk_chars = 4500
        for offset in range(0, len(text), chunk_chars):
            chunk = text[offset:offset + chunk_chars]
            try:
                resp = client.detect_pii_entities(Text=chunk, LanguageCode=language)
            except Exception:  # noqa: BLE001
                continue
            for ent in resp.get("Entities", []):
                label = _AWS_COMPREHEND_TO_NULLPII.get(ent["Type"])
                if label is None:
                    continue
                spans.append(Span(
                    label, int(ent["BeginOffset"]) + offset, int(ent["EndOffset"]) + offset,
                ))
        return ToolResult(spans, (time.perf_counter() - t0) * 1000)

    return _predict


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
    "IP_ADDRESS": "account_number",
    "MAC_ADDRESS": "account_number",
    "AUTH_TOKEN": "secret",
    "AWS_CREDENTIALS": "secret",
    "ENCRYPTION_KEY": "secret",
    "GCP_API_KEY": "secret",
    "GCP_CREDENTIALS": "secret",
    "JSON_WEB_TOKEN": "secret",
    "PASSWORD": "secret",
}


def gcp_dlp_predictor(*, project: str | None = None) -> Predictor:
    """Google Cloud DLP `inspect_content` predictor. Requires
    `google-cloud-dlp` SDK + GCP credentials. Cost: ~$3 per 1M chars."""
    try:
        from google.cloud import dlp_v2  # noqa: I001
    except ImportError as e:
        raise ImportError("google-cloud-dlp required") from e
    client = dlp_v2.DlpServiceClient()
    project_id = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise ValueError("set GOOGLE_CLOUD_PROJECT or pass project=")
    parent = f"projects/{project_id}"
    info_types = [{"name": k} for k in _GCP_DLP_TO_NULLPII]
    inspect_config = {"info_types": info_types, "include_quote": True,
                      "min_likelihood": dlp_v2.Likelihood.POSSIBLE}

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        try:
            resp = client.inspect_content(
                request={"parent": parent, "inspect_config": inspect_config,
                         "item": {"value": text}},
            )
        except Exception:  # noqa: BLE001
            return ToolResult(spans, (time.perf_counter() - t0) * 1000)
        for f in resp.result.findings:
            label = _GCP_DLP_TO_NULLPII.get(f.info_type.name)
            if label is None:
                continue
            spans.append(Span(
                label, int(f.location.byte_range.start), int(f.location.byte_range.end),
            ))
        return ToolResult(spans, (time.perf_counter() - t0) * 1000)

    return _predict


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
    "IPAddress": "account_number",
    "Password": "secret",
}


def azure_pii_predictor(*, language: str = "en") -> Predictor:
    """Azure AI Language PII Recognition predictor. Requires
    AZURE_LANGUAGE_KEY + AZURE_LANGUAGE_ENDPOINT env vars."""
    try:
        from azure.ai.textanalytics import TextAnalyticsClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError as e:
        raise ImportError("azure-ai-textanalytics required") from e
    key = os.environ.get("AZURE_LANGUAGE_KEY")
    endpoint = os.environ.get("AZURE_LANGUAGE_ENDPOINT")
    if not key or not endpoint:
        raise ValueError("set AZURE_LANGUAGE_KEY + AZURE_LANGUAGE_ENDPOINT")
    client = TextAnalyticsClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        try:
            resp = client.recognize_pii_entities([text], language=language)
        except Exception:  # noqa: BLE001
            return ToolResult(spans, (time.perf_counter() - t0) * 1000)
        for doc in resp:
            if doc.is_error:
                continue
            for ent in doc.entities:
                label = _AZURE_PII_TO_NULLPII.get(ent.category)
                if label is None:
                    continue
                spans.append(Span(label, int(ent.offset), int(ent.offset) + int(ent.length)))
        return ToolResult(spans, (time.perf_counter() - t0) * 1000)

    return _predict


# ─── TAB (Text Anonymization Benchmark) loader stub ────────────────
# TAB = ECHR court rulings annotated for legal PII (ACL 2022).
# Public dataset, third-party gold standard. Loader stub — actual data
# location to be confirmed (HF: pieldolce/TAB or similar). Filling in
# requires download + label-schema mapping ECHR → nullpii 8 categories.
def _load_tab_stub(_n: int | None) -> list:
    raise NotImplementedError(
        "TAB loader stub — locate ECHR-PII dataset on HF + map labels "
        "(PERSON/CODE/LOC/DATETIME/QUANTITY/MISC) → nullpii 8 categories. "
        "See COMPETITIVE_ANALYSIS.md → Roadmap — bench completeness.",
    )


def has_artifacts() -> bool:
    return DEFAULT_MODEL_DIR.is_dir() and (DEFAULT_MODEL_DIR / "tokenizer.json").is_file()


def has_nullpii_built() -> bool:
    return (REPO_ROOT / "dist" / "index.js").is_file()


def hf_token() -> str | None:
    return os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")
