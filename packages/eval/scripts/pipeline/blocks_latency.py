# SPDX-License-Identifier: Apache-2.0
"""The rendered blocks about latency: the README's tables, the paragraph
above them, the chart and its alternative text, METHOD's glance rows and
its account of what was timed, when, on which build and machine.

Every number comes from `published-bench/latency/latency.json`
(`latency.py`), timed by hand; nothing here is an output of a run of the
pipeline. Rows are sorted by the time at 30,000 characters; bold marks
the fastest printed value of each column, a rule, not a claim."""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from pipeline import blocks_r3, latency, settings, views
from pipeline.latency import Latency, LatencyError
from pipeline.prose import listing, number

RAW = "https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/"
METHOD_LATENCY = "https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md#latency"
LATENCY_FILE = "https://github.com/lBroth/nullpii/blob/main/packages/eval/published-bench/latency/latency.json"
CHART_SIZE = "30000"
SIZE_HEADS = {"2000": "2k", "30000": "30k", "100000": "100k"}
COMMIT_SHOWN = 7
# Tools the CPU table has and the GPU table cannot, and why.
CPU_ONLY = {"gliner-onnx-pii-fp32": "runs on CPU only", "presidio": "has no GPU path"}
PRESIDIO, OPENMED_LARGE = "presidio", "openmed-large"
ROUNDS_WORDS = {1: "timed once"}
RUNS_OF = {"default": "the agent default", "everything": "every category masked"}


@dataclass(frozen=True)
class Row:
    """A row of a latency table: its label as the tables print it and its
    median per call per size; `preset` for a nullpii row."""

    label: str
    ms: dict[str, float]
    preset: str | None = None

    @property
    def plain(self) -> str:
        """The label without Markdown, as the chart prints it."""
        return self.label.replace("**", "").replace("`", "")


def tool_name(tool: str) -> str:
    if tool not in blocks_r3.MATRIX_NAMES:
        raise LatencyError(f"latency: no display name for {tool}")
    return blocks_r3.MATRIX_NAMES[tool]


def rows(lat: Latency, table: str) -> list[Row]:
    """Every row of `table`, sorted by the time at 30,000 characters."""
    found = [Row(tool_name(t), ms) for t, ms in lat.tools(table).items()]
    found += [Row(f"**nullpii** ({views.PRESET_LABELS[p]})", lat.nullpii(table, p), p) for p in settings.PRESETS]
    return sorted(found, key=lambda r: (r.ms[CHART_SIZE], r.plain))


def ms(value: float) -> str:
    return f"{round(value):,}"


def _bold_fastest(cells: list[str]) -> list[str]:
    fastest = min(cells, key=lambda c: int(c.replace(",", "")))
    return [f"**{c}**" if c == fastest else c for c in cells]


def table(lat: Latency, name: str) -> str:
    shown = rows(lat, name)
    columns = [_bold_fastest([ms(r.ms[s]) for r in shown]) for s in latency.SIZES]
    lines = ["| Tool | " + " | ".join(SIZE_HEADS[s] for s in latency.SIZES) + " |",
             "|---|" + "---:|" * len(latency.SIZES)]
    lines += [f"| {r.label} | " + " | ".join(col[i] for col in columns) + " |" for i, r in enumerate(shown)]
    return "\n".join(lines)


def date(iso: str) -> str:
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B')} {d.year}"


def texts(lat: Latency, name: str) -> str:
    """"60, 12 and 5 texts per size"."""
    return listing([str(lat.plan(name)["texts"][s]) for s in latency.SIZES]) + " texts per size"


def rounds(lat: Latency, name: str) -> str:
    n = lat.plan(name)["rounds"]
    return ROUNDS_WORDS.get(n, f"{number(n)} rounds")


def _commit(lat: Latency) -> str:
    return lat.nullpii_timing["commit"][:COMMIT_SHOWN]


def _build(lat: Latency) -> str:
    n = lat.nullpii_timing
    return f"the build of `main` at {_commit(lat)} (after release {n['version']})"


# README -------------------------------------------------------------------------

def fig_alt(lat: Latency) -> str:
    shown = rows(lat, "gpu")
    first, last = shown[0], shown[-1]
    mine = listing([f"{ms(r.ms[CHART_SIZE])} {blocks_r3.CONFIG_WORDS[r.preset]}" for r in shown if r.preset])
    return (f"![GPU latency at 30,000 characters, median milliseconds per call: from {first.plain} at"
            f" {ms(first.ms[CHART_SIZE])} to {last.plain} at {ms(last.ms[CHART_SIZE])}; nullpii {mine}. The tables"
            f" below have every value.]({RAW}latency-gpu.svg)")


def readme_intro(lat: Latency) -> str:
    return ("Every tool runs the same coding-agent texts on the same idle machine, after a warm-up, at its default"
            f" setting. nullpii has two rows, its agent default and every category masked, timed on"
            f" {date(lat.nullpii_timing['date'])} with {_build(lat)}; every other tool was timed on"
            f" {date(lat.tools_timing['date'])}. Latency is timed by hand, never by the benchmark workflow"
            f" ([METHOD]({METHOD_LATENCY})).")


def _machine(lat: Latency, name: str, part: str) -> str:
    m = lat.machine(name)
    return f"{m['os']}, {m[part]}"


def _cpu_notes(lat: Latency) -> str:
    cpu, gpu = lat.tools("cpu"), lat.tools("gpu")
    only = {t for t in cpu if t not in gpu}
    if only != set(CPU_ONLY) or PRESIDIO not in cpu or OPENMED_LARGE not in cpu:
        raise LatencyError(f"latency: the CPU notes name {', '.join(CPU_ONLY)} and {OPENMED_LARGE}; the CPU-only"
                           f" tools are {', '.join(sorted(only)) or 'none'}")
    why = ", and ".join(f"{tool_name(t)} {reason}" for t, reason in CPU_ONLY.items())
    return ("Presidio is mostly patterns plus a small spaCy model; its accuracy is in the benchmark tables above."
            f" OpenMed Large's time depends a lot on the text, so its 100k figure, from"
            f" {number(lat.plan('cpu')['texts'][latency.SIZES[-1]])} texts, is rough. {why}, so neither is in the GPU"
            " table.")


def readme_tables(lat: Latency) -> str:
    return "\n".join([
        "The tables show the median time per call, in milliseconds, for texts of 2,000, 30,000 and 100,000 characters"
        " of coding-agent material (code, logs, prose, tool output). Bold marks nullpii's name and the fastest value"
        " in each column. How the texts are chosen and when each row was timed: [`METHOD.md`]"
        f"({METHOD_LATENCY}).",
        "",
        f"**GPU** ({_machine(lat, 'gpu', 'gpu')}; {texts(lat, 'gpu')}, {rounds(lat, 'gpu')}). nullpii loads"
        " `model_fp16.onnx` on CUDA.",
        "",
        table(lat, "gpu"),
        "",
        f"**CPU** ({_machine(lat, 'cpu', 'cpu')}, every tool on CPU; {texts(lat, 'cpu')}, {rounds(lat, 'cpu')},"
        " because the full plan takes hours per tool here).",
        "",
        table(lat, "cpu"),
        "",
        _cpu_notes(lat),
    ])


# Below this, a time in seconds keeps one decimal ("1.6 seconds").
WHOLE_SECONDS = 10
MS_PER_SECOND = 1000


def seconds(value: float) -> str:
    s = round(value / MS_PER_SECOND, 1)
    return f"{round(s)} seconds" if s >= WHOLE_SECONDS else f"{s:.1f} seconds"


def long_inputs(lat: Latency) -> str:
    """The README's expectation for a long text: the agent default's time
    at 100,000 characters on each table's backend."""
    size = latency.SIZES[-1]
    cpu, gpu = (seconds(lat.nullpii(t, "default")[size]) for t in ("cpu", "gpu"))
    return (f"Expect about {cpu} per {int(size):,} characters on CPU and about {gpu} on GPU (the agent default, on the"
            " machine of the [latency tables](#latency)).")


def chart_rows(lat: Latency) -> list[tuple[str, int]]:
    """The chart's bars: every GPU row at 30,000 characters."""
    return [(r.plain, round(r.ms[CHART_SIZE])) for r in rows(lat, "gpu")]


def chart_machine(lat: Latency) -> str:
    return lat.machine("gpu")["gpu"]


# METHOD -------------------------------------------------------------------------

def glance(lat: Latency) -> str:
    out = []
    for name, part in (("gpu", "gpu"), ("cpu", "cpu")):
        values = "; ".join(f"{ms(lat.nullpii(name, p)[CHART_SIZE])} ms {blocks_r3.CONFIG_WORDS[p]}"
                           for p in settings.PRESETS)
        out.append(f"| Latency on {name.upper()} ({lat.machine(name)[part]}), 30,000 characters, timed by hand on"
                   f" `main` at {_commit(lat)} | {values} |")
    return "\n".join(out)


def _runs(lat: Latency) -> str:
    parts = []
    for p in settings.PRESETS:
        found = {len(lat.runs(t, p)) for t in latency.TABLES}
        if len(found) != 1:
            raise LatencyError(f"latency: {p} has a different number of runs per table")
        n = found.pop()
        parts.append(f"{number(n)} {'run' if n == 1 else 'runs'} of {RUNS_OF[p]}")
    return (f"In each table it was timed in {listing(parts)}; a row takes the median of every round's median of its"
            " runs.")


def _partial(lat: Latency) -> str:
    gpu, cpu = (lat.nullpii(t, latency.PARTIAL)[CHART_SIZE] for t in latency.TABLES)
    gpu_d, cpu_d = (lat.nullpii(t, "default")[CHART_SIZE] for t in latency.TABLES)
    return ("**Partial presets cost an extra model pass.** A preset that masks secrets but leaves readable a category"
            " the agent default masks (the secrets-only preset, `/pii allow url`) runs a second model pass, prompted"
            " with the labels the preset masks, wherever the first pass or a recognizer found something, or a word"
            " was too long to read (`src/secret-pass.ts`); the"
            " agent default and every category masked run one. Timed in the same session with the secrets-only"
            f" preset, nullpii took {ms(gpu)} ms at 30,000 characters on GPU and {ms(cpu)} ms on CPU,"
            f" {gpu / gpu_d:.1f} and {cpu / cpu_d:.1f} times its agent default's ({ms(gpu_d)} ms and {ms(cpu_d)} ms).")


def method(lat: Latency) -> str:
    n, t = lat.nullpii_timing, lat.tools_timing
    model = {r["model"] for r in n["runs"]}
    if len(model) != 1:
        raise LatencyError("latency: nullpii's runs timed more than one model")
    m = lat.machine("gpu")
    if lat.machine("cpu") != m:
        raise LatencyError("latency: the GPU and CPU tables were timed on different machines; the text names one")
    node = {r["node"] for r in n["runs"]}
    return "\n".join([
        f"- **Machine:** {m['os']}, {m['gpu']} and {m['cpu']}, idle.",
        f"- **nullpii:** timed on {date(n['date'])} with {_build(lat)}, the model `{model.pop()}`, onnxruntime-node"
        f" {n['onnxruntime_node']} and Node {listing(sorted(node))} (`{n['timer']}`, texts from commit"
        f" `{n['corpus_commit']}`). {_runs(lat)}",
        f"- **Every other tool:** timed on {date(t['date'])} on the same machine (`{t['timer']}`, the same texts,"
        f" from commit `{t['corpus_commit']}`), each at its default operating point.",
        f"- **Plans:** on GPU, {texts(lat, 'gpu')}, {rounds(lat, 'gpu')}; the table shows the median of the rounds'"
        f" medians. On CPU, {texts(lat, 'cpu')}, {rounds(lat, 'cpu')}; the table shows their median.",
        "",
        _partial(lat),
        "",
        f"The times, with what each row timed, are in [`published-bench/latency/latency.json`]({LATENCY_FILE});"
        " nullpii's runs keep the harness's aggregates and no text.",
    ])


def limit(lat: Latency) -> str:
    return ("- Latency depends on hardware and load. Every tool is timed on the same idle machine and texts, but"
            " nullpii and the other tools were not timed in one session: nullpii on"
            f" {date(lat.nullpii_timing['date'])}, the other tools on {date(lat.tools_timing['date'])}.")
