# SPDX-License-Identifier: Apache-2.0
"""Microsoft Presidio, run the way its documentation sets it up for
multilingual text.

"As shipped" here means presidio-analyzer 2.2.364 with nothing added,
removed or re-tuned. For each language a text is in, one `AnalyzerEngine`
is built the way the docs' "Configure Presidio to use the new model ->
Via code" recipe builds one, restricted to that language:

1. `NlpEngineProvider(nlp_configuration=...)` creates a spaCy `NlpEngine`
   holding one NER model, for that language;
2. `AnalyzerEngine(nlp_engine=..., supported_languages=[language])` builds
   the default recognizer registry itself (`conf/default_recognizers.yaml`
   for that language, plus the `SpacyRecognizer` of the NLP engine), the
   default `LemmaContextAwareEnhancer` and `default_score_threshold` 0;
3. every text goes through `analyze(text=..., language=...)`.

The NLP configuration keeps the `ner_model_configuration` of Presidio's own
`conf/default.yaml`, the file `AnalyzerEngine()` reads (entity mapping,
ignored labels including ORGANIZATION, low-confidence handling), for every
language's model. It is read from the installed package, not copied.

Sources (tag 2.2.364 of github.com/data-privacy-stack/presidio, which
github.com/microsoft/presidio redirects to): docs/analyzer/languages.md,
docs/analyzer/customizing_nlp_models.md,
docs/analyzer/nlp_engines/spacy_stanza.md,
docs/analyzer/recognizer_registry_provider.md, and the package's
conf/default.yaml and conf/default_recognizers.yaml.

Model per language (spaCy 3.8 pipelines, release 3.8.0): where spaCy ships
a trained pipeline for the language, its largest CPU one: `en_core_web_lg`
(Presidio's own default for English), `zh_core_web_lg`, and
`<lang>_core_news_lg` for de, fr, it, es, nl, pt, pl, ro, da, fi, sv, lt,
el, hr, sl, ja, ko, ru. Where spaCy ships none (bg, cs, et, ga, hu, lv, mt,
sk, sr, ar, hi, id, th, vi), spaCy's multilingual NER `xx_ent_wiki_sm`. The docs present spaCy and Stanza as equal routes and
prescribe neither for such languages; staying on spaCy keeps one framework
and one NLP engine class across languages.

Disclosures:

- The language passed to `analyze()` is the sample's gold language
  (`Sample.language`), handed over per call. Presidio does not detect the
  language itself; its API leaves that to the caller. A sample without one
  is analysed as "en", Presidio's default. A code outside
  `SUPPORTED_LANGUAGES` raises.
- Languages without a spaCy pipeline run on `xx_ent_wiki_sm`, a small
  WikiNER model with no lemmatizer, so the context enhancer finds no
  context words there. Its tokenizer splits on spaces and punctuation, so
  in Thai, written without spaces between words, a token spans a phrase.
- The default registry is what it is per language: credit cards are
  recognized for en, es, it and pl only (`CreditCardRecognizer` lists no
  other language), US / UK identifiers for en only, ES NIF / NIE for es,
  IT fiscal code / VAT / ID card / passport / driving licence for it,
  PL PESEL for pl; every other language gets the language-agnostic set
  (crypto, date, email, IBAN, IP, MAC, phone, URL, and the US DEA
  `MedicalLicenseRecognizer`) with English context words. Recognizers the
  YAML ships disabled (all German ones, UK NINO, ...) stay disabled.
- `PhoneRecognizer` matches the regions US, GB, DE, FR, IL, IN, CA, BR
  (2.2.364 fixes the "UK" and "FE" region typos of 2.2.362, which hid
  British and French national-format numbers); other countries' numbers
  are found only in international format.
- `SpacyRecognizer` returns only spaCy labels named in
  `model_to_presidio_entity_mapping`, which the docs have the user set for
  the model they configure. default.yaml's mapping covers the OntoNotes and
  WikiNER labels; the Polish, Swedish, Romanian, Korean and Japanese
  pipelines use other names for the same entities, so those are added
  (`_MODEL_LABEL_MAPPING`). Without them Polish and Korean would get no NER
  entity at all and Swedish no person. Labels with no Presidio entity
  (WikiNER MISC, Swedish EVN/WRK, Romanian PERIOD, Croatian/Slovene
  DERIV_PER, Korean QT, Japanese MOVEMENT/PET_NAME/TITLE_AFFIX) stay
  unmapped, as shipped.
- Each engine is warmed up at build with one synthetic text, so Presidio's
  lazily loaded pieces (recognizers, and the public-suffix list tldextract
  uses for e-mail validation, fetched once per environment and cached in
  ~/.cache/python-tldextract) are loaded before the first timed call and
  predict time does no I/O.
- Presidio's log records (silent unless the caller configures logging) are
  stripped of their arguments, since the IBAN recognizer logs the
  candidate text it fails to validate, and each distinct message passes
  once.
- Every engine stays cached once built. Measured resident memory on CPU:
  about 0.8 GB per engine for de, fr, it, es, nl, pt, pl, ro, da, lt, el,
  0.25 GB for fi / hr / sl / sv, 0.6 GB for en, 0.3 GB per xx language;
  13.3 GB for the whole process with the first 25 loaded (ja, ko, ru, zh
  and the xx languages ar, hi, id, th, vi were added later, for
  mama-deid's validation split, and not measured).

Label map: same SYMMETRY RULE as `_RIZZO_LABEL_MAP` in `adapters.py`. An
entity maps to X iff our gold loaders map the equivalent gold concept to X,
and to None, an explicit drop, where the gold ignores the concept. The
PIIMB `privy` gold map (`_PIIMB_GOLD_MAPS["privy"]`) uses Presidio's own
entity names and is the first reference; ai4privacy / Isotonic / rizzo /
Nemotron gold maps decide where it is silent.
"""
from __future__ import annotations

import copy
import logging
import time
from collections.abc import Callable
from importlib import resources
from typing import TYPE_CHECKING

from .adapters import LabelCut, ToolResult, _check_label_coverage, _map_native_label
from .datasets import Span

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine, RecognizerResult

TOOL = "presidio"
DEFAULT_LANGUAGE = "en"
_NLP_ENGINE_NAME = "spacy"
_PRESIDIO_LOGGER = "presidio-analyzer"
_SHIPPED_NLP_CONF = "default.yaml"
_NER_CONF_KEY = "ner_model_configuration"
# Synthetic, no PII: an e-mail so the warm-up also loads the public-suffix list.
_WARMUP_TEXT = "Contact: warmup@example.com"
_MS_PER_S = 1000.0

# spaCy NER labels of the configured pipelines that default.yaml's
# `model_to_presidio_entity_mapping` does not name, mapped to the Presidio
# entity it gives their OntoNotes / WikiNER equivalents.
_MODEL_LABEL_MAPPING: dict[str, str] = {
    # pl_core_news_lg (NKJP)
    "persName": "PERSON",
    "placeName": "LOCATION",
    "geogName": "LOCATION",
    "orgName": "ORGANIZATION",
    "date": "DATE_TIME",
    "time": "DATE_TIME",
    # sv_core_news_lg (SUC)
    "PRS": "PERSON",
    "TME": "DATE_TIME",
    # ro_core_news_lg (RONEC)
    "DATETIME": "DATE_TIME",
    "FACILITY": "LOCATION",
    "NAT_REL_POL": "NRP",
    # ko_core_news_lg (KLUE)
    "PS": "PERSON",
    "LC": "LOCATION",
    "OG": "ORGANIZATION",
    "DT": "DATE_TIME",
    "TI": "DATE_TIME",
    # ja_core_news_lg (GSD-NE)
    "PHONE": "PHONE_NUMBER",
}

_XX_MODEL = "xx_ent_wiki_sm"
# Languages of our datasets that spaCy ships a trained pipeline for.
_SPACY_PIPELINES: dict[str, str] = {
    "en": "en_core_web_lg",
    "de": "de_core_news_lg",
    "fr": "fr_core_news_lg",
    "it": "it_core_news_lg",
    "es": "es_core_news_lg",
    "nl": "nl_core_news_lg",
    "pt": "pt_core_news_lg",
    "pl": "pl_core_news_lg",
    "ro": "ro_core_news_lg",
    "da": "da_core_news_lg",
    "fi": "fi_core_news_lg",
    "sv": "sv_core_news_lg",
    "lt": "lt_core_news_lg",
    "el": "el_core_news_lg",
    "hr": "hr_core_news_lg",
    "sl": "sl_core_news_lg",
    "ja": "ja_core_news_lg",
    "ko": "ko_core_news_lg",
    "ru": "ru_core_news_lg",
    "zh": "zh_core_web_lg",
}
# Languages of our datasets (PIIMB ai4privacy-multi / mapa-eur-lex, R3's
# mama-deid-val) that spaCy ships no pipeline for.
_XX_LANGUAGES = ("bg", "cs", "et", "ga", "hu", "lv", "mt", "sk", "sr", "ar", "hi", "id", "th", "vi")

SPACY_MODEL_BY_LANGUAGE: dict[str, str] = {
    **_SPACY_PIPELINES,
    **{language: _XX_MODEL for language in _XX_LANGUAGES},
}
SUPPORTED_LANGUAGES = frozenset(SPACY_MODEL_BY_LANGUAGE)

# Presidio entity -> nullpii label; None drops the prediction. The comment
# names the gold key each decision mirrors (privy = `_PIIMB_GOLD_MAPS["privy"]`).
_PRESIDIO_LABEL_MAP: dict[str, str | None] = {
    # ─── NER (SpacyRecognizer, through default.yaml's mapping) ────
    "PERSON": "private_person",          # privy PERSON; ai4privacy FIRSTNAME / LASTNAME
    "LOCATION": "private_address",       # privy LOCATION; ai4privacy CITY / STATE / COUNTRY
    "DATE_TIME": "private_date",         # privy DATE_TIME; ai4privacy DATE / TIME
    "NRP": None,                         # privy NRP (nationality, religion, politics); mapa nationality
    "ORGANIZATION": None,                # privy ORGANIZATION; `_NER_LABEL_MAP` ORG; isotonic COMPANYNAME
    # ─── Contact and network ──────────────────────────────────────
    "EMAIL_ADDRESS": "private_email",    # privy EMAIL_ADDRESS
    "PHONE_NUMBER": "private_phone",     # privy PHONE_NUMBER
    "URL": "private_url",                # privy URL
    "IP_ADDRESS": "private_ip",          # privy IP_ADDRESS
    "MAC_ADDRESS": "private_mac",        # privy MAC_ADDRESS; isotonic MACADDRESS / MAC
    # Not emitted by the default registry; kept from the old map.
    "STREET_ADDRESS": "private_address",  # presidio-synthetic STREET_ADDRESS
    # ─── Financial ────────────────────────────────────────────────
    "IBAN_CODE": "account_number",       # privy IBAN_CODE
    "CREDIT_CARD": "account_number",     # privy CREDIT_CARD
    "CRYPTO": "account_number",          # ai4privacy / isotonic BITCOINADDRESS (Presidio: BTC only)
    "US_BANK_NUMBER": "account_number",  # privy US_BANK_NUMBER
    # ─── Identity documents ───────────────────────────────────────
    "US_PASSPORT": "private_passport",   # privy US_PASSPORT
    "IT_PASSPORT": "private_passport",   # ai4privacy PASSPORTNUM
    "IN_PASSPORT": "private_passport",   # ai4privacy PASSPORTNUM
    "US_DRIVER_LICENSE": "private_driver_license",  # privy US_DRIVER_LICENSE
    # ai4privacy DRIVERLICENSENUM. NB rizzo-clean-val's gold folds driving
    # licences into account_number (vendor methodology), as US_DRIVER_LICENSE.
    "IT_DRIVER_LICENSE": "private_driver_license",
    "IT_IDENTITY_CARD": "account_number",  # ai4privacy IDCARDNUM; rizzo IDCARDNUM
    # ─── National, tax and health identifiers ─────────────────────
    "US_SSN": "account_number",          # privy US_SSN
    "US_ITIN": "account_number",         # privy US_ITIN
    "ES_NIF": "account_number",          # ai4privacy TAXNUM (NIF = personal tax id)
    "ES_NIE": "account_number",          # ai4privacy IDCARDNUM (foreigner id number)
    "IT_FISCAL_CODE": "account_number",  # rizzo CF; ai4privacy TAXNUM
    "IT_VAT_CODE": "account_number",     # rizzo PIVA; ai4privacy TAXNUM
    "PL_PESEL": "account_number",        # ai4privacy SOCIALNUM / IDCARDNUM
    "UK_NHS": "account_number",          # gretel health_plan_beneficiary_number
    "MEDICAL_LICENSE": "account_number",  # gretel certificate_license_number (US DEA number)
    # Disabled in default_recognizers.yaml; kept from the old map.
    "IN_AADHAAR": "account_number",      # ai4privacy IDCARDNUM; gretel national_id
    "IN_PAN": "account_number",          # ai4privacy TAXNUM; gretel tax_id
    "IN_VOTER": "account_number",        # ai4privacy IDCARDNUM
    "SG_NRIC_FIN": "account_number",     # ai4privacy IDCARDNUM
    "AU_ABN": "account_number",          # ai4privacy TAXNUM
    "AU_ACN": "account_number",          # ai4privacy TAXNUM
    "AU_TFN": "account_number",          # ai4privacy TAXNUM
    "AU_MEDICARE": "account_number",     # gretel health_plan_beneficiary_number
    # ─── Secrets (no default recognizer; kept from the old map) ───
    "API_KEY": "secret",                 # isotonic API_KEY
    "AWS_ACCESS_KEY": "secret",          # bigcode KEY / API_KEY
    "AWS_SECRET_KEY": "secret",          # bigcode KEY / SECRET
}


class _RedactedOnce(logging.Filter):
    """Keeps Presidio's log lines free of input text and of repeats.

    Some records carry analysed text as an argument (IbanRecognizer logs the
    candidate it fails to validate), and the bench never prints dataset
    text: the arguments are dropped and the message template is kept. A
    message repeated per entity is printed the first time only.
    """

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        record.args = None
        message = str(record.msg)
        if message in self._seen:
            return False
        self._seen.add(message)
        return True


def _install_log_filter() -> None:
    """Attach `_RedactedOnce` to Presidio's logger, once per process."""
    logger = logging.getLogger(_PRESIDIO_LOGGER)
    if any(isinstance(f, _RedactedOnce) for f in logger.filters):
        return
    logger.addFilter(_RedactedOnce())


def _shipped_ner_model_configuration() -> dict:
    """`ner_model_configuration` of the installed analyzer's conf/default.yaml,
    the NLP configuration `AnalyzerEngine()` reads by default, with the
    configured pipelines' own label names added to its entity mapping."""
    import yaml

    conf_file = resources.files("presidio_analyzer") / "conf" / _SHIPPED_NLP_CONF
    conf = yaml.safe_load(conf_file.read_text(encoding="utf-8"))
    if _NER_CONF_KEY not in conf:
        raise ValueError(f"[{TOOL}] {_SHIPPED_NLP_CONF} has no {_NER_CONF_KEY!r} section")
    ner = conf[_NER_CONF_KEY]
    shipped = ner["model_to_presidio_entity_mapping"]
    clashes = sorted(set(shipped) & set(_MODEL_LABEL_MAPPING))
    if clashes:
        raise ValueError(f"[{TOOL}] {_SHIPPED_NLP_CONF} already maps {clashes}")
    return {**ner, "model_to_presidio_entity_mapping": {**shipped, **_MODEL_LABEL_MAPPING}}


def _resolve_language(language: str | None) -> str:
    """The language to analyse under: the sample's, or Presidio's default."""
    if language is None:
        return DEFAULT_LANGUAGE
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"[{TOOL}] no NER model configured for language {language!r}; "
            f"supported: {sorted(SUPPORTED_LANGUAGES)}",
        )
    return language


def _require_installed(model: str) -> None:
    """Fail loud instead of letting Presidio download a missing model."""
    import spacy

    if not spacy.util.is_package(model):
        raise RuntimeError(
            f"[{TOOL}] spaCy model {model!r} is not installed; "
            "install packages/eval/requirements-presidio.txt",
        )


def _check_no_recognizer_thresholds(analyzer: AnalyzerEngine, language: str) -> None:
    """`analyze(score_threshold=...)` bypasses recognizer-level thresholds,
    which is only "as shipped" while the registry sets none."""
    with_thresholds = sorted(
        r.name for r in analyzer.registry.get_recognizers(language=language, all_fields=True) if r.score_thresholds
    )
    if with_thresholds:
        raise ValueError(f"[{TOOL}/{language}] recognizers with their own score thresholds: {with_thresholds}")


def _build_engine(language: str, ner_model_configuration: dict) -> AnalyzerEngine:
    """One `AnalyzerEngine` for one language, per the docs' via-code recipe."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    model = SPACY_MODEL_BY_LANGUAGE[language]
    _require_installed(model)
    nlp_configuration = {
        "nlp_engine_name": _NLP_ENGINE_NAME,
        "models": [{"lang_code": language, "model_name": model}],
        _NER_CONF_KEY: copy.deepcopy(ner_model_configuration),
    }
    nlp_engine = NlpEngineProvider(nlp_configuration=nlp_configuration).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=[language])
    _check_no_recognizer_thresholds(analyzer, language)
    _check_label_coverage(set(analyzer.get_supported_entities(language)), _PRESIDIO_LABEL_MAP, tool=TOOL)
    analyzer.analyze(text=_WARMUP_TEXT, language=language)
    return analyzer


def _map_results(
    results: list[RecognizerResult], label_cut: LabelCut | None,
) -> tuple[list[Span], list[float]]:
    """Presidio results -> nullpii spans and their scores, after the cut."""
    spans: list[Span] = []
    scores: list[float] = []
    for r in results:
        label = _map_native_label(r.entity_type, _PRESIDIO_LABEL_MAP, tool=TOOL)
        score = float(r.score)
        if label is None or (label_cut is not None and not label_cut.keeps(label, score)):
            continue
        spans.append(Span(label, int(r.start), int(r.end)))
        scores.append(score)
    return spans, scores


def presidio_predictor(
    *, label_cut: LabelCut | None = None, score_threshold: float = 0.0,
) -> Callable[..., ToolResult]:
    """Presidio analyzer per its multilingual docs (see the module docstring).

    The returned `_predict(text, language=None)` analyses `text` under
    `language` (ISO 639-1; None means "en") on that language's engine, built
    on first use and cached. `score_threshold` goes to `analyze()`;
    `label_cut` then filters the mapped spans by Presidio's score. The
    timing covers `analyze()` and the label mapping, not engine construction.
    """
    _install_log_filter()
    ner_model_configuration = _shipped_ner_model_configuration()
    engines: dict[str, AnalyzerEngine] = {}

    def _engine(language: str) -> AnalyzerEngine:
        if language not in engines:
            engines[language] = _build_engine(language, ner_model_configuration)
        return engines[language]

    def _predict(text: str, language: str | None = None) -> ToolResult:
        resolved = _resolve_language(language)
        analyzer = _engine(resolved)
        t0 = time.perf_counter()
        results = analyzer.analyze(text=text, language=resolved, score_threshold=score_threshold)
        spans, scores = _map_results(results, label_cut)
        elapsed_ms = (time.perf_counter() - t0) * _MS_PER_S
        return ToolResult(spans, elapsed_ms, scores=tuple(scores))

    _predict.wants_language = True  # type: ignore[attr-defined]
    return _predict
