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
import sys
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
    # ─── DB / message-bus connection strings (failure_analysis.py) ─
    # `postgres://user:pass@host:5432/db`, `mongodb://`, etc. Consistently
    # missed by the ML detector on dev-paste prompts; high-confidence
    # secret because the URI carries credentials inline.
    ("secret", r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|rabbitmq|kafka|clickhouse|cassandra)://[^\s/@]+:[^@\s]+@[^\s/]+(?:/[^\s]*)?"),
    # ─── AWS ────────────────────────────────────────────────────────
    # All access-token prefixes (A3T*, AKIA, ASIA, ABIA, ACCA)
    ("secret", r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b"),
    # AWS Bedrock long-lived
    ("secret", r"\bABSK[A-Za-z0-9+/]{109,269}={0,2}"),
    # AWS resource ARN — high-info, distinctive prefix.
    ("secret", r"\barn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[\w/.:-]+"),
    # ─── GitHub ─────────────────────────────────────────────────────
    ("secret", r"\bghp_[A-Za-z0-9]{36,}\b"),
    ("secret", r"\bghs_[A-Za-z0-9]{36,}\b"),
    ("secret", r"\bgho_[A-Za-z0-9]{36,}\b"),
    ("secret", r"\bghu_[A-Za-z0-9]{36,}\b"),
    ("secret", r"\bghr_[A-Za-z0-9]{36,}\b"),
    ("secret", r"\bgithub_pat_[A-Za-z0-9_]{82,}\b"),
    # ─── OpenAI / Anthropic ─────────────────────────────────────────
    ("secret", r"\bsk-[A-Za-z0-9]{32,}\b"),
    ("secret", r"\bsk-ant-[A-Za-z0-9_-]{50,}\b"),
    ("secret", r"\bsk-ant-admin01-[a-zA-Z0-9_\-]{93}AA\b"),
    ("secret", r"\bsk-ant-api03-[a-zA-Z0-9_\-]{93}AA\b"),
    # ─── Stripe ─────────────────────────────────────────────────────
    ("secret", r"\bsk_(?:live|test)_[A-Za-z0-9]{24,}\b"),
    # ─── 1Password / Adobe / Age / Airtable / Alibaba ──────────────
    ("secret", r"\bA3-[A-Z0-9]{6}-(?:[A-Z0-9]{11}|[A-Z0-9]{6}-[A-Z0-9]{5})-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}\b"),
    ("secret", r"\bops_eyJ[a-zA-Z0-9+/]{250,}={0,3}"),
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
    ("secret", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    ("secret", r"\bxoxe\.xoxp-[0-9]+-[A-Za-z0-9]+\b"),
    # ─── GitLab / SendGrid / Twilio / NPM / PyPI / HF / GitLab ──
    ("secret", r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    ("secret", r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b"),
    ("secret", r"\bAC[a-f0-9]{32}\b"),
    ("secret", r"\bSK[a-f0-9]{32}\b"),
    ("secret", r"\bnpm_[A-Za-z0-9]{36,}\b"),
    ("secret", r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,}\b"),
    ("secret", r"\bhf_[A-Za-z0-9]{34,}\b"),
    ("secret", r"\b[a-f0-9]{32}-us[0-9]{1,2}\b"),  # Mailchimp
    ("secret", r"\bsecret_[A-Za-z0-9]{43}\b"),  # Notion
    ("secret", r"\blin_api_[A-Za-z0-9]{40,}\b"),
    # ─── PEM private keys / JWT ─────────────────────────────────────
    ("secret", r"-----BEGIN (?:RSA|DSA|EC|OPENSSH|PGP) PRIVATE KEY-----"),
    ("secret", r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    # ─── Account-number patterns ────────────────────────────────────
    # IBAN (rough — IT, GB, DE, FR, ES)
    ("account_number", r"\b[A-Z]{2}\d{2}[A-Z0-9]{1,4}(?:[ \t]?\d{4}){2,5}(?:[ \t]?\d{1,4})?\b"),
    # SSN US
    ("account_number", r"\b\d{3}-\d{2}-\d{4}\b"),
    # Italian Codice Fiscale (16-char structured)
    ("account_number", r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b"),
    # Bitcoin Legacy P2PKH (starts with 1, base58, 25-34 chars)
    ("account_number", r"\b1[A-HJ-NP-Za-km-z1-9]{25,34}\b"),
    # Bitcoin P2SH (starts with 3, base58)
    ("account_number", r"\b3[A-HJ-NP-Za-km-z1-9]{25,34}\b"),
    # Bitcoin Bech32 (segwit, bc1...)
    ("account_number", r"\bbc1[a-z0-9]{39,59}\b"),
    # Ethereum address (0x prefix + 40 hex)
    ("account_number", r"\b0x[a-fA-F0-9]{40}\b"),
    # UUID v4 (often used as account/customer id)
    ("account_number", r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"),
    # MAC address (hardware identifier)
    ("account_number", r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b"),
    # ─── Additional secret patterns (non-hacky, distinct prefix) ───
    # Google API key
    ("secret", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    # Discord webhook URL
    ("secret", r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+"),
    # Discord bot token
    ("secret", r"\b[MN][A-Za-z\d]{23}\.[\w-]{6}\.[\w-]{27,}\b"),
    # Telegram bot token (8-10 digit id : 35-char secret)
    ("secret", r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),
    # Mailgun API key
    ("secret", r"\bkey-[a-f0-9]{32}\b"),
    # Mapbox token
    ("secret", r"\bpk\.eyJ1Ijoi[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    # Square access token
    ("secret", r"\bEAA[A-Za-z0-9_\-]{200,}\b"),
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
    # ─── Phone — international format anchored on `+` ──────────────
    # `+CC NNN NNN NNNN` / `+CC-NNN-NNN-NNNN` / `+CC NNNNNNNNNN` etc.
    # Anchored on the leading `+` to avoid matching version strings,
    # IDs, etc. that have similar digit groupings.
    ("private_phone", r"\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{3,8}"),
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

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        spans: list[Span] = []
        for label, regex in compiled:
            for m in regex.finditer(text):
                if label == "private_url" and _is_public(m.group()):
                    continue
                spans.append(Span(label, m.start(), m.end()))
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(spans, elapsed)

    return _predict


# Backwards-compat alias — `EXTENDED_REGEX_PATTERNS` was the merged
# default+gitleaks pack while we A/B'd the two. After the merge it's
# identical to `DEFAULT_REGEX_PATTERNS`. Kept to avoid breaking the
# bench harness that imported it; new code should use
# `DEFAULT_REGEX_PATTERNS` directly.
EXTENDED_REGEX_PATTERNS: list[tuple[str, str]] = DEFAULT_REGEX_PATTERNS


def multi_ensemble_predictor(
    *,
    predictors: list[Predictor],
    strategy: str = "primary",
) -> Predictor:
    """Generic N-way ensemble. Two strategies (others tested and dropped
    in iter loop — see CLEANUP_TODO.md):

    - **primary**: predictors[0] wins, others fill non-overlapping gaps.
      Production default; +0.046 F1 vs primary alone in 11-dataset bench.
    - **union**: all spans, longest-wins on overlap. Higher recall, more
      false positives. Lost vs primary by -0.026 in iter-15.
    """
    if strategy not in {"union", "primary"}:
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

    merger = {"union": _merge_union, "primary": _merge_primary}[strategy]

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        results = [pred(text) for pred in predictors]
        spans_per_tool = [list(r.spans) for r in results]
        merged = merger(spans_per_tool)
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


def gliner_v2_predictor(
    model_path: str,
    *,
    onnx_file: str | None = None,
    device: str = "cuda",
    threshold: float = 0.5,
    chunk_chars: int = 1400,
    overlap_chars: int = 200,
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

    kwargs: dict = {"local_files_only": True}
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
        if len(text) <= chunk_chars:
            for e in model.predict_entities(text, _NULLPII_8, threshold=threshold):
                spans.append(Span(e["label"], int(e["start"]), int(e["end"])))
        else:
            stride = chunk_chars - overlap_chars
            for offset in range(0, len(text), stride):
                chunk = text[offset : offset + chunk_chars]
                if not chunk:
                    break
                for e in model.predict_entities(chunk, _NULLPII_8, threshold=threshold):
                    spans.append(
                        Span(e["label"], int(e["start"]) + offset, int(e["end"]) + offset),
                    )
                if offset + chunk_chars >= len(text):
                    break
            spans = _dedupe(spans)
        elapsed = (time.perf_counter() - t0) * 1000
        return ToolResult(spans, elapsed)

    return _predict


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


def has_artifacts() -> bool:
    return DEFAULT_MODEL_DIR.is_dir() and (DEFAULT_MODEL_DIR / "tokenizer.json").is_file()


def has_nullpii_built() -> bool:
    return (REPO_ROOT / "dist" / "index.js").is_file()


def hf_token() -> str | None:
    return os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")
