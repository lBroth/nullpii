# Cleanup TODO

Tracked from the iter-N exploration loop on `nullpii-gliner-ensemble` /
`iter-explore-19-21` branches. These are functions / patterns the
benchmark proved dead or marginal — safe to remove or simplify.

## Confirmed dead (Δ F1 ≤ 0.001 across 4271 samples)

- **CC 16-digit regex** — already dropped in iter-22 (commit 95484ce).
  Never fires on any dataset.
- **Bare-domain URL regex** — already dropped in iter-20 (commit a3c01b6).
  Was a net negative (FP > recall).

## Marginal / candidate for removal

- **Phone regex** (`r"\+\d{1,3}[\s-]?…"`) — iter-21 shows -0.005 on
  long-prompts when removed. GLiNER already at 7% miss on phones.
  Low value, occasional FP on version strings. Consider drop.
- **`category_routing_predictor`** in adapters.py — strategy proven
  worse than `primary` on every dataset (iter-8 -0.135 vs baseline).
  Keep API surface for users but document as not recommended.
- **`multi_ensemble_predictor` strategies `intersection`, `majority`** —
  both lose vs `primary` (iter-15 union -0.026, iter-16 majority -0.075).
  Keep but document as recall-killers.

## Code added during iter-26..28 — confirmed dead

These predictors / wrappers were authored as candidates but failed
their smoke test. Safe to drop (or keep behind opt-in flag, undocumented):

- **`negative_context_predictor`** (iter-27): drops spans near
  "example/test/placeholder" keywords. Lost -0.10 bundled / -0.09
  long-prompts because legitimate "example.com" emails get filtered.
  Drop or only enable for adversarial subset.
- **`span_coalesce_predictor`** (iter-28): merges same-label adjacent
  spans separated by gap. Wins bundled +0.008 but loses isotonic
  -0.010 each locale. Net -0.004. Drop.
- **`boundary_refined_predictor.expand_word_chars=True`** (iter-26):
  extends spans outward to word boundaries instead of trimming.
  Bundled -0.008, isotonic noise. Drop the option.
- **Locale-specific regex** (iter-25 — German Steuer-ID 11-digit, IT
  codice fiscale, ES NIF, FR SIREN, IPv4, crypto addresses): the
  German 11-digit `r"\b\d{11}\b"` is too greedy and creates FPs on
  any 11-digit number. Drop or tighten radically.
- **GLiNER non-PII variants** (iter-23 `urchade/gliner_multi-v2.1`):
  base model loses -0.027 bundled. Keep `model_name` parameter but
  document gliner_multi_pii-v1 as the only recommended.

## Insight (iter-32 relaxed IoU 0.3)

Annotation-noise ceiling: re-running best config with IoU 0.3 instead
of strict 0.5 gives F1 **0.6860** (vs 0.6713). The +0.0147 gap is
"free" recovery only with looser matching — i.e. the bench dataset
ground truth has real boundary noise on bundled (+0.023) and isotonic
(+0.014..0.020), but long-prompts annotations are tight (+0.002).
Implication: target ≥0.80 strict IoU is NOT reachable without
LLM-judge or model finetune (both excluded from this loop).

## Strategies tested and rejected (do not reintroduce)

| Strategy | Best Δ | Reason |
|---|---|---|
| 3-way primary (np+gl+presidio) | -0.027 | Presidio adds FP on long-prompts |
| 4-way (+presidio) | -0.046 | Same |
| 4-way (+piiranha) | -0.045 | piiranha FP on long-prompts |
| 4-way (+deberta) | mixed | English-only; hurts multilingual |
| GLiNER threshold < 0.7 | -0.018 | Too many FP |
| GLiNER threshold = 0.75 | -0.001 | Same as 0.8, no advantage |
| Bias tweaks (continue/enter/bg ±0.5) | ≈0 | Defaults already optimal |

## Best known config (iter-22)

```bash
quick_ensemble.py \
  --tools nullpii,gliner,regex \
  --strategy primary \
  --gliner-threshold 0.8 \
  # --refine-boundaries enabled by default
```

- AVG PII F1: **0.6712** (cumulative +0.059 vs iter-0 baseline 0.6120)
- p50 single-call latency: 208 ms
- p95: 279 ms
- Regex pack: URL (http(s)/www only), email, AWS+GitHub+Stripe+OpenAI
  keys, IBAN, SSN, phone

## Functions to potentially purge

If we ship this as the production ensemble:

- `category_routing_predictor` — kept for API completeness, document as
  experimental
- `intersection` and `majority` mergers in `multi_ensemble_predictor` —
  same
- `nullpii_gliner_ensemble_predictor` — superseded by
  `multi_ensemble_predictor`. Mark deprecated or remove.
- DeBERTa / piiranha adapters — keep for benchmarking-only docs section

## Path to higher F1 (excluded from current loop)

- LLM-as-judge fallback (Tier 3.3): expected +0.05-0.08 on ambiguous spans
- Custom finetune of `openai/privacy-filter` on `nullpii-bench`
  (Tier 4.1): expected +0.05-0.10
- Newer GLiNER variants (only `gliner_multi_pii-v1` is PII-specific;
  base v2.1 with PII labels untested)
