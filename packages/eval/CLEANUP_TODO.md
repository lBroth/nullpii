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
