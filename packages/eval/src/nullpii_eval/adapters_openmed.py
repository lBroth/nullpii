# SPDX-License-Identifier: Apache-2.0
"""OpenMed's PII checkpoints run through OpenMed's own product call,
`openmed.deidentify`, the way the `openmed` package ships it.

"As shipped" means `openmed[hf]==3.0.0` (PyPI, Apache-2.0) with nothing
added, removed or re-tuned: every text goes through one
`deidentify(text, method="mask", model_name=<checkpoint>, ...)` call and the
returned `DeidentificationResult.pii_entities` are scored. That call is the
package's end-to-end product (the analogue of nullpii's `sanitize()`), so
the row measures everything the package wraps around the checkpoint:

1. `text.strip()`, then stage-1 normalisation: whitespace runs collapsed to
   one space and NFC per grapheme, with an offset map
   (core/pipeline.py:458, :1078);
2. `extract_pii`: Unicode defences (zero-width removal, confusable and
   digit folding) with an offset map (core/pii.py:661-734), pySBD sentence
   segmentation packed into chunks of at most 6 sentences / max(480, 4 x
   model_max_length) chars (openmed/__init__.py:580-705), the HF
   token-classification pipeline with `aggregation_strategy="simple"`
   (:412), splitting at line and sentence breaks (:278), the medical-token
   span remap (`use_medical_tokenizer`, a config default, :783-810), the
   score threshold and adjacent-entity grouping (`group_entities=True`,
   core/pii.py:1311; processing/outputs.py:152);
3. regex "smart merging": semantic units widen fragmented model spans and,
   because these checkpoints are not model-led, regex-only units are added
   at their pattern prior (core/pii.py:1040-1116, :1100;
   core/pii_entity_merger.py:818-1021);
4. clinical-term suppression of person-name / location / organisation
   spans that exactly match a bundled clinical vocabulary
   (core/clinical_protect.py:30, core/pii.py:1375-1381,
   core/pipeline.py:821);
5. the stage-9 structured-ID safety sweep, which adds validated SSN / card /
   IBAN / ... spans no kept span overlaps (core/pipeline.py:1543,
   core/safety_sweep.py:227);
6. offsets mapped back to the stripped input, snapped to grapheme
   boundaries, overlaps resolved (core/pipeline.py:919,
   core/pii.py:2174-2178); `PIIEntity.label` is the raw label
   (core/pii.py:2188), not the canonical one.

Sources (the 3.0.0 wheel, paths under `openmed/`): core/pii.py
(`deidentify` :2620, `extract_pii` :1393, `PIIEntity` :142,
`DeidentificationResult` :177), core/pipeline.py (`Pipeline.run` :389),
openmed/__init__.py (`analyze_text` :405), core/config.py (`OpenMedConfig`
:284), core/models.py (`ModelLoader.create_pipeline` :419),
core/model_integrity.py (`prepare_model_reference` :120), the bundled
registry `models.jsonl` (rows :1883 Large, :1886 Small).

Settings. Every `deidentify` argument keeps its default except these:

- `model_name`: the checkpoint under test (default: the Small one).
- `confidence_threshold`: 0.7 by default, the package's own default
  (core/pii.py:2624); a tuning grid passes other values.
- `config=OpenMedConfig(backend="hf", device=<device>)`: `backend=None`
  would auto-select MLX on Apple Silicon when `mlx` is importable
  (core/backends.py:329-334) and fall back to HF on failure
  (core/models.py:464-480); "hf" pins the PyTorch path everywhere and
  disables the fallback. `device` is the bench's device (MPS, CUDA or CPU,
  resolved by `adapters._resolve_torch_device`, which also caps CPU
  threads as for the other transformer rows). Every other config field
  keeps its default (medical-token remap and clinical protection on,
  `~/.cache/openmed` cache, attention "auto", no 4-bit).
- `loader=ModelLoader(config)`: one loader per predictor, warmed at build,
  so a timed call never loads weights (the package's documented way to
  reuse a warmed pipeline).
- Passed explicitly at their defaults, so a future default change cannot
  slip in: `method="mask"`, `use_smart_merging=True`,
  `use_safety_sweep=True`, `lang="en"`, `keep_mapping=False` (no
  re-identification mapping), `audit=False` (no audit report),
  `cache_results=False` (no in-process result cache).

Revision pin. The HF path has no revision option: `deidentify` forwards no
revision to `analyze_text` / `create_pipeline`, and `pii_model_revision` is
read by the ONNX backend only (core/backends.py:229). The package pins
registry models itself: `prepare_model_reference` downloads the snapshot at
the remote head only if its reproducibility hash (repo id, commit sha,
release date, file list) equals the registry's, then verifies every file
against the hashes it recorded (core/model_integrity.py:467-540). The
adapter checks that the snapshot directory the pipeline loaded is the
pinned commit and raises otherwise.

Determinism and isolation. Any `OPENMED_*` environment variable raises at
build: they change config defaults, the device, telemetry, model
verification or input limits (core/config.py:373-547). Telemetry is
therefore off (`OPENMED_TELEMETRY_ENABLED` unset, core/pipeline.py:380).
Third-party detector plugins (entry point `openmed.detectors`) raise at
build; the one built-in detector (India multi-ID) is gated off for "en".
`pysbd` must be importable (`analyze_text` silently drops sentence
chunking without it, openmed/__init__.py:589-592) and `ftfy` must not be
(`openmed[hf]` does not install it; with it stage 1 would also repair
encodings). Network: only the first build of a checkpoint downloads it;
predict calls reuse the cached pipeline and make no network call (checked
in the smoke test under openmed's own socket guard). Loading a verified
local snapshot makes openmed set HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE /
HF_DATASETS_OFFLINE process-wide (core/models.py:580-584,
core/offline.py); the adapter restores them after the build, because the
bench downloads its datasets after building tools. openmed's own offline
mode (`local_only`) stays off for the same reason.

Language. `lang` stays "en" for every sample and the predictor does not
declare `wants_language`. With `lang != "en"` the Small checkpoint, which is
the package's `_DEFAULT_EN_MODEL`, is silently swapped for that language's
own checkpoint (`_resolve_effective_pii_model`, core/pii.py:645-649; e.g. de
-> OpenMed-PII-German-SuperClinical-Small-44M-v1), so the row would no
longer measure this checkpoint. For the Large one it keeps the model and
adds that language's regex bank (6-9 date / phone / national-id / street /
postcode patterns). The docstring defines `lang` as selecting "model ...
regex patterns, and fake data", and the registry lists both checkpoints as
English-only, so the documented use of `lang` for a non-English text is the
language's own model: a different row. Sentence segmentation is English
either way (`extract_pii` never passes `sentence_language`).

Disclosures:

- `confidence_threshold` only gates the model's aggregated spans, before
  merging. Regex-only semantic units enter at their pattern prior whatever
  the threshold (e.g. `bic` 0.25, `npi` 0.15, x0.3 when the validator
  fails), and safety-sweep spans at theirs, so the default output carries
  some low-score regex spans; `label_cut` can remove them.
- `label_cut` filters the final entities by nullpii label and the entity's
  `confidence` (model score, merged blend 0.6 model + 0.4 pattern, or
  pattern prior), i.e. per-label thresholds applied after the whole
  pipeline. The package's own `calibration_thresholds_path` filters earlier:
  after smart merging and clinical protection but BEFORE the safety sweep
  (core/pipeline.py:724, :1418), keyed by OpenMed's canonical labels, so
  the sweep can re-add a structured ID it removed. `label_cut` is the exact
  post-filter; calibration is the closer of the two package knobs.
- `analyze_text` sets the tokenizer's `model_max_length` to 512 for both
  checkpoints (the cards fine-tuned at 384), and a chunk longer than that
  is truncated by the HF pipeline (no stride, transformers
  token_classification.py:248): the model never sees its tail, e.g. a name
  at the end of one ~900-token sentence is missed. The regex layers still
  scan all the text.
- `deidentify` refuses some inputs: `analyze_text` raises
  `InputValidationError` on an empty text (code `empty_text`) or "suspicious
  content" (`suspicious_content`: a character repeated more than 100 times,
  more than half the characters non-word non-space, or 10+ control
  characters; utils/validation.py:235-259). Such a text is scored as no
  spans, since the product returns no de-identified text for it; each
  refusal is logged (code and length only) and counted in
  `_predict.refusals`. Any other exception propagates.
- Offsets: the package reports offsets into `text.strip()` (its
  `original_text`); the adapter checks that frame and adds the stripped
  leading whitespace back. Each entity's text must equal its slice.
  Checked on leading / trailing whitespace, zero-width characters inside
  a name, a Cyrillic confusable inside an e-mail, an astral emoji and a ZWJ
  emoji sequence before the entities: every span lands on its surface.
- One openmed 3.0.0 offset defect is kept as shipped: when the stripped
  text starts with zero-width characters (or lone combining marks)
  followed by whitespace, every span coming out of `extract_pii` lands
  that many characters early (e.g. " Jan" for "Jane"), because the Unicode
  defences remove those characters, `analyze_text` strips the whitespace
  they exposed, and the remap assumes the unstripped frame
  (core/pii.py:767-807). Correcting it would score better than the
  product redacts; such texts are detected exactly (with the package's own
  `normalize_for_pii_detection`), logged and counted in `_predict.shifted`.
- On MPS the package sets PYTORCH_ENABLE_MPS_FALLBACK=1 and the MPS
  watermark ratios (torch/device.py, `setdefault`, process-wide).

Label map: same SYMMETRY RULE as `_RIZZO_LABEL_MAP` in `adapters.py`. A
label maps to X iff our gold loaders map the equivalent gold concept to X,
and to None, an explicit drop, where the gold ignores the concept. Model
labels (the 54 Nemotron-PII types, B-/I- stripped as
processing/outputs.py:186-190 does) and regex labels of the same name go
through `_NEMOTRON_TOKEN_LABEL_MAP`, shared with the Nemotron-trained rows;
`_OPENMED_PATTERN_LABEL_MAP` decides the labels only the regex layers emit.
"""
from __future__ import annotations

import functools
import importlib.util
import logging
import os
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from .adapters import (
    _NEMOTRON_TOKEN_LABEL_MAP,
    LabelCut,
    ToolResult,
    _check_label_coverage,
    _map_native_label,
    _resolve_torch_device,
)
from .datasets import Span

if TYPE_CHECKING:
    from openmed import ModelLoader, OpenMedConfig
    from openmed.core.pii import DeidentificationResult, PIIEntity
    from transformers import TokenClassificationPipeline

OPENMED_VERSION = "3.0.0"
OPENMED_SMALL_MODEL = "OpenMed/OpenMed-PII-SuperClinical-Small-44M-v1"
OPENMED_SMALL_REVISION = "a2360d3f42526fc660ac3b2b2301e1c2d94eba61"
OPENMED_LARGE_MODEL = "OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1"
OPENMED_LARGE_REVISION = "df7af994d39d358e52f929ff1b3a40d894adf022"

# `deidentify()`'s own default operating point (core/pii.py:2624).
DEFAULT_CONFIDENCE_THRESHOLD = 0.7

_METHOD = "mask"
_LANG = "en"
_BACKEND = "hf"
# What `analyze_text` asks the loader for (openmed/__init__.py:412, :533-549);
# the same arguments return the pipeline the warm-up cached.
_TASK = "token-classification"
_AGGREGATION = "simple"
_USE_FAST_TOKENIZER = True
_SNAPSHOTS_DIR = "snapshots"
_ENV_PREFIX = "OPENMED_"
_BIO_PREFIXES = ("B-", "I-")
_BIO_PREFIX_LEN = 2
_OUTSIDE_LABEL = "O"
_SENTENCE_DETECTION_KEY = "sentence_detection"
_REQUIRED_MODULE = "pysbd"
_FORBIDDEN_MODULE = "ftfy"
# `InputValidationError.code`s for inputs `deidentify` refuses to process.
_REFUSAL_CODES = frozenset({"empty_text", "suspicious_content"})
# Unicode categories openmed's detection normalisation can drop from the
# front of a text: format controls (zero-width chars) and lone marks.
_DROPPED_LEADING_CATEGORIES = frozenset({"Cf", "Mn", "Me"})
_SHIFTED_KEY = "shifted_offsets"
# Synthetic, no PII: a name, an e-mail and a date, so the warm-up runs the
# model, smart merging and the sweep once before the first timed call.
_WARMUP_TEXT = "Patient Jane Roe, jane.roe@example.com, was seen on 2024-03-05."
_MS_PER_S = 1000.0

_LOG = logging.getLogger(__name__)

# Labels only the package's regex layers emit: smart-merging units
# (`get_patterns_for_language("en")`, core/pii_i18n.py:13207; PII_PATTERNS
# incl. the africa_context entries, core/pii_entity_merger.py:204-575) and
# the safety sweep (PII_PATTERNS + AADHAAR, core/safety_sweep.py:75-79).
# Regex labels that share a model label's name (date, email, ssn, iban's
# sibling account_number, ...) are decided by `_NEMOTRON_TOKEN_LABEL_MAP`.
_OPENMED_PATTERN_LABEL_MAP: dict[str, str | None] = {
    "iban": "account_number",            # ai4privacy / isotonic IBAN
    "bic": "account_number",             # ai4privacy / isotonic BIC (model: swift_bic)
    "ACCOUNT_NUMBER": "account_number",  # mobile-money reference; ai4privacy ACCOUNTNUMBER
    "upi_id": "account_number",          # India payment handle of a bank account; ai4privacy ACCOUNTNUMBER
    "npi": "account_number",             # US provider registry id; gretel certificate_license_number
    "abha_number": "account_number",     # India health id; gretel health_plan_beneficiary_number
    "abha_address": "account_number",    # handle of the same health account, as abha_number
    "ration_card": "account_number",     # India id card number; ai4privacy IDCARDNUM
    # China USCC: an organisation's registration and tax id; ai4privacy
    # TAXNUM, as `adapters_presidio` maps the company AU_ABN / AU_ACN.
    "social_credit_code": "account_number",
    "passport_mrz": "private_passport",  # passport MRZ lines; ai4privacy PASSPORTNUM, privy US_PASSPORT
    # ─── Dropped: our gold has no such category ───────────────────
    "ORGANIZATION": None,                # facility names; `_NER_LABEL_MAP` ORG, isotonic COMPANYNAME
    "ETHNICITY": None,                   # as the model's race_ethnicity; mapa race_ethnicity
}


def _merged_label_map() -> dict[str, str | None]:
    """The Nemotron map plus the regex-only labels; a regex label must not
    re-decide a label the shared map already decides."""
    shared = sorted(set(_NEMOTRON_TOKEN_LABEL_MAP) & set(_OPENMED_PATTERN_LABEL_MAP))
    if shared:
        raise ValueError(f"[openmed] regex labels already decided by the Nemotron map: {shared}")
    return {**_NEMOTRON_TOKEN_LABEL_MAP, **_OPENMED_PATTERN_LABEL_MAP}


OPENMED_DEIDENTIFY_LABEL_MAP: dict[str, str | None] = _merged_label_map()


def _require_clean_environment(tool: str) -> None:
    """No operator override may reach the as-shipped configuration."""
    overrides = sorted(name for name in os.environ if name.startswith(_ENV_PREFIX))
    if overrides:
        raise RuntimeError(f"[{tool}] unset these environment overrides to run openmed as shipped: {overrides}")


def _require_pinned_install(tool: str) -> None:
    """The installed package is the pinned one, with the optional modules
    that change its output present or absent as `openmed[hf]` leaves them."""
    import openmed

    if openmed.__version__ != OPENMED_VERSION:
        raise RuntimeError(f"[{tool}] openmed {openmed.__version__} installed, {OPENMED_VERSION} pinned")
    if importlib.util.find_spec(_REQUIRED_MODULE) is None:
        raise RuntimeError(f"[{tool}] {_REQUIRED_MODULE} missing: analyze_text would skip sentence chunking")
    if importlib.util.find_spec(_FORBIDDEN_MODULE) is not None:
        raise RuntimeError(f"[{tool}] {_FORBIDDEN_MODULE} installed: openmed[hf] ships without encoding repair")


def _require_no_detector_plugins(tool: str) -> None:
    """Only the built-in India multi-ID detector may be registered, and it
    must stay gated off for English."""
    from openmed.core.custom_recognizer import abdm_mode_enabled
    from openmed.core.detector_plugins import DETECTOR_STAGES, INDIAN_MULTI_ID_DETECTOR, iter_detectors

    registered = {spec.name for stage in DETECTOR_STAGES for spec in iter_detectors(stage, _LANG)}
    plugins = sorted(registered - {INDIAN_MULTI_ID_DETECTOR})
    if plugins:
        raise RuntimeError(f"[{tool}] third-party openmed detector plugins registered: {plugins}")
    if abdm_mode_enabled(None, lang=_LANG, locale=None):
        raise RuntimeError(f"[{tool}] the India multi-ID detector is active for {_LANG!r}")


def _package_label(raw: str) -> str:
    """A model label as `format_predictions` emits it (outputs.py:186-190)."""
    return raw[_BIO_PREFIX_LEN:] if raw.startswith(_BIO_PREFIXES) else raw


def _emittable_labels(pipe: TokenClassificationPipeline) -> set[str]:
    """Every label `deidentify` can return for this checkpoint in English:
    the model's, smart merging's and the safety sweep's."""
    from openmed.core.pii_entity_merger import PII_PATTERNS
    from openmed.core.pii_i18n import AADHAAR_PII_PATTERNS, get_patterns_for_language

    model = {_package_label(str(raw)) for raw in pipe.model.config.id2label.values()} - {_OUTSIDE_LABEL}
    patterns = (*get_patterns_for_language(_LANG, include_indian_multi_id=True), *PII_PATTERNS, *AADHAAR_PII_PATTERNS)
    return model | {p.entity_type for p in patterns}


@contextmanager
def _hf_offline_env_restored() -> Iterator[None]:
    """Put back the HF offline variables openmed's loader sets process-wide
    when it loads a verified local snapshot (`enable_hf_offline_flags` via
    core/models.py:580-584); left set, they would turn the bench's later
    dataset downloads offline. Predict calls never set them again."""
    from openmed.core.offline import HF_OFFLINE_ENV_VARS

    saved = {name: os.environ.get(name) for name in HF_OFFLINE_ENV_VARS}
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _warm_up(call: Callable[[str], DeidentificationResult], tool: str) -> None:
    """Load the checkpoint and the package's lazy pieces before any timed
    call; the result must show that sentence chunking ran."""
    result = call(_WARMUP_TEXT)
    if (result.metadata or {}).get(_SENTENCE_DETECTION_KEY) is not True:
        raise RuntimeError(f"[{tool}] the warm-up ran without sentence detection")


def _cached_pipeline(loader: ModelLoader, model_id: str, tool: str) -> TokenClassificationPipeline:
    """The pipeline the warm-up created, fetched with `analyze_text`'s own
    arguments; a second pipeline appearing means the lookup missed."""
    from transformers import TokenClassificationPipeline

    before = loader.loaded_models()
    pipe = loader.create_pipeline(
        model_id, task=_TASK, aggregation_strategy=_AGGREGATION, use_fast_tokenizer=_USE_FAST_TOKENIZER,
    )
    after = loader.loaded_models()
    if after != before or after.get(model_id, {}).get("pipelines") != 1:
        raise RuntimeError(f"[{tool}] expected exactly the warm-up's pipeline, loader holds {after}")
    if not isinstance(pipe, TokenClassificationPipeline):
        raise RuntimeError(f"[{tool}] backend served {type(pipe).__name__}, not the HF pipeline")
    return pipe


def _check_loaded(pipe: TokenClassificationPipeline, revision: str, device: str, tool: str) -> None:
    """The weights and tokenizer come from the pinned commit's snapshot, on
    the requested device."""
    for part, name_or_path in (("model", pipe.model.name_or_path), ("tokenizer", pipe.tokenizer.name_or_path)):
        snapshot = Path(name_or_path)
        if snapshot.parent.name != _SNAPSHOTS_DIR or snapshot.name != revision:
            raise RuntimeError(f"[{tool}] {part} loaded from snapshot {snapshot.name!r}, pinned {revision!r}")
    if pipe.device.type != device.split(":")[0]:
        raise RuntimeError(f"[{tool}] pipeline on {pipe.device.type}, requested {device}")


def _deidentify_or_refusal(
    call: Callable[[str], DeidentificationResult], text: str, refusals: Counter, tool: str,
) -> DeidentificationResult | None:
    """`deidentify(text)`, or None when the package refuses the input (see
    the module docstring); every other exception propagates."""
    from openmed.utils.gateway import InputValidationError

    try:
        return call(text)
    except InputValidationError as exc:
        if exc.code not in _REFUSAL_CODES:
            raise
        refusals[exc.code] += 1
        _LOG.warning(
            "[%s] deidentify refused a text (code=%s, chars=%d), scored as no spans; refusals so far: %s",
            tool, exc.code, len(text), dict(refusals),
        )
        return None


def _shifted_by_package(body: str, config: OpenMedConfig) -> bool:
    """True when openmed 3.0.0 reports this text's offsets shifted: its
    Unicode defences drop the leading zero-width / combining characters,
    the inference text then starts with whitespace, `analyze_text` strips it
    again (utils/gateway.py:193) and the spans are remapped from the
    unstripped frame (core/pii.py:767-807), so they land that many
    characters early. The spans are kept as shipped; this only counts it."""
    if not body or unicodedata.category(body[0]) not in _DROPPED_LEADING_CATEGORIES:
        return False
    from openmed.core.script_detect import normalize_for_pii_detection

    inference = normalize_for_pii_detection(
        body, width_convention=config.cjk_width_convention, chinese_target_script=config.chinese_target_script,
    ).text
    return inference[:1].isspace()


def _count_shift(body: str, config: OpenMedConfig, shifted: Counter, tool: str) -> None:
    """Count and log (length only) a text whose offsets openmed shifted."""
    if not _shifted_by_package(body, config):
        return
    shifted[_SHIFTED_KEY] += 1
    _LOG.warning(
        "[%s] openmed shifted this text's offsets (leading zero-width char + whitespace, chars=%d); "
        "spans kept as shipped; texts so far: %d",
        tool, len(body), shifted[_SHIFTED_KEY],
    )


def _leading_offset(result: DeidentificationResult, text: str, tool: str) -> int:
    """Characters the package stripped off the front of `text`. Its offsets
    index `text.strip()` (core/pipeline.py:458); any other frame raises."""
    if result.original_text != text.strip():
        raise RuntimeError(f"[{tool}] deidentify's offsets do not index the stripped input")
    return len(text) - len(text.lstrip())


def _entity_bounds(entity: PIIEntity, body: str, lead: int, tool: str) -> tuple[int, int]:
    """`entity`'s offsets in the caller's text; they must cut a non-empty
    slice of the stripped text equal to the entity's own text."""
    start, end = entity.start, entity.end
    if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(body)):
        raise RuntimeError(f"[{tool}] entity offsets ({start}, {end}) outside a {len(body)}-char text")
    if body[start:end] != entity.text:
        raise RuntimeError(f"[{tool}] entity text does not match its offsets ({start}, {end})")
    return start + lead, end + lead


def _project(
    entities: Iterable[PIIEntity], body: str, lead: int, label_cut: LabelCut | None, tool: str,
) -> tuple[list[Span], list[float]]:
    """OpenMed entities -> nullpii spans on the caller's text and their
    scores, after the label map and the cut."""
    spans: list[Span] = []
    scores: list[float] = []
    for entity in entities:
        start, end = _entity_bounds(entity, body, lead, tool)
        label = _map_native_label(entity.label, OPENMED_DEIDENTIFY_LABEL_MAP, tool=tool)
        score = float(entity.confidence)
        if label is None or (label_cut is not None and not label_cut.keeps(label, score)):
            continue
        spans.append(Span(label, start, end))
        scores.append(score)
    return spans, scores


def openmed_deidentify_predictor(
    model_id: str,
    revision: str,
    *,
    tool: str,
    device: str | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    label_cut: LabelCut | None = None,
) -> Callable[[str], ToolResult]:
    """`model_id` at `revision` behind `openmed.deidentify` (see the module
    docstring for the call, its settings and the disclosures).

    `confidence_threshold` goes to `deidentify`; `label_cut` then filters
    the mapped spans by the entity's confidence. The returned
    `_predict(text)` times the `deidentify` call plus the mapping; the model
    is loaded, checked against the pin and warmed here. `_predict.refusals`
    counts the texts the package refused, by refusal code;
    `_predict.shifted` counts the texts whose offsets the package shifted
    (kept as shipped; the check runs after the timed section).
    """
    _require_clean_environment(tool)
    _require_pinned_install(tool)
    from openmed import ModelLoader, OpenMedConfig
    from openmed.core.pii import deidentify

    resolved_device = _resolve_torch_device(device)
    config = OpenMedConfig(backend=_BACKEND, device=resolved_device)
    loader = ModelLoader(config)
    call = functools.partial(
        deidentify,
        method=_METHOD,
        model_name=model_id,
        confidence_threshold=confidence_threshold,
        keep_mapping=False,
        config=config,
        use_smart_merging=True,
        lang=_LANG,
        use_safety_sweep=True,
        loader=loader,
        audit=False,
        cache_results=False,
    )
    with _hf_offline_env_restored():
        _warm_up(call, tool)
        pipe = _cached_pipeline(loader, model_id, tool)
    _check_loaded(pipe, revision, resolved_device, tool)
    _require_no_detector_plugins(tool)
    _check_label_coverage(_emittable_labels(pipe), OPENMED_DEIDENTIFY_LABEL_MAP, tool=tool)
    refusals: Counter = Counter()
    shifted: Counter = Counter()

    def _predict(text: str) -> ToolResult:
        t0 = time.perf_counter()
        result = _deidentify_or_refusal(call, text, refusals, tool)
        spans: list[Span] = []
        scores: list[float] = []
        if result is not None:
            lead = _leading_offset(result, text, tool)
            spans, scores = _project(result.pii_entities, result.original_text, lead, label_cut, tool)
        elapsed_ms = (time.perf_counter() - t0) * _MS_PER_S
        if result is not None:
            _count_shift(result.original_text, config, shifted, tool)
        return ToolResult(spans, elapsed_ms, scores=tuple(scores))

    _predict.refusals = refusals  # type: ignore[attr-defined]
    _predict.shifted = shifted  # type: ignore[attr-defined]
    return _predict
