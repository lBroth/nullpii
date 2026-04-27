# SPDX-License-Identifier: Apache-2.0
"""Render markdown tables from accuracy/compare/benchmark JSON outputs.

Used by the doc generation step. Reads JSON produced by
`run_accuracy.py` / `run_compare.py` / `run_benchmark.py` and writes a
Markdown file ready to drop into `docs/guide/`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click


@click.command()
@click.option("--accuracy", type=click.Path(exists=True, dir_okay=False))
@click.option("--compare", type=click.Path(exists=True, dir_okay=False))
@click.option("--benchmark", type=click.Path(exists=True, dir_okay=False))
@click.option("--out", type=click.Path(dir_okay=False), required=True)
def main(accuracy: str | None, compare: str | None, benchmark: str | None, out: str) -> None:
    sections: list[str] = ["# Eval results", ""]
    sections.append("Auto-generated. Re-run `python -m nullpii_eval.render_tables` to refresh.\n")

    if accuracy is not None:
        sections.append(_render_accuracy(json.loads(Path(accuracy).read_text("utf-8"))))
    if compare is not None:
        sections.append(_render_compare(json.loads(Path(compare).read_text("utf-8"))))
    if benchmark is not None:
        sections.append(_render_benchmark(json.loads(Path(benchmark).read_text("utf-8"))))

    Path(out).write_text("\n".join(sections), encoding="utf-8")
    sys.stdout.write(f"wrote {out}\n")


def _render_accuracy(data: dict) -> str:
    rows = ["## Accuracy by locale", "", "| Locale | Macro F1 | n samples |", "| --- | ---: | ---: |"]
    for locale, payload in sorted(data.items()):
        rows.append(f"| {locale} | {payload['macro_f1']:.3f} | {payload['n_samples']} |")
    rows.append("")
    rows.append("### Per-category (English baseline)")
    rows.append("")
    rows.append("| Category | Precision | Recall | F1 |")
    rows.append("| --- | ---: | ---: | ---: |")
    for cat, m in sorted(data.get("en", {}).get("by_label", {}).items()):
        rows.append(f"| `{cat}` | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} |")
    return "\n".join(rows)


def _render_compare(data: dict) -> str:
    rows = [
        "## nullpii vs Microsoft Presidio",
        "",
        "| Locale | nullpii F1 | Presidio F1 | Δ |",
        "| --- | ---: | ---: | ---: |",
    ]
    for locale, p in sorted(data.items()):
        d = p["nullpii_f1"] - p["presidio_f1"]
        sign = "+" if d >= 0 else ""
        rows.append(f"| {locale} | {p['nullpii_f1']:.3f} | {p['presidio_f1']:.3f} | {sign}{d:.3f} |")
    return "\n".join(rows)


def _render_benchmark(data: dict) -> str:
    rows = [
        "## Throughput",
        "",
        "| Tool | Hardware | seq=128 (tok/s) | seq=512 (tok/s) |",
        "| --- | --- | ---: | ---: |",
    ]
    for tool, payload in data.items():
        rows.append(
            f"| {tool} | {payload['hardware']} | {payload['tps_128']:.0f} | {payload['tps_512']:.0f} |"
        )
    return "\n".join(rows)


if __name__ == "__main__":
    main()
