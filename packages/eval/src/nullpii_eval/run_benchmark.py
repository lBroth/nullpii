# SPDX-License-Identifier: Apache-2.0
"""Latency / throughput benchmark — fixed input, both tools."""
from __future__ import annotations

import json
import platform
import time
from pathlib import Path

import click

from .adapters import nullpii_predictor, presidio_predictor

PROMPT_128 = "John Smith lives at 42 Oak Avenue, Brooklyn, NY 11201. " * 4
PROMPT_512 = "John Smith lives at 42 Oak Avenue, Brooklyn, NY 11201. " * 16


@click.command()
@click.option("--out", type=click.Path(dir_okay=False), required=True)
@click.option("--runs", type=int, default=3)
@click.option("--variant", default="int8")
@click.option("--include-presidio/--no-include-presidio", default=True)
def main(out: str, runs: int, variant: str, include_presidio: bool) -> None:
    np_pred = nullpii_predictor(variant=variant)
    payload = {"nullpii": _bench(np_pred, runs)}
    if include_presidio:
        try:
            ps_pred = presidio_predictor()
            payload["presidio"] = _bench(ps_pred, runs)
        except ImportError as e:
            payload["presidio"] = {"error": str(e)}

    Path(out).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _bench(predictor, runs: int) -> dict:
    # warmup
    predictor(PROMPT_128)
    res128 = _measure(predictor, PROMPT_128, runs)
    res512 = _measure(predictor, PROMPT_512, runs)
    tokens128 = max(1, len(PROMPT_128.split()))
    tokens512 = max(1, len(PROMPT_512.split()))
    return {
        "hardware": f"{platform.system()} / {platform.machine()}",
        "ms_128": res128,
        "ms_512": res512,
        "tps_128": tokens128 / (res128 / 1000),
        "tps_512": tokens512 / (res512 / 1000),
    }


def _measure(predictor, text: str, runs: int) -> float:
    durations = []
    for _ in range(runs):
        t0 = time.perf_counter()
        predictor(text)
        durations.append((time.perf_counter() - t0) * 1000)
    return sum(durations) / len(durations)


if __name__ == "__main__":
    main()
