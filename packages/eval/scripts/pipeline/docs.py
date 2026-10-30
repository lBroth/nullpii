# SPDX-License-Identifier: Apache-2.0
"""Every rendered region of the tracked docs: which file, which marker,
and the function that writes it from a set of outputs.

A region is a whole Markdown block between `<!-- name:begin -->` and
`<!-- name:end -->`, each on its own line, so the comments never change
how the Markdown around them renders. Static sentences that share a list
with a rendered one are written here too, so the list stays one list;
history (dated re-measurements, the scoring change) is static and is
never rewritten from a new run."""
from __future__ import annotations

from collections.abc import Callable

from pipeline import blocks_ab1 as ab1
from pipeline import blocks_r3 as r3
from pipeline import views
from pipeline.prose import pct

Block = Callable[[views.Bench], str]

# Paths from the repository's root.
README = "README.md"
METHOD = "packages/eval/METHOD.md"
MODEL_CARD = "MODEL_CARD.md"
FIGURES = "assets/readme"
RAW = "https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/"
# Hand-kept data blocks no step renders yet: latency (measured by hand on
# quiet machines; `readme_figures.py` draws its chart from this block).
KEPT = frozenset({"latency"})
ALT_LISTED = 5


# Figures' alternative texts ----------------------------------------------------

def fig_ab1(b: views.Bench) -> str:
    report, labels = b.ab1(ab1.A), ab1.chart_labels(b)
    keys = ab1.render_ab1.wanted(report, readme=True, nullpii=ab1._labels(b, ab1.A))
    last = max(i for i, k in enumerate(keys) if ab1.render_ab1.split(k)[0] in labels)
    listed, rest = keys[:last + 2], keys[last + 2:]

    def item(k: str) -> str:
        tool = ab1.render_ab1.split(k)[0]
        name = labels.get(tool) or ab1.render_ab1.NAMES[tool]
        return f"{name} {pct(report[k]['leak_rate'])} and {pct(report[k]['keep_rate'])}"

    items = [item(k) for k in listed]
    if len(items) > 1:
        items[-1] = "then " + items[-1]
    text = ", ".join(items)
    if len(rest) == 1:
        text += f"; the other tool lets {pct(report[rest[0]]['leak_rate'])} through"
    elif rest:
        leaks = [report[k]["leak_rate"] for k in rest]
        text += f"; every other tool lets {pct(min(leaks))} to {pct(max(leaks))} through"
    docs = report[b.ab1_baseline(ab1.A)]["docs"]
    return (f"![Agent traffic, {docs:,} documents, leak rate and keep rate per tool: {text}. The table below has every"
            f" value.]({RAW}ab1-agent-traffic.svg)")


def fig_r3(b: views.Bench) -> str:
    rows = r3.chart_rows(b)
    last = max(i for i, row in enumerate(rows) if row[3])
    listed = rows[:max(ALT_LISTED, last + 1)]
    text = ", ".join(f"{name} {all5:.3f} and {english:.3f}" for name, all5, english, _ in listed)
    return ("![Documents, macro char-F2 per tool over five sets and over English documents only: "
            f"{text}. The table below has every value.]({RAW}r3-documents.svg)")


# README -------------------------------------------------------------------------

def readme_summary(b: views.Bench) -> str:
    s = ab1.standing(b, ab1.A)
    return "\n".join([
        "- **Built for coding agents.** It masks tool output (files, logs, command output), not only prompts. It keeps"
        " links to code hosts and documentation readable. It never puts a real value into a shell command (see"
        " SECURITY.md). It is built and tested with Claude Code, through the mod (recommended) or the gateway.",
        "- **Works with any model.** Mask before your LLM call and restore after it. Or run the gateway in front of the"
        " Anthropic Messages API or OpenAI Chat Completions. The Codex CLI only speaks the Responses API, so it cannot"
        " use the gateway.",
        f"- **Measured, every result published.** On coding-agent traffic {ab1.rates(s)}. {ab1.fewer_sentence(s)}"
        f" {r3.summary_clause(b)} [Benchmark](#benchmark).",
    ])


AB1_HISTORY = (
    "- **nullpii was measured again after three rules found in end-to-end testing,** added after the first run: a UUID"
    " is an id, not an account number; an IP address is labelled as one, so documentation, private and local addresses"
    " stay readable; \"Claude\" is a product, not a person. They raised its keep rate (A: 81.9% → 85.4%; issues: 69.2%"
    " → 77.2%) and its CredData leak rate (14.6% → 24.5%, the UUIDs above). The other tools' rows are unchanged.\n"
    "- **One scoring rule was changed after the scores were first read, and the change works against nullpii.**"
    " Punctuation left between masked pieces of a value (like the comma between a street and a city) no longer counts"
    " as a leak. With the first rule nullpii led (11.0% against rizzo-pii's 15.0%). The first scoring's files are kept"
    " in the repository's history ([`strict-rule/`](https://github.com/lBroth/nullpii/tree/"
    "230ce9fd1933f5df5263ca9c87d248e064eddc77/packages/eval/published-bench/ab1/strict-rule))."
)


def readme_ab1(b: views.Bench) -> str:
    return ab1.readme_bullets(b) + "\n" + AB1_HISTORY


def readme_matrix(b: views.Bench) -> str:
    return r3.matrix(b) + "\n\n" + r3.matrix_note(b)


# METHOD -------------------------------------------------------------------------

LATENCY_GLANCE = ("| Latency on GPU (RTX 4070 Ti), 30,000 characters | 463 ms; every category masked 489 ms |\n"
                  "| Latency on CPU (Core i7-13700KF), 30,000 characters | 6,984 ms |")


def glance(b: views.Bench) -> str:
    a, b1, b2 = (ab1.standing(b, k) for k in (ab1.A, ab1.B1, ab1.B2))
    return "\n".join([
        f"| What | Result for nullpii {b.version} |",
        "|---|---|",
        f"| Agent traffic (AB-1 A): lets through / keeps readable | {pct(a.me['leak_rate'])} / {pct(a.me['keep_rate'])}"
        f" ({ab1.fewer_aside(a)}) |",
        f"| Agent traffic on CredData (B1) / GitHub issues (B2): lets through | {pct(b1.me['leak_rate'])} /"
        f" {pct(b2.me['leak_rate'])}{ab1.uuid_split(b, ab1.UUID_GLANCE)} |",
        f"| Documents (R3), macro char-F2 over five held-out sets | {r3.glance_documents(b)} |",
        f"| Scored with the PIIMB leaderboard's method | {r3.glance_piimb(b)} |",
        LATENCY_GLANCE,
    ])


def method_coverage_intro(b: views.Bench) -> str:
    return f"{ab1.coverage_counts(b)} (the release build's pack no longer has the UUID recognizer)."


METHOD_UUID = (" On B1, 268 of nullpii's leaks are items CredData labels `UUID`: B1 inherits CredData's labels, and CredData"
               " counts 294 UUIDs as credentials, mostly after keys that name ids (`id`, `uid`, `_postman_id`,"
               " `collectionId`) or after no key; this specification lists UUIDs as text to keep. nullpii lets 268 of"
               " those 294 through, and 222 of B1's other 1,706 secrets (13.0%). As an analysis made after the scores"
               " were read (it changes no published row): with every item of kind `UUID` removed from B1's gold, nullpii"
               " lets 13.0% through (openai privacy-filter 13.6%, nemotron-pii as a library 16.2%).")


def method_rules(b: views.Bench) -> str:
    return (f"On A they leave the leak rate where it was and raise the keep rate: UUIDs kept readable"
            f" {ab1.kept_kind(b, ab1.UUID_KIND)}, reserved addresses (`example.com` and `.test` addresses, `127.0.0.1`,"
            f" `0.0.0.0`, `::1`, documentation IPs) {ab1.kept_kind(b, ab1.RESERVED_KIND)}."
            + ab1.uuid_split(b, METHOD_UUID))


PIIMB_CAVEATS = (
    "- the ai4privacy tasks come from the same family as part of the tuning set;\n"
    "- PIIMB shaped one design decision. An earlier result, on which nullpii missed every category it did not mask"
    " then, is why the five extended categories exist. They were masked by default until 0.5; the 0.5 default for"
    " coding agents leaves them readable. PIIMB has not been used to tune anything."
)


def method_piimb(b: views.Bench) -> str:
    return r3.piimb_method(b) + "\n" + PIIMB_CAVEATS


METHOD_LIMITS = (
    "- Five gated datasets is a small sample of the world, and only English, the main EU languages and Greek are covered.\n"
    "- Gold labels differ in scope between datasets. PIILO labels only students' names, contact details, addresses,"
    " URLs and ids, so another person's name, a date or a place that a tool masks counts against it. Tonic's gold does"
    " not include city, state or postcode, which affects every precision figure on it.\n"
    "- The tuning set is close to nullpii's training distribution and partly to some competitors' (it is used to"
    " choose, never to claim).\n"
    "- Latency depends on hardware and load; it is measured on idle machines, every tool on the same corpus."
)


def method_limits(b: views.Bench) -> str:
    return r3.f05_limit(b) + "\n" + METHOD_LIMITS


def method_lodo(b: views.Bench) -> str:
    return r3.lodo_intro(b) + "\n\n" + r3.lodo_table(b)


# MODEL_CARD ---------------------------------------------------------------------

def card_ab1(b: views.Bench) -> str:
    return ab1.card_traffic_bullet(b) + "\n" + ab1.card_weak_bullet(b)


def card_r3(b: views.Bench) -> str:
    return r3.card_documents(b) + "\n" + r3.recall_bullet(b)


CARD_LIMITS = (
    "- The fine-tuning text is mostly English. The base model covers six languages.\n"
    "- It finds what is written out. It does not infer facts, such as a health condition, from indirect wording.\n"
    "- nullpii replaces values with placeholders that it can reverse. This is pseudonymisation, not anonymisation, and"
    " not a compliance certification."
)


def card_limits(b: views.Bench) -> str:
    s = ab1.standing(b, ab1.A)
    return (f"- It misses some values: {pct(s.me['leak_rate'])} of those that must be hidden on coding-agent traffic"
            " (AB-1). Do not make it your only privacy control.\n" + CARD_LIMITS)


# The registry ---------------------------------------------------------------------

BLOCKS: dict = {
    README: {
        "summary": readme_summary,
        "fig-ab1": fig_ab1,
        "ab1-claims": readme_ab1,
        "ab1-a": ab1.readme_table,
        "fig-r3": fig_r3,
        "r3-claims": r3.readme_bullets,
        "matrix": readme_matrix,
        "r3-configs": r3.configs_paragraph,
        "r3-detail": r3.detail,
    },
    METHOD: {
        "fig-ab1": fig_ab1,
        "fig-r3": fig_r3,
        "glance": glance,
        "ab1-roundtrip": ab1.roundtrip_sentence,
        "ab1-a": ab1.method_table_a,
        "ab1-b1": ab1.method_table(ab1.B1),
        "ab1-b2": ab1.method_table(ab1.B2),
        "ab1-coverage-items": method_coverage_intro,
        "ab1-coverage": ab1.coverage_table,
        "ab1-rules": method_rules,
        "r3-gated": r3.method_table(views.R3_MAIN),
        "r3-reported": r3.method_table(views.R3_REPORTED),
        "r3-en": r3.method_table(views.R3_EN),
        "r3-en-intervals": r3.english_intervals,
        "r3-configs": r3.method_configs,
        "r3-comparisons": r3.comparisons,
        "r3-lodo": method_lodo,
        "r3-sensitivity": r3.sensitivity,
        "piimb": method_piimb,
        "limits": method_limits,
    },
    MODEL_CARD: {
        "card-ab1": card_ab1,
        "card-r3": card_r3,
        "card-limits": card_limits,
    },
}
