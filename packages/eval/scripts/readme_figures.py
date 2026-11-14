# SPDX-License-Identifier: Apache-2.0
"""Draw the README's figures as SVG from the published numbers, so no figure
is drawn by hand.

- `ab1-agent-traffic.svg`: AB-1 component A, leak and keep rate of the rows
  `ab1/render_ab1.py` puts in the README (`published-bench/ab1/scores-ab1-a.json`).
- `r3-documents.svg`: R3 macro char-F2 over the five gated sets and over
  English documents only, each tool at its better row
  (`published-bench/r3/char-r3.json` and `char-r3-en.json`).
- `latency-gpu.svg`: median milliseconds per call at 30,000 characters on
  GPU, from the README's latency table.
- `how-it-works.svg`: the data path; no numbers.

The benchmark pipeline (`bench_pipeline.py render`) draws them with the
docs, from `published-bench/`; this script's own run does the same.

Each file carries its light and dark colours and follows the reader's
`prefers-color-scheme`. nullpii's rows carry its logo mark
(`assets/readme/logo-mark.png`, the logo cropped to its glyph and scaled to
64 px), embedded once per file, since a README image cannot load others.

  python packages/eval/scripts/readme_figures.py [--out assets/readme]
"""
from __future__ import annotations

import argparse
import base64
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOGO_MARK = ROOT / "assets" / "readme" / "logo-mark.png"
LOGO_SIZE = 18
# The mark sits at the start of nullpii's highlighted row, a fixed column:
# labels are right-aligned and their width depends on the reader's font.
LOGO_X = 18
sys.path.insert(0, str(Path(__file__).resolve().parent / "ab1"))

import render_ab1  # noqa: E402

FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif'
MONO = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace'
# Light, then dark: GitHub's canvas and ink, nullpii's brand teal (the site's
# and the logo's; `--vp-c-brand-2` on light, `--vp-c-brand-1` on dark) for
# nullpii's bars and the R3 dots, and a grey for the other tools. R3's two
# series share the teal: filled for all five sets, a ring for English only.
LIGHT = {"bg": "#ffffff", "zone": "#f6f8fa", "fg": "#1f2328", "muted": "#59636e", "grid": "#d1d9e0",
         "other": "#818b98", "a": "#0d9488", "band": "#0d948814"}
DARK = {"bg": "#0d1117", "zone": "#151b23", "fg": "#f0f6fc", "muted": "#9198a1", "grid": "#3d444d",
        "other": "#6e7681", "a": "#2dd4bf", "band": "#2dd4bf1f"}
CSS = """
.bg {{ fill: var(--bg); }} .zone {{ fill: var(--zone); stroke: var(--grid); }}
text {{ font-family: {font}; fill: var(--fg); }}
.title {{ font-size: 17px; font-weight: 600; }} .sub {{ font-size: 13px; fill: var(--muted); }}
.ptitle {{ font-size: 14px; font-weight: 600; }} .hint {{ font-size: 12px; font-weight: 400; fill: var(--muted); }}
.label {{ font-size: 13px; }} .np {{ font-weight: 600; }} .val {{ font-size: 12px; font-variant-numeric: tabular-nums; }}
.axis {{ font-size: 11px; fill: var(--muted); font-variant-numeric: tabular-nums; }}
.note {{ font-size: 11.5px; fill: var(--muted); }} .grid {{ stroke: var(--grid); stroke-width: 1; }}
.bar-other {{ fill: var(--other); }} .bar-np {{ fill: var(--a); }} .band {{ fill: var(--band); }}
.dot-a {{ fill: var(--a); stroke: var(--bg); stroke-width: 2; }} .dot-b {{ fill: var(--bg); stroke: var(--a); stroke-width: 2; }}
.link {{ stroke: var(--grid); stroke-width: 2; }}
.box {{ fill: var(--bg); stroke: var(--grid); stroke-width: 1.5; }} .step {{ font-size: 14px; font-weight: 600; }}
.small {{ font-size: 12px; fill: var(--muted); }} .mono {{ font-family: {mono}; font-size: 11.5px; }}
.zlabel {{ font-size: 12px; font-weight: 600; fill: var(--muted); letter-spacing: .04em; }}
.arrow {{ stroke: var(--muted); stroke-width: 1.6; fill: none; }} .head {{ fill: var(--muted); }}
"""


def tokens(colours: dict[str, str]) -> str:
    return " ".join(f"--{k}: {v};" for k, v in colours.items())


def svg(width: int, height: int, title: str, desc: str, body: list[str]) -> str:
    style = (f"svg {{ {tokens(LIGHT)} }}\n@media (prefers-color-scheme: dark) {{ svg {{ {tokens(DARK)} }} }}"
             + CSS.format(font=FONT, mono=MONO))
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-labelledby="t d">',
        f"<title id=\"t\">{esc(title)}</title>", f"<desc id=\"d\">{esc(desc)}</desc>",
        f"<style>{style}</style>",
        f'<rect class="bg" width="{width}" height="{height}" rx="8"/>',
        *body, "</svg>", ""])


def logo_defs() -> str:
    """The logo mark, defined once per file for `logo_mark`."""
    data = base64.b64encode(LOGO_MARK.read_bytes()).decode("ascii")
    return (f'<defs><image id="np-logo" width="{LOGO_SIZE}" height="{LOGO_SIZE}" '
            f'href="data:image/png;base64,{data}"/></defs>')


def logo_mark(row_y: float, row_h: float) -> str:
    """The logo mark at the start of nullpii's row."""
    return f'<use href="#np-logo" x="{LOGO_X}" y="{row_y + (row_h - LOGO_SIZE) / 2:.1f}"/>'


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x: float, y: float, s: str, cls: str, anchor: str = "start") -> str:
    a = "" if anchor == "start" else f' text-anchor="{anchor}"'
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}"{a}>{s}</text>'


def bar(x: float, y: float, w: float, h: float, cls: str, r: float = 4) -> str:
    """A bar anchored at `x`, its data end rounded."""
    if w <= 0:
        return ""
    r = min(r, w, h / 2)
    return (f'<path class="{cls}" d="M{x:.1f},{y:.1f}H{x + w - r:.1f}A{r},{r} 0 0 1 {x + w:.1f},{y + r:.1f}'
            f'V{y + h - r:.1f}A{r},{r} 0 0 1 {x + w - r:.1f},{y + h:.1f}H{x:.1f}Z"/>')


def cells(line: str) -> list[str]:
    return [re.sub(r"[*`]", "", c).strip() for c in line.strip().strip("|").split("|")]


def md_table(md: str, start: str) -> list[dict[str, str]]:
    """The first Markdown table after the line that starts with `start`."""
    lines = md.split("\n")
    i = next(k for k, line in enumerate(lines) if line.startswith(start))
    while not lines[i].startswith("|"):
        i += 1
    head, i = cells(lines[i]), i + 2
    rows = []
    while i < len(lines) and lines[i].startswith("|"):
        rows.append(dict(zip(head, cells(lines[i]))))
        i += 1
    return rows


def ab1_chart(report: dict, nullpii: dict[str, str] | None = None, baseline: str = render_ab1.BASELINE) -> str:
    """`nullpii`: each nullpii row's key and its label in the chart."""
    nullpii = nullpii or {render_ab1.BASELINE: "nullpii 0.5"}
    keys = render_ab1.wanted(report, readme=True, nullpii=nullpii)
    width, row, top, label_x, panel_w = 880, 26, 104, 282, 220
    height = top + len(keys) * row + 58
    panels = [("Leak rate", "lower is better", "leak_rate", 298), ("Keep rate", "higher is better", "keep_rate", 604)]
    docs = report[baseline]["docs"]
    body = [logo_defs(), text(16, 30, "Agent traffic (AB-1, component A)", "title"),
            text(16, 50, f"{docs:,} documents. Each tool at its tuned operating point, with the agent-policy filter.", "sub")]
    bottom = top + len(keys) * row
    for name, hint, _, x0 in panels:
        body.append(f'<text x="{x0}" y="84" class="ptitle">{name} <tspan class="hint">{hint}</tspan></text>')
        for v in (0, 25, 50, 75, 100):
            x = x0 + v / 100 * panel_w
            body += [f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{top - 6}" y2="{bottom}"/>',
                     text(x, bottom + 16, f"{v}%", "axis", "middle")]
    for i, k in enumerate(keys):
        tool = render_ab1.split(k)[0]
        mine = tool in nullpii
        y = top + i * row
        if mine:
            body.append(f'<rect class="band" x="8" y="{y}" width="{width - 16}" height="{row}" rx="4"/>')
        name = chart_name(tool, nullpii)
        body.append(text(label_x, y + row / 2 + 4.5, esc(name), "label np" if mine else "label", "end"))
        if mine:
            body.append(logo_mark(y, row))
        for _, _, key, x0 in panels:
            w = report[k][key] * panel_w
            body.append(bar(x0, y + 6, w, row - 12, "bar-np" if mine else "bar-other"))
            body.append(text(x0 + w + 6, y + row / 2 + 4, f"{100 * report[k][key]:.1f}%", "val np" if mine else "val"))
    body.append(text(16, height - 14, "Intervals, B1 and B2 and every other row: METHOD.md. "
                     "Data: packages/eval/published-bench/ab1/scores-ab1-a.json.", "note"))
    desc = "; ".join(f"{chart_name(render_ab1.split(k)[0], nullpii)}: "
                     f"leak {100 * report[k]['leak_rate']:.1f}%, keep {100 * report[k]['keep_rate']:.1f}%" for k in keys)
    return svg(width, height, "Agent traffic: leak rate and keep rate per tool", desc, body)


def chart_name(tool: str, nullpii: dict[str, str]) -> str:
    return nullpii[tool] if tool in nullpii else render_ab1.NAMES[tool]


R3_STEP = 0.05
# The axis the published chart was drawn on; it widens, by whole steps,
# only when a value falls outside it.
R3_AXIS = (8, 16)


def r3_axis(values: list[float]) -> tuple[float, float, int]:
    """The R3 axis's ends and its number of steps: 0.40 to 0.80, widened to
    the nearest 0.05 below the lowest value and above the highest."""
    low = min(R3_AXIS[0], math.floor(min(values) / R3_STEP + 1e-9))
    high = max(R3_AXIS[1], math.ceil(max(values) / R3_STEP - 1e-9))
    if low < 0 or high * R3_STEP > 1 + 1e-9:
        raise ValueError("an R3 score outside 0 to 1")
    return low * R3_STEP, high * R3_STEP, high - low


def r3_chart(rows: list[tuple[str, float, float, bool]], floor: float) -> str:
    """`rows`: each tool's name, macro char-F2 on the five sets and on
    English documents, and whether it is a nullpii row; `floor`: the
    mask-everything row's macro char-F2."""
    width, row, top, label_x, x0, plot_w = 880, 24, 112, 262, 280, 430
    lo, hi, steps = r3_axis([v for _, a, e, _ in rows for v in (a, e)])
    height = top + len(rows) * row + 58
    bottom = top + len(rows) * row

    def x(v: float) -> float:
        if not lo <= v <= hi:
            raise SystemExit(f"{v} outside the axis")
        return x0 + (v - lo) / (hi - lo) * plot_w

    body = [logo_defs(), text(16, 30, "Documents (R3): macro char-F2", "title"),
            text(16, 50, "Five held-out document sets, frozen before any tool ran. Higher is better; "
                 "each tool at its better operating point.", "sub"),
            f'<circle class="dot-a" cx="{x0 + 6}" cy="76" r="6"/>', text(x0 + 18, 80, "All five sets", "label"),
            f'<circle class="dot-b" cx="{x0 + 136}" cy="76" r="6"/>',
            text(x0 + 148, 80, "English documents only (no clinical notes)", "label"),
            text(790, top - 10, "5 sets", "hint", "end"), text(858, top - 10, "English", "hint", "end")]
    for i in range(steps + 1):
        v = lo + i * R3_STEP
        body += [f'<line class="grid" x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{top - 4}" y2="{bottom}"/>',
                 text(x(v), bottom + 16, f"{v:.2f}", "axis", "middle")]
    for i, (name, all5, english, mine) in enumerate(rows):
        y = top + i * row
        cy = y + row / 2
        if mine:
            body.append(f'<rect class="band" x="8" y="{y}" width="{width - 16}" height="{row}" rx="4"/>')
        cls = "np" if mine else ""
        body += [text(label_x, cy + 4.5, esc(name), f"label {cls}".strip(), "end"),
                 f'<line class="link" x1="{x(all5):.1f}" x2="{x(english):.1f}" y1="{cy}" y2="{cy}"/>',
                 f'<circle class="dot-b" cx="{x(english):.1f}" cy="{cy}" r="5.5"/>',
                 f'<circle class="dot-a" cx="{x(all5):.1f}" cy="{cy}" r="5.5"/>',
                 text(790, cy + 4, f"{all5:.3f}", f"val {cls}".strip(), "end"),
                 text(858, cy + 4, f"{english:.3f}", f"val {cls}".strip(), "end")]
        if mine:
            body.append(logo_mark(y, row))
    body.append(text(16, height - 14, "The datasets, intervals and the table per dataset: METHOD.md. "
                     f"Masking everything scores {floor:.3f}.", "note"))
    desc = "; ".join(f"{n}: {a:.3f} on all five sets, {e:.3f} on English only" for n, a, e, _ in rows)
    return svg(width, height, "Document sets: macro char-F2 per tool", desc, body)


def latency_rows(readme: str) -> list[tuple[str, int]]:
    block = readme.split("<!-- latency:begin -->", 1)[1].split("<!-- latency:end -->", 1)[0]
    return [(r["Tool"], int(r["30k"].replace(",", ""))) for r in md_table(block, "**GPU**")]


def latency_chart(rows: list[tuple[str, int]]) -> str:
    width, row, top, label_x, x0, plot_w, hi = 880, 24, 84, 318, 334, 440, 3000
    height = top + len(rows) * row + 58
    bottom = top + len(rows) * row
    if max(v for _, v in rows) > hi:
        raise SystemExit("latency above the axis")
    body = [logo_defs(), text(16, 30, "Latency on GPU, 30,000 characters", "title"),
            text(16, 50, "Median milliseconds per call, lower is better. RTX 4070 Ti, every tool on the same "
                 "coding-agent texts, after a warm-up.", "sub")]
    for v in range(0, hi + 1, 500):
        xv = x0 + v / hi * plot_w
        body += [f'<line class="grid" x1="{xv:.1f}" x2="{xv:.1f}" y1="{top - 4}" y2="{bottom}"/>',
                 text(xv, bottom + 16, f"{v:,}", "axis", "middle")]
    for i, (name, ms) in enumerate(rows):
        y = top + i * row
        mine = name.startswith("nullpii")
        if mine:
            body.append(f'<rect class="band" x="8" y="{y}" width="{width - 16}" height="{row}" rx="4"/>')
        w = ms / hi * plot_w
        body += [text(label_x, y + row / 2 + 4.5, esc(name), "label np" if mine else "label", "end"),
                 bar(x0, y + 6, w, row - 12, "bar-np" if mine else "bar-other"),
                 text(x0 + w + 6, y + row / 2 + 4, f"{ms:,}", "val np" if mine else "val")]
        if mine:
            body.append(logo_mark(y, row))
    body.append(text(16, height - 14, "CPU, 2,000 and 100,000 characters: the tables below.", "note"))
    desc = "; ".join(f"{n}: {v:,} ms" for n, v in rows)
    return svg(width, height, "GPU latency at 30,000 characters per tool", desc, body)


def box(x: float, y: float, w: float, h: float, heads: list[str], lines: list[str]) -> list[str]:
    """A rounded box: bold heading lines, then small lines, centred."""
    cx = x + w / 2
    out = [f'<rect class="box" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>']
    out += [text(cx, y + 26 + 18 * i, head, "step", "middle") for i, head in enumerate(heads)]
    first = y + 26 + 18 * (len(heads) - 1) + 22
    out += [text(cx, first + 16 * i, line, "small", "middle") for i, line in enumerate(lines)]
    return out


def arrow(d: str) -> str:
    return f'<path class="arrow" d="{d}" marker-end="url(#h)"/>'


def how_it_works() -> str:
    width, height = 880, 340
    body = ['<defs><marker id="h" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            'orient="auto-start-reverse"><path class="head" d="M0,0L10,5L0,10z"/></marker></defs>',
            '<rect class="zone" x="12" y="12" width="682" height="316" rx="10" stroke-dasharray="6 4"/>',
            text(28, 36, "YOUR MACHINE", "zlabel"),
            '<rect class="zone" x="716" y="12" width="152" height="316" rx="10"/>',
            text(732, 36, "LLM PROVIDER", "zlabel")]
    body += box(28, 56, 124, 100, ["Your app or", "Claude Code"], ["prompts, files,", "tool output"])
    body += box(174, 56, 140, 100, ["1  Decode"], ["look-alikes,", "zero-width chars,", "%-encoding, base64"])
    body += box(336, 56, 160, 100, ["2  Detect"], ["GLiNER model", "+ recognizers:", "checksums, key formats"])
    body += box(518, 56, 160, 100, ["3  Mask"], ["mask, ask or readable,", "per category;", "value → placeholder"])
    body += box(518, 200, 160, 76, ["Vault"], ["in memory only,", "value ↔ placeholder"])
    body += box(174, 200, 322, 112, ["4  Restore"], ["your reply: real values back",
                                                     "file tools (Read, Edit, Write): real values",
                                                     "shell commands: placeholders stay"])
    body += [text(792, 120, "sees only", "small", "middle"),
             text(792, 140, "{{PII_PRIVATE_", "mono", "middle"),
             text(792, 156, "EMAIL_0_…}}", "mono", "middle"),
             text(792, 200, "Anthropic, OpenAI", "small", "middle"),
             text(792, 216, "or any model", "small", "middle"),
             text(606, 302, "reply, with placeholders", "small", "middle")]
    body += [arrow("M152,106H172"), arrow("M314,106H334"), arrow("M496,106H516"), arrow("M678,106H714"),
             arrow("M598,156V198"), arrow("M714,286H498"), arrow("M518,238H498"), arrow("M174,256H90V158")]
    desc = ("Text from your app or Claude Code is decoded, scanned by the model and the recognizers, and each "
            "value the policy masks becomes a placeholder kept in an in-memory vault. The LLM provider sees only "
            "placeholders. On the way back the reply gets the real values; file tools get real values; shell "
            "commands keep the placeholders.")
    return svg(width, height, "How nullpii works", desc, body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "readme")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pipeline import render  # the pipeline draws them from published-bench

    figures = render.figures(render.load(render.PUBLISHED_BENCH))
    for name, content in figures.items():
        (args.out / name).write_text(content, encoding="utf-8")
        print(f"{name}: {len(content):,} bytes")


if __name__ == "__main__":
    main()
