"""v10 domain router for nullpii.

Lexical heuristic that classifies an input text into one of:
  - "devops"    — code, secrets, env vars, JSON/YAML configs
  - "legal"     — court rulings, citations, statutes
  - "medical"   — clinical narratives, MRN, ICD-10, drug names
  - "narrative" — prose, ≥40 chars, no domain signals
  - "unknown"   — short / ambiguous inputs (default fallback)

Routing decisions are calibrated against the v10 bench matrix
(see `docs/v10/V10_JOURNAL.md` 2026-05-04). Selected per-domain
specialists:

  devops    → v10-devops    (best v10 on nullpii-bench: 0.729)
  legal     → v10-legal     (0.922 on tab-echr — biggest LoRA win)
  medical   → v10-medical   (0.611 on ai4privacy-300k)
  narrative → v10-general   (0.85 on isotonic-{en,de,fr})
  unknown   → v10-general   (0.756 average, safest fallback)

The router is intentionally signal-precision-first: order matters.
Devops signals (high-precision: regex matches on secret patterns)
are checked first — a fenced code block with `sk_live_…` should
NEVER route to legal, even if surrounding prose mentions "Court".
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Callable


# Router-only text normalization. Applied to the routing-decision
# input only — the adapter sees the raw text, so span offsets are
# unaffected. The purpose is to make obfuscated/perturbed inputs
# look closer to training-distribution to the router classifier
# (unicode-style fonts, fullwidth chars, zero-width tricks). This is
# transparent preprocessing, not a span-offset hack: routing changes
# but detection still operates on the original bytes.
_ZERO_WIDTH_RE = re.compile(r"[​-‍﻿⁠­]")
_MULTI_WS_RE = re.compile(r"\s+")


def normalize_for_routing(text: str) -> str:
    """NFKC + zero-width strip + apostrophe fold + whitespace collapse.

    Used by routing detectors to recover an unobfuscated form before
    embedding/classification. Adapter inference still sees the
    original `text`. See `EmbeddingDomainRouter.__call__`.

    AUDIT F17: NFKC does NOT fold typographic apostrophes (`’` U+2019)
    to ASCII; modern French copy uses U+2019 throughout, so router
    patterns like `Cour d'appel` would miss `Cour d’appel`. Translate
    typographic single quotes to ASCII before pattern matching.
    """
    t = unicodedata.normalize("NFKC", text)
    t = t.translate({0x2018: 0x27, 0x2019: 0x27, 0x201B: 0x27})
    t = _ZERO_WIDTH_RE.sub("", t)
    t = _MULTI_WS_RE.sub(" ", t).strip()
    return t

# ─── high-precision devops/secret signals ─────────────────────────
# These are deliberately tight — false-positive routing to devops
# is fine (devops adapter has DEFAULT_REGEX_PATTERNS regex pack as
# its primary predictor in the ensemble), but false-negative on a
# legal doc that happens to mention "AWS" would route narrative to
# legal which loses dev-paste capability.
_SECRET_PATTERNS = re.compile(
    r"\b(sk_live_|sk_test_|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|"
    r"xox[baprs]-[A-Za-z0-9-]+|AIza[0-9A-Za-z_-]{35}|"
    r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)",
)
# AUDIT F15: was uppercase-only with `=` separator. Now also matches:
# - lowercase `api_key=` / `auth_token=` (common in YAML/JSON dumps)
# - `KEY:` colon separator (YAML/INI)
# Captures the value through end-of-line so the count helper can drop
# matches whose VALUE looks like a date/email (those are PII fields,
# not secrets — see _count_env_var_dump below).
_ENV_VAR = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]{2,})\s*[:=]\s*(\S[^\n]*)$",
    re.MULTILINE,
)
_ENV_VAR_VALUE_LOOKS_LIKE_PII = re.compile(
    r"^("
    r"\d{4}-\d{2}-\d{2}"          # ISO date
    r"|\d{1,2}/\d{1,2}/\d{2,4}"   # slash date
    r"|[A-Za-z0-9._%+-]+@"         # email
    r"|\+?\d{1,3}[\s\-.]?\d{3,}"   # phone
    r")",
)


def _count_env_var_dump(text: str) -> int:
    """Count `KEY=value` / `KEY: value` lines whose VALUE does NOT look
    like a date/email/phone (those are PII payloads, not config dumps).
    """
    out = 0
    for m in _ENV_VAR.finditer(text):
        value = m.group(2).strip().strip("\"'")
        if _ENV_VAR_VALUE_LOOKS_LIKE_PII.match(value):
            continue
        out += 1
    return out
_CODE_FENCE = re.compile(r"```|`[^`\n]+`")
_JSON_OBJECT = re.compile(r'\{\s*"[A-Za-z_][\w]*"\s*:')
_PYTHON_KEYWORD = re.compile(
    r"^\s*(def |class |import |from \S+ import|return |if __name__)",
    re.MULTILINE,
)
_JS_KEYWORD = re.compile(
    r"\b(const |let |var |function |async function|=>|require\(|import .+ from )",
)

# ─── legal signals ───────────────────────────────────────────────
# Lexical hits aimed at TAB ECHR / EDGAR-redacted / UN court vocab.
# Multilingual: en + es + fr core terms.
_LEGAL_TERMS = re.compile(
    r"\b("
    # English
    r"the Court|Court (of|held|finds|considers)|"
    r"Article\s+\d+|article\s+\d+\s+(of|de|du)|"
    r"plaintiff|defendant|appellant|respondent|"
    r"v\.|vs\.|versus\s|"
    r"paragraph\s+\d+|§\s*\d+|"
    r"Convention(?:\s+on)?|Protocol\s+No\.?\s*\d+|"
    r"(?:District|Supreme|Federal|Constitutional)\s+Court|"
    r"Honourable|honorable|"
    r"hereby (orders|finds|declares|rules)|"
    r"in accordance with|pursuant to|"
    # Spanish
    r"juzgado|tribunal\s+(supremo|constitucional)|"
    r"demandante|demandado|"
    # French (ASCII; `normalize_for_routing` maps `’` → `'`)
    r"Cour\s+(d'appel|de cassation|européenne)|"
    # AUDIT F14: German legal vocabulary
    r"der Gerichtshof|das Gericht|Artikel\s+\d+|"
    r"Beschwerdef[üu]hrer|Antragsteller|Beklagte|"
    r"Konvention|Urteil|Absatz\s+\d+|"
    # Italian legal vocabulary (was missing)
    r"la Corte|il Tribunale|Articolo\s+\d+|"
    r"Imputato|Ricorrente|sentenza|paragrafo\s+\d+|"
    r"Grande Camera"
    r")\b",
)

# ─── medical signals ──────────────────────────────────────────────
# Targets MEDDOCAN-style Spanish + en clinical narrative + dosage
# patterns. Keep narrow — "patient" alone is too weak (false-positive
# legal docs mentioning "the patient witness").
_MEDICAL_TERMS = re.compile(
    r"\b("
    # English
    r"diagnos(is|tic|is of|tic of)|"
    r"prescri(b|p)tion|prescribed\s+(medic|drug|antib)|"
    r"medical\s+(history|record|center|hospital)|"
    r"clinical\s+(notes?|examination|presentation)|"
    r"ICD-?10|MRN[:#]?\s*\d+|NHC\s*\d+|"
    r"mg/ml|mg/kg|\d+\s*mg\s+(?:per|every|q[hd])|"
    # English + Spanish (paziente added — see Italian below)
    r"(?:patient|paciente|paziente)\s+"
    r"(?:was|presented|admitted|came|with|fue|present[óo]|"
    r"presenta(?:va|to)?|ammesso|con)|"
    # Hospital / clinic (en/es/it)
    r"(?:hospital|clinic|hospital de|clínica|centro\s+de\s+salud|"
    r"centro de salud|ospedale|clinica)\s+[A-Z]|"
    # Spanish clinical terms
    r"dolor\s+(?:abdominal|torácico|de cabeza)|"
    r"tratamiento\s+con|antecedentes\s+(?:personales|familiares)|"
    r"informe\s+(?:clínico|médico)|episodio\s+clínico|"
    # AUDIT F16: Italian medical vocabulary (was missing entirely)
    r"diagnosi|prescrizione|anamnesi|referto|"
    r"dolore\s+(?:addominale|toracico|alla\s+testa)"
    r")\b",
    re.IGNORECASE,
)

# ─── helpers ──────────────────────────────────────────────────────


def _has_devops_signal(text: str) -> bool:
    if _SECRET_PATTERNS.search(text):
        return True
    if _CODE_FENCE.search(text):
        return True
    # Multiple env-var lines = strong devops signal. AUDIT F15:
    # `_count_env_var_dump` skips lines whose value is a date/email/
    # phone — those are PII fields, not config dumps (e.g. a YAML
    # block listing personal records would otherwise mis-route to
    # devops).
    if _count_env_var_dump(text) >= 2:
        return True
    if _JSON_OBJECT.search(text):
        return True
    if _PYTHON_KEYWORD.search(text):
        return True
    if _JS_KEYWORD.search(text):
        return True
    return False


def _has_legal_signal(text: str) -> bool:
    matches = _LEGAL_TERMS.findall(text)
    return len(matches) >= 2  # require ≥2 hits to gate routing


def _has_medical_signal(text: str) -> bool:
    matches = _MEDICAL_TERMS.findall(text)
    return len(matches) >= 1


def _is_narrative(text: str) -> bool:
    """Long-enough prose with sentence punctuation."""
    if len(text) < 40:
        return False
    # At least one sentence-end and a space → text-shaped, not key-value.
    return bool(re.search(r"[.!?]\s+\S", text))


# ─── public API ───────────────────────────────────────────────────


def detect_domain(text: str) -> str:
    """Return the routing key for `text`.

    Decision order is precision-first:

        devops > legal > medical > narrative > unknown

    A devops signal trumps legal/medical because a code block with
    embedded secrets must route to the devops adapter regardless of
    surrounding prose. A legal signal trumps medical because TAB ECHR
    chunks occasionally name medical conditions (the v10-legal adapter
    handled those well at 0.922 F1).
    """
    if _has_devops_signal(text):
        return "devops"
    if _has_legal_signal(text):
        return "legal"
    if _has_medical_signal(text):
        return "medical"
    if _is_narrative(text):
        return "narrative"
    return "unknown"


def routing_summary(text: str) -> dict:
    """Diagnostic dump for tuning. Not used in hot path."""
    return {
        "domain": detect_domain(text),
        "len": len(text),
        "secret": bool(_SECRET_PATTERNS.search(text)),
        "code_fence": bool(_CODE_FENCE.search(text)),
        "env_vars": len(_ENV_VAR.findall(text)),
        "json_obj": bool(_JSON_OBJECT.search(text)),
        "py_kw": bool(_PYTHON_KEYWORD.search(text)),
        "js_kw": bool(_JS_KEYWORD.search(text)),
        "legal_hits": len(_LEGAL_TERMS.findall(text)),
        "medical_hits": len(_MEDICAL_TERMS.findall(text)),
        "narrative": _is_narrative(text),
    }


# ─── ML / hybrid router ───────────────────────────────────────────


_DEFAULT_ROUTER_PATH = (
    Path(__file__).resolve().parents[2] / "results" / "train" / "v10" / "router" / "router.joblib"
)

# Empirical-best-adapter labeling (router-v2). Same architecture as
# v1, but training labels reflect which adapter actually wins on each
# corpus origin (e.g. ai4 → legal, dev-paste → devops) rather than
# the corpus-assignment label v1 used.
_ROUTER_V2_PATH = (
    Path(__file__).resolve().parents[2] / "results" / "train" / "v10" / "router" / "router-v2.joblib"
)


def _has_high_precision_signal(text: str) -> str | None:
    """First stage of the hybrid router. Returns a domain label only
    when a high-precision regex signal fires; `None` otherwise (ML
    fallback handles those).

    AUDIT F13: when a legal/medical doc embeds a single secret (e.g. a
    judgment that quotes a leaked credential as evidence), preserve
    the domain routing — the regex pack still catches the secret
    regardless of which adapter handles span detection. Without this
    guard, one embedded secret rerouted a 4 KB ECHR judgment to v10-
    devops, dropping the legal adapter (0.922 → ~0.10 F1).
    """
    has_secret = bool(_SECRET_PATTERNS.search(text))
    legal_hits = len(_LEGAL_TERMS.findall(text))
    medical_hits = len(_MEDICAL_TERMS.findall(text))
    # Strong domain signal overrides single-secret reroute.
    if has_secret and (legal_hits >= 4 or medical_hits >= 4):
        return "legal" if legal_hits >= medical_hits else "medical"
    if has_secret:
        return "devops"
    if _CODE_FENCE.search(text):
        return "devops"
    # AUDIT F15: see `_count_env_var_dump` for the PII-value filter.
    if _count_env_var_dump(text) >= 2:
        return "devops"
    if _PYTHON_KEYWORD.search(text):
        return "devops"
    if _JS_KEYWORD.search(text):
        return "devops"
    if legal_hits >= 2:
        return "legal"
    if medical_hits >= 1:
        return "medical"
    return None


class HybridDomainRouter:
    """Two-stage router: regex stage 1 + sklearn stage 2.

    Stage 1 (`_has_high_precision_signal`) handles unambiguous text
    (secrets, code, court vocabulary, clinical vocabulary). Returns
    a confident domain label — no ML needed.

    Stage 2 (`self._classifier.predict`) handles ambiguous prose:
    short snippets, contact-info fragments, narrative without
    domain markers. The classifier returns one of the four trained
    labels {`devops`, `legal`, `medical`, `narrative`}; if its
    `predict_proba` max is below `min_confidence`, falls back to
    `narrative` (safe default — narrative records map to v10-general
    in the routing table, which is the best-on-average single
    adapter).
    """

    def __init__(
        self,
        classifier_path: str | Path = _DEFAULT_ROUTER_PATH,
        *,
        min_confidence: float = 0.40,
    ) -> None:
        try:
            import joblib
        except ImportError as e:
            raise ImportError(
                "joblib required for HybridDomainRouter; "
                "run `pip install joblib scikit-learn`",
            ) from e
        path = Path(classifier_path)
        if not path.exists():
            raise FileNotFoundError(
                f"router classifier not found at {path}. "
                f"Train it first: "
                f"`python packages/eval/scripts/train/train_router.py`",
            )
        self._classifier = joblib.load(path)
        self._classes = list(self._classifier.classes_)
        self._min_confidence = min_confidence

    def __call__(self, text: str) -> str:
        # AUDIT F17: normalise BEFORE both stages so typographic
        # apostrophes / fullwidth digits / zero-width chars don't
        # defeat pattern anchors.
        normalized = normalize_for_routing(text)
        # Stage 1 — high-precision regex
        signal = _has_high_precision_signal(normalized)
        if signal is not None:
            return signal
        # Stage 2 — sklearn classifier
        try:
            proba = self._classifier.predict_proba([normalized])[0]
        except (ValueError, AttributeError):
            return "narrative"
        idx = int(proba.argmax())
        if proba[idx] < self._min_confidence:
            return "narrative"
        return self._classes[idx]


def make_hybrid_detector(
    classifier_path: str | Path = _DEFAULT_ROUTER_PATH,
    min_confidence: float = 0.40,
) -> Callable[[str], str]:
    """Construct and return a hybrid detector callable. Convenience
    factory for `domain_routed_predictor` callers."""
    router = HybridDomainRouter(classifier_path, min_confidence=min_confidence)
    return router


def make_hybrid_detector_v2(
    min_confidence: float = 0.40,
) -> Callable[[str], str]:
    """Hybrid detector using the v2 classifier (empirical-best-adapter
    labeling). See `train_router_v2.py` for the relabeling logic."""
    return HybridDomainRouter(_ROUTER_V2_PATH, min_confidence=min_confidence)


# ─── multilingual embedding router ───────────────────────────────


_EMBEDDING_PROTOTYPES_PATH = (
    Path(__file__).resolve().parents[2]
    / "results" / "train" / "v10" / "router" / "router-embeddings.npz"
)


class EmbeddingDomainRouter:
    """Multilingual embedding-based router. Replaces the regex+TF-IDF
    pair with a single sentence embedder + per-domain prototypes.

    At init: loads `intfloat/multilingual-e5-small` (118 MB, 94
    languages) plus 4 prototype vectors (mean of domain training
    embeddings, see `build_router_embeddings.py`).

    At inference: embed the query, cosine-similarity against each
    prototype, route to argmax. If the max similarity is below
    `min_similarity`, fall back to `narrative` (safe default — broad
    coverage).

    Tradeoffs vs `HybridDomainRouter`:
    - PRO: no hand-curated regex wordlist; works on Italian, Chinese,
      Japanese, etc. without adding patterns.
    - PRO: single artifact (the embedder + prototypes), no two-stage
      pipeline.
    - CON: ~50ms / sample on CPU (~5ms on MPS) vs ~µs for regex.
    - CON: 118 MB extra artifact (one-time cost; cached on disk after
      first download from HuggingFace).
    """

    def __init__(
        self,
        prototypes_path: str | Path = _EMBEDDING_PROTOTYPES_PATH,
        *,
        min_similarity: float = 0.0,
        device: str = "cpu",
        gated_routes: dict[str, float] | None = None,
    ) -> None:
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "sentence-transformers + numpy required for EmbeddingDomainRouter; "
                "run `pip install sentence-transformers`",
            ) from e
        path = Path(prototypes_path)
        if not path.exists():
            raise FileNotFoundError(
                f"router prototypes not found at {path}. "
                f"Build first: "
                f"`python packages/eval/scripts/train/build_router_embeddings.py`",
            )
        data = np.load(path, allow_pickle=False)
        self._labels: list[str] = list(data["labels"])
        self._prototypes = data["prototypes"]  # (N_domains, dim) float32
        embedder_name = str(data["embedder"])
        # Some legacy npz files don't have a `prefix` key — default to
        # the e5-style "passage: " prefix.
        try:
            self._prefix = str(data["prefix"])
        except KeyError:
            self._prefix = "passage: "
        self._embedder = SentenceTransformer(embedder_name, device=device)
        self._embedder.max_seq_length = 256
        self._min_similarity = min_similarity
        self._np = np
        # Per-route minimum cosine margin over second-best. Used to
        # gate routes that have a tendency to over-attract samples
        # (e.g. `enterprise` prototype overlaps with dev-paste; without
        # gating, 15% of nullpii-bench would falsely route to
        # enterprise — empirically observed). Keys are route labels;
        # values are minimum (cosine_top - cosine_2nd) margin to keep
        # the prediction. Below threshold, fall back to second-best.
        self._gated_routes = gated_routes or {}

    def __call__(self, text: str) -> str:
        # Embed query with same prefix used at prototype-build time.
        # Normalize the routing input only — the adapter still sees
        # the original `text` via the routes dict.
        normalized = normalize_for_routing(text)
        emb = self._embedder.encode(
            [f"{self._prefix}{normalized}"],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        sims = self._prototypes @ emb  # (N_domains,) cosine since both unit-norm
        sims_arr = self._np.asarray(sims)
        idx = int(self._np.argmax(sims_arr))
        if float(sims_arr[idx]) < self._min_similarity:
            return "narrative"
        top_label = self._labels[idx]
        # Apply margin gate if this label is in `gated_routes`.
        gate = self._gated_routes.get(top_label)
        if gate is not None:
            second_best_idx = int(
                self._np.argmax(self._np.delete(sims_arr, idx))
            )
            second_best_score = float(
                self._np.delete(sims_arr, idx)[second_best_idx]
            )
            margin = float(sims_arr[idx]) - second_best_score
            if margin < gate:
                # Reroute to the second-best label.
                full_idx = (
                    second_best_idx
                    if second_best_idx < idx
                    else second_best_idx + 1
                )
                return self._labels[full_idx]
        return top_label


def make_embedding_detector(
    min_similarity: float = 0.0,
    device: str = "cpu",
    gated_routes: dict[str, float] | None = None,
) -> Callable[[str], str]:
    """Convenience factory for `domain_routed_predictor` callers.

    `gated_routes` defaults to a 0.05 margin gate on `enterprise` —
    enterprise prototype overlaps with dev-paste shapes; without this
    gate ~15% of nullpii-bench falsely routes to enterprise (down to
    ~3% with the gate, while still keeping ~80% of nemotron-pii-test
    routed correctly).
    """
    if gated_routes is None:
        # AUDIT_A: empirical sweep on nullpii-bench / nemotron-pii-test:
        # - 0.05 → 5 enterprise + 1 legal misroute on nullpii-bench
        #   (-0.11 F1) but ~56% nemotron correctly routed
        # - 0.10 → 0 misroutes on nullpii-bench, ~31% nemotron correct
        # 0.10 chosen to preserve dev-paste F1; nemotron lift via the
        # `nullpii-v10-router-embedding-expanded` variant (option B —
        # inference-time finer-grained prompts, no enterprise routing).
        gated_routes = {"enterprise": 0.10}
    return EmbeddingDomainRouter(
        min_similarity=min_similarity,
        device=device,
        gated_routes=gated_routes,
    )


__all__ = [
    "EmbeddingDomainRouter",
    "HybridDomainRouter",
    "detect_domain",
    "make_embedding_detector",
    "make_hybrid_detector",
    "make_hybrid_detector_v2",
    "routing_summary",
]
