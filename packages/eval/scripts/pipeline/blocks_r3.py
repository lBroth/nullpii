# SPDX-License-Identifier: Apache-2.0
"""The rendered blocks about R3 and PIIMB: METHOD's tables, the README's
matrix, and every sentence that states a number, a rank or a claim.

Which rows: each other tool at its best-F2 row of the report, `(default)`
where that is its default; nullpii in each configuration measured now
(`settings.PRESETS`), never the published core regime. The README's
matrix and the ranks the README and the model card state count NVIDIA's
two nemotron pipelines as one tool (`views.TOOL_GROUPS`); METHOD's tables
show both. An interval, a "significantly" or an S2 claim is read only
from intervals against a configuration measured now: the published
run's are against its core regime, so its outputs render none."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pipeline import compare, settings, views
from pipeline.blocks_ab1 import render_ab1
from pipeline.prose import f3, interval, listing, number, ordinal, refuse, signed, tools

SET_NAMES = {
    "r3-redact": "REDACT", "r3-tonic-human": "Tonic", "r3-piilo": "PIILO", "r3-eu-clinical": "eu-clinical",
    "r3-traces-v3": "traces-v3", "r3-redactionbench": "RedactionBench", "r3-mama-deid-val": "mama-deid",
    "r3-traces-v3-nodistract": "traces-v3, distractors ignored",
}
R3_NAMES = {**render_ab1.NAMES, **views.R3_NAMES_OVERRIDE}
MATRIX_NAMES = {**render_ab1.NAMES, **views.MATRIX_NAMES_OVERRIDE}
CONFIG_WORDS = {"default": "in its agent default", "everything": "with every category masked"}
PIIMB_CONFIG = {"default": "nullpii's agent default", "everything": "nullpii with every category masked, the default before 0.5"}
TASK_NAMES = {"ai4privacy-en": "ai4privacy-en", "ai4privacy-multi": "ai4privacy-multilingual", "nemotron-pii": "nemotron-pii",
              "gretel": "Gretel", "privy": "privy", "mapa-eur-lex": "mapa-eur-lex"}
LODO_LISTED = 3
RANGE_DASH = "–"
NO_INTERVALS = ("The published run's paired intervals are against nullpii's core regime, which is no longer published,"
                " so none is given here; a run of the pipeline gives them against the agent default.")
BONFERRONI_SHOWN = f"{settings.bonferroni_level():.2f}%"


def config_words(name: str) -> str:
    return CONFIG_WORDS[views.preset_of(name)]


ABSENT = "—"


def bold_best(cells: list[str]) -> list[str]:
    """Bold on every cell that prints the column's highest value."""
    values = [float(c) for c in cells if c != ABSENT]
    if not values:
        return cells
    best = f3(max(values))
    return [f"**{c}**" if c == best else c for c in cells]


# Tables ---------------------------------------------------------------------

def _method_rows(b: views.Bench, report: str) -> list[views.Row]:
    rows = [*b.r3_competitors(report, R3_NAMES, grouped=False), *b.r3_nullpii(report), b.r3_mask_all(report)]
    return sorted(rows, key=lambda r: (-r.f2, r.label))


def _label(row: views.Row) -> str:
    return f"**{row.label}**" if row.nullpii else row.label


def method_table(report: str) -> Callable[[views.Bench], str]:
    """A METHOD table: char-F2 per set, macro and leave-one-out range;
    bold marks nullpii's names and the best value of each value column."""
    def block(b: views.Bench) -> str:
        sets = list(b.r3_sets(report))
        rows = _method_rows(b, report)
        columns = [[f3(r.sets[d]["f2"]) if d in r.sets else ABSENT for r in rows] for d in sets]
        columns.append([f3(r.f2) for r in rows])
        bolded = [bold_best(col) for col in columns]
        lines = ["| Tool | " + " | ".join(SET_NAMES[d] for d in sets) + " | Macro | LODO |",
                 "|---|" + "---:|" * (len(sets) + 2)]
        for i, r in enumerate(rows):
            low, high = r.macro[compare.R3_LODO_RANGE]
            cells = [col[i] for col in bolded]
            lines.append(f"| {_label(r)} | " + " | ".join(cells) + f" | {f3(low)}{RANGE_DASH}{f3(high)} |")
        return "\n".join(lines)
    return block


MATRIX_FIELDS = ("f2", "f05", "recall", "precision")


def matrix_rows(b: views.Bench, report: str = views.R3_MAIN) -> list[views.Row]:
    rows = [*b.r3_competitors(report, MATRIX_NAMES, grouped=True), *b.r3_nullpii(report)]
    return sorted(rows, key=lambda r: (-r.f2, r.label))


def _ci_cell(b: views.Bench, report: str, row: views.Row) -> str:
    baseline = b.r3_baseline(report)
    if baseline is None or row.nullpii == baseline:
        return "—"
    return interval(row.macro[compare.R3_INTERVAL])


def matrix(b: views.Bench) -> str:
    rows = matrix_rows(b)
    columns = [[f3(r.value(f)) for r in rows] for f in MATRIX_FIELDS]
    bolded = [bold_best(col) for col in columns]
    lines = ["| Tool | Macro char-F2 | F0.5 | Recall | Precision | CI of nullpii − tool (F2) |",
             "|---|---:|---:|---:|---:|---|"]
    for i, r in enumerate(rows):
        lines.append(f"| {_label(r)} | " + " | ".join(col[i] for col in bolded) + f" | {_ci_cell(b, views.R3_MAIN, r)} |")
    lines.append(f"| {views.MASK_ALL_NAME} | {f3(b.r3_mask_all(views.R3_MAIN).f2)} | | | | |")
    return "\n".join(lines)


def matrix_note(b: views.Bench) -> str:
    baseline = b.r3_baseline(views.R3_MAIN)
    head = "Bold marks nullpii's name and the best value in each column."
    if baseline is None:
        return f"{head} {NO_INTERVALS}"
    return f"{head} The intervals are of {b.label(baseline)} minus each tool."


def chart_rows(b: views.Bench) -> list[tuple[str, float, float, bool]]:
    """The R3 chart's rows: the gated table's, without the floor, each
    with its English macro (the tool's best-F2 row there)."""
    english = {views.tool_of(r.key): r.f2 for r in b.r3_competitors(views.R3_EN, R3_NAMES, grouped=False)}
    english |= {r.nullpii: r.f2 for r in b.r3_nullpii(views.R3_EN)}
    out = []
    for r in _method_rows(b, views.R3_MAIN):
        if r.key == compare.MASK_ALL_ROW:
            continue
        if r.nullpii:
            out.append((b.chart_label(r.nullpii), r.f2, english[r.nullpii], True))
        else:
            out.append((R3_NAMES[views.tool_of(r.key)], r.f2, english[views.tool_of(r.key)], False))
    return out


def chart_floor(b: views.Bench) -> float:
    return b.r3_mask_all(views.R3_MAIN).f2


# Places ---------------------------------------------------------------------

@dataclass(frozen=True)
class Place:
    rank: int
    of: int
    ahead: list[views.Row]

    @property
    def words(self) -> str:
        return f"{ordinal(self.rank)} of {self.of}"


def place(rows: list[views.Row], me: views.Row, field: str = "f2") -> Place:
    """nullpii's row among the other tools' rows by `field`, 1 the highest."""
    others = [r for r in rows if not r.nullpii]
    ahead = sorted((r for r in others if r.value(field) > me.value(field)), key=lambda r: -r.value(field))
    return Place(views.rank(me.value(field), [r.value(field) for r in others]), len(others) + 1, ahead)


def _me(b: views.Bench, report: str, name: str) -> views.Row:
    for r in b.r3_nullpii(report):
        if r.nullpii == name:
            return r
    raise refuse(f"nullpii's place in {report}", f"{name} has no row there")


def matrix_place(b: views.Bench, name: str, report: str = views.R3_MAIN, field: str = "f2") -> Place:
    return place(matrix_rows(b, report), _me(b, report, name), field)


def _plain(row: views.Row) -> str:
    """A row's name in a sentence, where a number in brackets follows."""
    if row.label.endswith(views.DEFAULT_MARK):
        return row.label.removesuffix(views.DEFAULT_MARK) + " at its default"
    return row.label


def _ahead_sentence(p: Place, me: views.Row) -> str:
    if not p.ahead:
        return "No other tool scores higher."
    if len(p.ahead) == 1:
        return f"{_plain(p.ahead[0])} is ahead ({f3(p.ahead[0].f2)} against {f3(me.f2)})."
    return (f"{number(len(p.ahead)).capitalize()} tools are ahead, from {_plain(p.ahead[0])} ({f3(p.ahead[0].f2)})"
            f" to {_plain(p.ahead[-1])} ({f3(p.ahead[-1].f2)}).")


def _signs(b: views.Bench, report: str, rows: list[views.Row]) -> dict[str, list[views.Row]] | None:
    """The other tools of `rows` by the sign of the macro F2 interval of
    the baseline minus each, or None when the report's baseline is no
    configuration measured now."""
    baseline = b.r3_baseline(report)
    if baseline is None:
        return None
    claims = compare.r3_claims(b.o)[0]
    out: dict[str, list[views.Row]] = {compare.AHEAD: [], compare.CLOSE: [], compare.BEHIND: []}
    for r in rows:
        if not r.nullpii:
            out[claims[f"R3 {report} · {baseline} against {r.key} (F2)"]].append(r)
    return out


def _sign_counts(signs: dict[str, list[views.Row]]) -> str:
    def named(rows: list[views.Row]) -> str:
        return f"{len(rows)}, {listing([_plain(r) for r in rows])}," if 0 < len(rows) <= LODO_LISTED else str(len(rows))
    return (f"significantly ahead of {named(signs[compare.AHEAD])}, too close to call with "
            f"{named(signs[compare.CLOSE])} and significantly behind {named(signs[compare.BEHIND])}")


def interval_bullet(b: views.Bench) -> str:
    rows = matrix_rows(b)
    signs, corrected = _signs(b, views.R3_MAIN, rows), _signs(b, views.R3_BONFERRONI, matrix_rows(b, views.R3_BONFERRONI))
    if signs is None or corrected is None:
        return ""
    baseline = b.r3_baseline(views.R3_MAIN)
    others = len(rows) - len(b.r3_nullpii(views.R3_MAIN))
    return (f"- **Paired intervals** of {b.label(baseline)} minus each other tool ({tools(others)}), macro"
            f" char-F2, 95% (the test fixed before the run): {_sign_counts(signs)}. With the Bonferroni correction added"
            f" later ({BONFERRONI_SHOWN}): {_sign_counts(corrected)}.")


def _recall_words(p: Place) -> str:
    if p.rank == 1:
        return f"is the highest of {p.of}"
    if p.rank == p.of:
        return f"is the lowest of {p.of}"
    return f"ranks {p.words}"


def _second_words(p: Place) -> str:
    if p.rank == 1:
        return "the highest"
    if p.rank == p.of:
        return "the lowest"
    return ordinal(p.rank)


def recall_bullet(b: views.Bench) -> str:
    name = b.headline
    me = _me(b, views.R3_MAIN, name)
    recall, precision = matrix_place(b, name, field="recall"), matrix_place(b, name, field="precision")
    f05 = matrix_place(b, name, field="f05")
    if recall.rank < precision.rank:
        head = "It favours recall"
    elif recall.rank > precision.rank:
        head = "It favours precision"
    else:
        head = "Recall and precision"
    return (f"- **{head}.** {config_words(name).capitalize()}, its macro recall ({f3(me.mean('recall'))})"
            f" {_recall_words(recall)} at each tool's best-F2 row, and its precision ({f3(me.mean('precision'))})"
            f" {_second_words(precision)}. Ranked by F0.5, which favours precision, it is {ordinal(f05.rank)}.")


def rank_bullets(b: views.Bench) -> list[str]:
    out = []
    for me in b.r3_nullpii(views.R3_MAIN):
        p = place(matrix_rows(b), me)
        out.append(f"- **{ordinal(p.rank).capitalize()} of {p.of}** by macro char-F2 {config_words(me.nullpii)}"
                   f" ({f3(me.f2)}; counting NVIDIA's two nemotron pipelines as one tool, the chart shows both)."
                   f" {_ahead_sentence(p, me)}")
    return out


def english_bullet(b: views.Bench) -> str:
    parts = []
    for me in b.r3_nullpii(views.R3_EN):
        p = matrix_place(b, me.nullpii, views.R3_EN)
        parts.append(f"{config_words(me.nullpii)}, {p.words} ({f3(me.f2)})")
    return "- **English documents only:** " + "; ".join(parts) + "."


def _piimb_place(at: dict, listed: str = "the") -> str:
    if at["rank"] == 1:
        return f"above {listed} {at['of'] - 1} listed tools"
    return f"{ordinal(at['rank'])} of {at['of']} on the leaderboard"


def piimb_bullets(b: views.Bench) -> list[str]:
    out = []
    for name, r in b.piimb().items():
        rest = r["without"]
        out.append(f"- **PIIMB**, scored by us with the leaderboard's method (not a submitted entry), {config_words(name)}:"
                   f" average F2 {f3(r['avg_f2'])}, {_piimb_place(r['leaderboard'])}. Without the one task from its"
                   f" training family it is {f3(rest['avg_f2'])}, {_piimb_place(rest['leaderboard'])}; the leaderboard"
                   " gives no intervals.")
    return out


def readme_bullets(b: views.Bench) -> str:
    bullets = [*rank_bullets(b), interval_bullet(b), english_bullet(b), recall_bullet(b), *piimb_bullets(b)]
    return "\n".join(x for x in bullets if x)


def summary_clause(b: views.Bench) -> str:
    """The README's first lines: nullpii's places on the five sets."""
    parts = []
    for me in b.r3_nullpii(views.R3_MAIN):
        p, en = place(matrix_rows(b), me), matrix_place(b, me.nullpii, views.R3_EN)
        parts.append(f"{config_words(me.nullpii)}, it is {p.words} tools by macro char-F2, and {ordinal(en.rank)} on English"
                     " text alone")
    return "On five held-out document sets, " + "; ".join(parts) + "."


# The README's configurations paragraph and its details ----------------------

FIVE = "organisations, occupations, demographic and sensitive attributes, titles"


def configs_paragraph(b: views.Bench) -> str:
    shown = [f"{views.PRESET_LABELS[views.preset_of(r.nullpii)]} ({f3(r.f2)})" for r in b.r3_nullpii(views.R3_MAIN)]
    text = (f"nullpii is shown in the configurations it is published in: {listing(shown)}. These datasets label dates,"
            f" and not {FIVE}, so masking those five counts as over-masking here.")
    if settings.tool_name("default") not in {r.nullpii for r in b.r3_nullpii(views.R3_MAIN)}:
        text += (" The agent default, which leaves those five categories and dates readable, is not measured on these"
                 " datasets in the outputs published here; agent traffic (AB-1, above) measures it.")
    return text


def _set_counts(b: views.Bench, report: str, name: str) -> str:
    rows = matrix_rows(b, report)
    others = [r for r in rows if not r.nullpii]
    me = _me(b, report, name)
    parts = []
    for d in b.r3_sets(report):
        mine = me.sets[d]["f2"]
        ahead = sum(1 for r in others if d in r.sets and r.sets[d]["f2"] > mine)
        parts.append(f"{SET_NAMES[d]} {ahead if ahead else 'none'}")
    return ", ".join(parts)


def lodo_reports() -> list[tuple[str, str]]:
    return [(f"{compare.LODO_PREFIX}{d}", d) for d in settings.R3_GATED]


def _lodo_places(b: views.Bench, name: str) -> str:
    parts = []
    for report, left_out in lodo_reports():
        me = _me(b, report, name)
        p = place(matrix_rows(b, report), me)
        parts.append(f"without {SET_NAMES[left_out]} {f3(me.f2)} ({ordinal(p.rank)})")
    return ", ".join(parts)


def _english_detail(b: views.Bench, name: str) -> str:
    me = _me(b, views.R3_EN, name)
    p = matrix_place(b, name, views.R3_EN)
    text = f"{ordinal(p.rank).capitalize()} of {p.of} ({f3(me.f2)})"
    if p.ahead:
        shown = p.ahead[:LODO_LISTED]
        more = len(p.ahead) - len(shown)
        text += "; ahead: " + listing([f"{_plain(r)} ({f3(r.f2)})" for r in shown] + ([f"{more} more"] if more else []))
    return text + "."


def _piimb_detail(name: str, r: dict) -> str:
    rest = r["without"]
    tasks = [f"{TASK_NAMES[t]} {ordinal(at['rank'])}" for t, at in r["task_ranks"].items()]
    return (f"- **PIIMB** ([leaderboard](https://huggingface.co/spaces/piimb/pii-masking-benchmark-leaderboard), `sentences`"
            f" subset, scored by us with the leaderboard's method, not a submitted entry, {config_words(name)}): average F2"
            f" {f3(r['avg_f2'])}, {_piimb_place(r['leaderboard'], 'all')}. One of the six tasks, {rest['task']}, comes from"
            " nullpii's training family: 2.5% of its sampled text overlaps nullpii's training data, and 5.2% overlaps"
            f" Nemotron-PII's. Without that task nullpii averages {f3(rest['avg_f2'])}, {_piimb_place(rest['leaderboard'], 'all')}."
            " The leaderboard gives no intervals, so no difference on it can be called significant. Its place on each task,"
            f" of {next(iter(r['task_ranks'].values()))['of']}: {', '.join(tasks)}.")


def detail(b: views.Bench) -> str:
    name = b.headline
    lines = [f"**In detail**, {config_words(name)}.",
             f"- **Per dataset.** Tools ahead on each set, of the {len(matrix_rows(b)) - len(b.r3_nullpii(views.R3_MAIN))}"
             f" others, each at its best-F2 row: {_set_counts(b, views.R3_MAIN, name)}.",
             f"- **Leaving one set out** (macro char-F2, and the place of {matrix_place(b, name).of}):"
             f" {_lodo_places(b, name)}.",
             f"- **English documents only.** {_english_detail(b, name)}"]
    lines += [_piimb_detail(n, r) for n, r in b.piimb().items()]
    return "\n".join(lines)


# METHOD's prose ---------------------------------------------------------------

def _labels_with_intervals(rows: list[views.Row]) -> str:
    return listing([f"{_plain(r)} {interval(r.macro[compare.R3_INTERVAL])}" for r in rows])


def english_intervals(b: views.Bench) -> str:
    rows = matrix_rows(b, views.R3_EN)
    signs = _signs(b, views.R3_EN, rows)
    if signs is None:
        return f"On English documents, {NO_INTERVALS[:1].lower()}{NO_INTERVALS[1:]}"
    label = b.label(b.r3_baseline(views.R3_EN))
    parts = []
    if signs[compare.BEHIND]:
        parts.append(f"{_labels_with_intervals(signs[compare.BEHIND])} {'is' if len(signs[compare.BEHIND]) == 1 else 'are'}"
                     f" significantly ahead of {label} (nullpii minus the tool, 95%)")
    if signs[compare.CLOSE]:
        parts.append(f"{_labels_with_intervals(signs[compare.CLOSE])} {'is' if len(signs[compare.CLOSE]) == 1 else 'are'}"
                     " within the interval")
    parts.append(f"{label} is significantly ahead of {len(signs[compare.AHEAD])}")
    return "On English documents, " + "; ".join(parts) + "."


def method_configs(b: views.Bench) -> str:
    rows = {r.nullpii: r for r in b.r3_nullpii(views.R3_MAIN)}
    parts = [f"nullpii is shown {listing([config_words(n) for n in rows])}."]
    everything = settings.tool_name("everything")
    if everything in rows:
        piilo = rows[everything].sets["r3-piilo"]["f2"]
        parts.append(f"With every category masked (the default before 0.5) it also masks five categories outside the core"
                     f" labels these datasets are scored on ({FIVE}); counted on everything it masks, it scores"
                     f" {f3(rows[everything].f2)} on the gated sets, {f3(piilo)} on PIILO.")
    default = settings.tool_name("default")
    if default in rows:
        parts.append("The agent default (`DEFAULT_DISABLED_CATEGORIES`) leaves those five categories and dates readable;"
                     " the core labels count dates, so a date it leaves readable counts as missed.")
    else:
        parts.append("The default nullpii now ships for coding agents leaves those five categories and dates readable"
                     " (`DEFAULT_DISABLED_CATEGORIES`). The outputs published here do not measure it on these sets; the"
                     " agent-traffic benchmark above measures it.")
    return " ".join(parts)


def s2_sentence(b: views.Bench) -> str:
    """r2_verdict's S2 on the gated verdict's report, from compare's claims:
    a tool row with significantly higher recall at a precision not
    significantly lower, on any set, is named."""
    baseline = b.r3_baseline(views.R3_MAIN)
    if baseline is None:
        return ""
    claims = compare.verdict_claims(b.o)
    breaches: dict[str, list[str]] = {}
    for dataset, rows in b.r3_sets(views.R3_MAIN).items():
        for key in rows:
            if compare._is_competitor(key):
                where = f"R3 {views.R3_MAIN} · {dataset} · {baseline} against {key} (S2)"
                if claims[where] == compare.S2_BREACH:
                    breaches.setdefault(dataset, []).append(views.r3_label(key, R3_NAMES))
    if not breaches:
        return "No dataset has a tool with significantly higher recall at matched or better precision."
    named = [f"on {SET_NAMES[d]}, {listing(tools)}" for d, tools in breaches.items()]
    return ("A tool has significantly higher recall at a precision not significantly lower (S2): "
            + "; ".join(named) + ".")


def _higher_recall_rows(b: views.Bench, me: views.Row) -> list[str]:
    table = b.r3(views.R3_MAIN)
    out = []
    for key in table[compare.MACRO]:
        if compare._is_competitor(key):
            r = compare._macro_mean(table, key, "recall")
            if r > me.mean("recall"):
                setting = "default" if key.endswith(views.DEFAULT_SUFFIX) else "tuned"
                out.append(f"{R3_NAMES[views.tool_of(key)]} at its {setting} setting reaches {f3(r)}, at a macro"
                           f" char-F2 of {f3(table[compare.MACRO][key]['f2'])}")
    return out


def _f05_best_rank(b: views.Bench, me: views.Row) -> int:
    best = compare._best_rows(b.r3(views.R3_MAIN)[compare.MACRO], "f05")
    return views.rank(me.macro["f05"], list(best.values()))


def comparisons(b: views.Bench) -> str:
    name = b.headline
    rows = [*b.r3_competitors(views.R3_MAIN, R3_NAMES, grouped=False), *b.r3_nullpii(views.R3_MAIN)]
    me = _me(b, views.R3_MAIN, name)
    label = b.label(name)
    parts = ["**Comparisons (gated sets, F2).**"]
    signs = _signs(b, views.R3_MAIN, rows)
    if signs is None:
        parts.append(NO_INTERVALS)
    else:
        corrected = _signs(b, views.R3_BONFERRONI, [*b.r3_competitors(views.R3_BONFERRONI, R3_NAMES, grouped=False),
                                                     *b.r3_nullpii(views.R3_BONFERRONI)])
        others = len(rows) - len(b.r3_nullpii(views.R3_MAIN))
        parts.append(f"On the macro over the five sets, against each other tool ({tools(others)}) at its better row,"
                     f" 95% (the test fixed before the run), {label} is {_sign_counts(signs)}.")
        ahead = sorted(signs[compare.AHEAD], key=lambda r: r.macro[compare.R3_INTERVAL][0])[:2]
        if ahead:
            parts.append(f"The narrowest margins ahead are {_labels_with_intervals(ahead)}.")
        parts.append(f"With {BONFERRONI_SHOWN} intervals (a Bonferroni correction for {settings.BONFERRONI_COMPARISONS}"
                     f" comparisons, added after the run), it is {_sign_counts(corrected)}.")
        parts.append(s2_sentence(b))
    p_recall = place(rows, me, "recall")
    recall = (f"{config_words(name).capitalize()}, nullpii's macro recall ({f3(me.mean('recall'))})"
              f" {_recall_words(p_recall)} at each tool's better row")
    higher = _higher_recall_rows(b, me)
    parts.append(recall + ("; " + "; ".join(higher) if higher else "") + ".")
    f05 = place(rows, me, "f05")
    parts.append(f"At F0.5 it is {ordinal(f05.rank)} on these rows ({tools(f05.rank - 1)} ahead), and"
                 f" {ordinal(_f05_best_rank(b, me))} with each tool at its best F0.5 row.")
    return " ".join(parts)


def lodo_intro(b: views.Bench) -> str:
    with_ci = b.r3_baseline(lodo_reports()[0][0]) == b.headline
    return (f"**Leaving one set out**, nullpii {config_words(b.headline)}. Each set left out in turn (each tool at its"
            f" better row; the tool's score minus nullpii's{', with the paired 95% CI' if with_ci else ''}):")


def _diff(b: views.Bench, report: str, r: views.Row, me: views.Row) -> str:
    text = f"{_plain(r)} {signed(r.f2 - me.f2)}"
    if b.r3_baseline(report) == me.nullpii:
        low, high = r.macro[compare.R3_INTERVAL]
        text += f" {interval([-high, -low])}"
    return text


def lodo_table(b: views.Bench) -> str:
    lines = ["| Left out | nullpii | Tools ahead of nullpii | Closest behind |", "|---|---:|---|---|"]
    for report, left_out in lodo_reports():
        me = _me(b, report, b.headline)
        rows = [r for r in b.r3_competitors(report, R3_NAMES, grouped=False)]
        ahead = sorted((r for r in rows if r.f2 > me.f2), key=lambda r: -r.f2)
        behind = sorted((r for r in rows if r.f2 <= me.f2), key=lambda r: -r.f2)
        if not ahead:
            ahead_cell = "none"
        elif len(ahead) <= LODO_LISTED:
            ahead_cell = ", ".join(_diff(b, report, r, me) for r in ahead)
        else:
            ahead_cell = f"{len(ahead)} tools; the nearest, {_diff(b, report, ahead[-1], me)}"
        behind_cell = _diff(b, report, behind[0], me) if behind else "none"
        lines.append(f"| {SET_NAMES[left_out]} | {f3(me.f2)} | {ahead_cell} | {behind_cell} |")
    return "\n".join(lines)


def _docs(b: views.Bench, report: str, key: str) -> int:
    return sum(rows[key]["docs"] for rows in b.r3_sets(report).values() if key in rows)


def _sensitivity_result(b: views.Bench, report: str) -> str:
    me = _me(b, report, b.headline)
    rows = [*b.r3_competitors(report, R3_NAMES, grouped=False), me]
    main_rows = [*b.r3_competitors(views.R3_MAIN, R3_NAMES, grouped=False), _me(b, views.R3_MAIN, b.headline)]
    signs, main = _signs(b, report, rows), _signs(b, views.R3_MAIN, main_rows)
    if signs is None or main is None:
        return f"macro char-F2 {f3(me.f2)}"
    def by_tool(found: dict[str, list[views.Row]]) -> dict[str, str]:
        return {r.label: sign for sign, rs in found.items() for r in rs}
    now, before = by_tool(signs), by_tool(main)
    moved = sorted(t for t in now.keys() & before.keys() if now[t] != before[t])
    return "conclusions unchanged" if not moved else f"the interval's sign changes against {listing(moved)}"


def sensitivity(b: views.Bench) -> str:
    excluded = "sens-openmed-excluded"
    me_key = _me(b, views.R3_MAIN, b.headline).key
    gone = _docs(b, views.R3_MAIN, me_key) - _docs(b, excluded, me_key)
    lines = [f"**Sensitivity checks**, nullpii {config_words(b.headline)}. They are reported, and none decides. Both"
             " include NVIDIA's server row:",
             f"- without the documents any OpenMed row returned no output for ({gone} gated documents, for every tool):"
             f" {_sensitivity_result(b, excluded)};",
             f"- every set resampled by its recorded clusters: {_sensitivity_result(b, 'sens-cluster-rows')}."]
    if b.r3_baseline(views.R3_MAIN) is None:
        lines.append("")
        lines.append(NO_INTERVALS)
    return "\n".join(lines)


def piimb_method(b: views.Bench) -> str:
    out = []
    for name, r in b.piimb().items():
        preset = views.preset_of(name)
        tasks = ", ".join(f"{TASK_NAMES[t]} {f3(s['f2'])}" for t, s in r["tasks"].items())
        out.append(f"**PIIMB** (`sentences` subset, 150,022 texts; {PIIMB_CONFIG[preset]}), scored by us with the"
                   " leaderboard's method (`scripts/ab/piimb_score.py`), not a submitted entry: average F2"
                   f" {f3(r['avg_f2'])}, {_piimb_place(r['leaderboard'], 'all')}. nullpii's F2 per task: {tasks}."
                   " These are the release build's. Caveats:")
        rest = r["without"]
        out.append(f"- the {rest['task']} task is in nullpii's training family (2.5% of its sampled text overlaps"
                   " nullpii's training corpus, 5.2% overlaps Nemotron-PII's); without it nullpii averages"
                   f" {f3(rest['avg_f2'])}, {_piimb_place(rest['leaderboard'], 'all')}, and the leaderboard gives no"
                   " intervals;")
    return "\n".join(out)


def f05_limit(b: views.Bench) -> str:
    name = b.headline
    p = matrix_place(b, name, field="f05")
    return (f"- F2 rewards over-masking. At F0.5, {p.rank - 1} of the {p.of - 1} other tools rank above"
            f" {b.label(name)}, each at its best-F2 row.")


def card_documents(b: views.Bench) -> str:
    parts = []
    for me in b.r3_nullpii(views.R3_MAIN):
        p = place(matrix_rows(b), me)
        first = f"; the first is {_plain(p.ahead[0])} ({f3(p.ahead[0].f2)})" if p.ahead else ""
        en = matrix_place(b, me.nullpii, views.R3_EN)
        en_me = _me(b, views.R3_EN, me.nullpii)
        parts.append(f"{config_words(me.nullpii)}, nullpii is {p.words} tools (macro char-F2 {f3(me.f2)}{first}); on"
                     f" English documents alone it is {ordinal(en.rank)} ({f3(en_me.f2)})")
    return "- **Documents (five held-out sets):** " + "; ".join(parts) + "."


def glance_documents(b: views.Bench) -> str:
    parts = []
    for me in b.r3_nullpii(views.R3_MAIN):
        p = place(matrix_rows(b), me)
        en = _me(b, views.R3_EN, me.nullpii)
        top = f" ({p.ahead[0].label.removesuffix(views.DEFAULT_MARK)} {f3(p.ahead[0].f2)})" if p.ahead else ""
        parts.append(f"{f3(me.f2)} {config_words(me.nullpii)}, {p.words}{top}; English only {f3(en.f2)}")
    return "; ".join(parts)


def glance_piimb(b: views.Bench) -> str:
    return "; ".join(f"{f3(r['avg_f2'])} average F2 ({views.PRESET_LABELS[views.preset_of(n)]})" for n, r in b.piimb().items())

