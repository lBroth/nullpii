# SPDX-License-Identifier: Apache-2.0
"""Run nullpii on bundled or public datasets and emit per-locale accuracy."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import click

from . import datasets, public_datasets
from .adapters import nullpii_predictor
from .metrics import evaluate, macro_f1


@click.command()
@click.option("--out", type=click.Path(dir_okay=False), required=True, help="JSON output path.")
@click.option(
    "--dataset",
    type=click.Choice(
        ["bundled", "conll2003", "wikiann", "ai4privacy/pii-masking-300k", "presidio-synthetic"],
    ),
    default="bundled",
    help="Dataset to evaluate against.",
)
@click.option("--max-samples", type=int, default=200)
@click.option("--backend", default="cpu")
@click.option("--variant", default="int8")
def main(out: str, dataset: str, max_samples: int, backend: str, variant: str) -> None:
    predictor = nullpii_predictor(backend=backend, variant=variant)
    if dataset == "bundled":
        result = _run_bundled(predictor)
    else:
        result = _run_public(predictor, dataset, max_samples)
    Path(out).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")


def _run_bundled(predictor) -> dict:
    out: dict = {}
    for locale in [*datasets.LOCALES, datasets.ADVERSARIAL]:
        try:
            ds = datasets.load(locale)
        except FileNotFoundError:
            continue
        preds = [list(predictor(s.text).spans) for s in ds.samples]
        truths = [list(s.spans) for s in ds.samples]
        m = evaluate(preds, truths)
        out[locale] = {
            "n_samples": len(ds.samples),
            "macro_f1": macro_f1(m),
            "by_label": {k: asdict(v) for k, v in m.items()},
        }
    return out


def _run_public(predictor, name: str, max_samples: int) -> dict:
    ds = public_datasets.load(name, max_samples=max_samples)  # type: ignore[arg-type]
    preds = [list(predictor(s.text).spans) for s in ds.samples]
    truths = [list(s.spans) for s in ds.samples]
    m = evaluate(preds, truths)
    return {
        ds.name: {
            "n_samples": len(ds.samples),
            "macro_f1": macro_f1(m),
            "citation": ds.citation,
            "by_label": {k: asdict(v) for k, v in m.items()},
        },
    }


if __name__ == "__main__":
    main()
