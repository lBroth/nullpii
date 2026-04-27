# SPDX-License-Identifier: Apache-2.0
"""Head-to-head: nullpii vs Presidio vs bare spaCy on the same dataset."""
from __future__ import annotations

import json
from pathlib import Path

import click

from . import datasets, public_datasets
from .adapters import nullpii_predictor, presidio_predictor, spacy_predictor
from .metrics import evaluate, macro_f1


@click.command()
@click.option("--out", type=click.Path(dir_okay=False), required=True)
@click.option(
    "--dataset",
    type=click.Choice(
        [
            "bundled",
            "conll2003",
            "wikiann",
            "ai4privacy/pii-masking-300k",
            "presidio-synthetic",
            "isotonic/pii-masking-200k",
        ],
    ),
    default="bundled",
)
@click.option("--locale", default="en", help="Locale for bundled / wikiann / isotonic datasets.")
@click.option(
    "--max-samples",
    type=int,
    default=None,
    help="Cap samples for smoke runs. Omit for full dataset (release benchmark).",
)
@click.option("--variant", default="int8")
@click.option("--include-spacy/--no-include-spacy", default=True)
@click.option("--include-presidio/--no-include-presidio", default=True)
def main(
    out: str,
    dataset: str,
    locale: str,
    max_samples: int | None,
    variant: str,
    include_spacy: bool,
    include_presidio: bool,
) -> None:
    nullpii = nullpii_predictor(variant=variant)

    samples = _load_samples(dataset, locale, max_samples)
    truths = [list(s.spans) for s in samples]

    payload: dict = {dataset: {"locale": locale, "n_samples": len(samples)}}

    nullpii_preds = [list(nullpii(s.text).spans) for s in samples]
    payload[dataset]["nullpii_f1"] = macro_f1(evaluate(nullpii_preds, truths))

    if include_presidio:
        try:
            presidio = presidio_predictor(language=locale if locale == "en" else "en")
            preds = [list(presidio(s.text).spans) for s in samples]
            payload[dataset]["presidio_f1"] = macro_f1(evaluate(preds, truths))
        except Exception as e:  # noqa: BLE001
            payload[dataset]["presidio_error"] = str(e)

    if include_spacy:
        try:
            sp = spacy_predictor(locale=locale)
            preds = [list(sp(s.text).spans) for s in samples]
            payload[dataset]["spacy_f1"] = macro_f1(evaluate(preds, truths))
            payload[dataset]["spacy_model"] = locale
        except Exception as e:  # noqa: BLE001
            payload[dataset]["spacy_error"] = str(e)

    Path(out).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_samples(name: str, locale: str, max_samples: int | None):
    if name == "bundled":
        return list(datasets.load(locale).samples)
    if name == "wikiann":
        # delegate to private function so we can pass the per-call locale
        from . import public_datasets as pd

        return list(pd._load_wikiann(max_samples, lang=locale).samples)  # type: ignore[attr-defined]
    pub = public_datasets.load(name, max_samples=max_samples, locale=locale)  # type: ignore[arg-type]
    return list(pub.samples)


if __name__ == "__main__":
    main()
