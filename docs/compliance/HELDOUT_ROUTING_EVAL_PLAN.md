# Held-out routing-eval corpus — plan

## Goal

Build a 500-document hand-annotated corpus that is **never** used to tune the heuristic router (`_is_dev_paste_like`) or the LoRA adapters. Used **only** for v10 go/no-go gating and for ongoing regression checks.

## Why

The current `_is_dev_paste_like` router (`packages/eval/src/nullpii_eval/adapters.py:2109+`) is an a-priori heuristic. The compliance review flagged that even good-faith tuning becomes implicit test-set tuning without an isolated eval set. v10 LoRA-per-domain training will need a routing-quality signal that isn't on the training/dev path.

## Specification

### 4 domains × 5 locales × 25 documents per cell = 500 docs

| Domain | Sources |
|---|---|
| dev-paste | curated GitHub PR discussions (CC BY licensed projects), Stack Overflow (CC BY-SA), public RFC drafts, anonymised customer-support ticket bodies |
| legal | TAB ECHR (CC BY 4.0), public US court records (PACER unsealed), public EU court records (HUDOC), public contracts (EDGAR) |
| medical | MEDDOCAN (CC BY 4.0, Spanish only — fill EN/IT/DE/FR with synthetic narrative reviewed by clinical advisor) |
| general | mixed conversational + administrative + customer-facing emails |

| Locale | Coverage |
|---|---|
| en | 100 docs (25 per domain) |
| it | 100 docs |
| de | 100 docs |
| fr | 100 docs |
| es | 100 docs |

### Each document carries

```json
{
  "id": "routing-eval-001",
  "domain": "legal | dev-paste | medical | general",
  "locale": "en | it | de | fr | es",
  "text": "...",
  "spans": [{"label": "...", "start": 0, "end": 0}],
  "annotator_a_id": "...",
  "annotator_b_id": "...",
  "annotator_a_decision": {...},
  "annotator_b_decision": {...},
  "adjudicated": {...},
  "kappa": 0.0,
  "license": "CC BY 4.0 | CC BY-SA | proprietary-public",
  "source_url": "..."
}
```

### Annotator workflow

- 2 annotators per document (independent).
- Spans annotated per the nullpii 8-class schema (`adapters.py:581-596`).
- Cohen's κ ≥ 0.7 required for span agreement; below threshold → adjudicator (DPO or domain expert).
- Tracking: kappa per-domain × per-locale × per-class, target ≥ 0.7 per cell.

### Document selection

Scrape candidate documents → filter for natural PII presence → sample stratified by **document length** (short < 500 chars / medium 500–2000 / long > 2000) and by **PII density** (sparse 1–3 spans / medium 4–10 / dense > 10).

### License audit

Each source URL must be reviewed for redistribution license. CC BY 4.0 → include. CC BY-SA → include with shareback notice. Proprietary → request permission OR exclude.

## Effort

- 2 annotators × 250 docs each × ~10 min/doc = 80 hours/annotator = ~2 weeks per annotator.
- Adjudicator: 1 person × 50 disputed docs × 20 min/doc = 17 hours = ~half-week.
- Tooling setup (annotation UI, kappa tracking, redaction pipeline): ~1 week engineer time.
- License audit: ~1 week.
- **Total: 3–4 weeks calendar.**

## Storage

- `packages/eval/datasets/routing-eval/` — gitignored.
- Encrypted at rest (sops-encrypted index file with annotator IDs + license metadata).
- Annotator IDs pseudonymised in the published version.

## Use protocol

- This corpus is **forbidden** as a tuning signal.
- Only inspected at v10 release-candidate cut and during quarterly regression checks.
- Any drift > 0.02 routing accuracy triggers a review (not a tune); review concludes either (a) accept drift, (b) re-do v10 training with new corpus injection, or (c) document a known regression.

## Do NOT

- Do NOT use this corpus to tune the heuristic.
- Do NOT use this corpus as a v10 training source.
- Do NOT publish raw text without per-source license review.
- Do NOT lower the kappa threshold to fit a deadline.

## Sign-off

Created: 2026-05-03. To be reviewed by DPO + privacy counsel before v10 ship.
