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
    "- **One scoring rule was changed after the 0.5 run's scores were first read.** Punctuation left between masked"
    " pieces of a value (like the comma between a street and a city) no longer counts as a leak. The first scoring's"
    " files are kept in the repository's history ([`strict-rule/`](https://github.com/lBroth/nullpii/tree/"
    "230ce9fd1933f5df5263ca9c87d248e064eddc77/packages/eval/published-bench/ab1/strict-rule))."
)


def readme_ab1(b: views.Bench) -> str:
    return ab1.readme_bullets(b) + "\n" + AB1_HISTORY


def readme_matrix(b: views.Bench) -> str:
    return r3.matrix(b) + "\n\n" + r3.matrix_note(b)


# How nullpii's numbers were measured ---------------------------------------------
# The published run measured nullpii on CUDA; a run of the pipeline runs it
# on CPU (score_capture.mjs's backend), on a GitHub-hosted runner when
# bench.yml runs it, and scores every other tool from the published run's
# predictions. The 0.5 run's own checks stay its history.

BENCH_INTRO = ("Every test was fixed before the run, except one AB-1 scoring rule changed afterwards (see below)."
               " Every result is published. How the numbers are made:"
               " [`METHOD.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md).")
CUDA_CPU_AGREEMENT = "37 of the 14,701 tuning-set documents differ"
FP16_CHECK = (
    "The fp16 model that nullpii loads on CUDA by default scored the same macro F2 on these sets as fp32 in the 0.5"
    " run's core regime, which is no longer published (0.7576 against 0.7575), with the same macro recall (0.9577)."
    " It takes 14–15% less time at 30k and 100k characters (463 ms against 537 ms, and 1,650 ms against 1,945 ms;"
    " median per call on the RTX 4070 Ti).")
OPERATING_POINTS = "Competitors run at their default and tuned operating points, and each row shows a tool's better one."
PUBLISHED_MEASURED = (
    "nullpii 0.5 (the release build and the published weights, in fp32), in the configurations it is published in,"
    " measured on CUDA. Its CUDA and CPU outputs agree on all but a few documents in a thousand"
    f" ({CUDA_CPU_AGREEMENT}; release build, fp32 on both). {FP16_CHECK} {OPERATING_POINTS} The rows are from the"
    " release build, which includes the three rules from end-to-end testing described under AB-1; they changed only"
    " documents holding a UUID, an IPv4 address, a loopback host or the word \"Claude\". The CUDA and CPU agreement"
    " above was measured on the build before those rules, and the timings were checked on the release build, which"
    " takes the same time (fp16 459 ms and 1,640 ms, fp32 535 ms and 1,909 ms at 30k and 100k characters).")


def readme_intro(b: views.Bench) -> str:
    if b.names == views.PUBLISHED_NAMES:
        return BENCH_INTRO
    return (f"{BENCH_INTRO} nullpii's rows are a CPU re-measurement of nullpii {b.version} by the benchmark workflow;"
            f" every other tool's rows come from its predictions in the published {views.PUBLISHED_VERSION} run,"
            " which measured nullpii on CUDA.")


def method_measured(b: views.Bench) -> str:
    if b.names == views.PUBLISHED_NAMES:
        return PUBLISHED_MEASURED
    return (
        f"nullpii {b.version} (the build of `main` the benchmark workflow measured, with the published weights in"
        " fp32), in the configurations it is published in, re-measured on CPU on a GitHub-hosted runner by the"
        " benchmark pipeline ([`packages/eval/README.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/"
        f"README.md#benchmark-workflow)). Every other tool's rows are scored from its predictions in the published"
        f" {views.PUBLISHED_VERSION} run, on the same documents. That run measured nullpii on CUDA, and nullpii's CUDA"
        " and CPU outputs agreed then on all but a few documents in a thousand"
        f" ({CUDA_CPU_AGREEMENT}; fp32 on both, on the build before the three rules from end-to-end testing described"
        f" under AB-1). {FP16_CHECK} {OPERATING_POINTS}")


# Where nullpii's rows come from ---------------------------------------------------
# The published 0.5 run measured the release build; a run of the pipeline
# measures the build it names (b.measured). Each paragraph keeps its text
# around the sentence that says which.

AB1_INTRO = ("AB-1 checks two things in a coding agent's traffic. What the agent must not give to the model (secrets, contact details and addresses, ids and account numbers, names) should be masked. What it needs to read (dates, versions, paths, hostnames of public services, placeholders, code identifiers) should stay readable. Each item is scored: the leak rate on items that must be hidden, and the keep rate on items that must stay readable. There is no combined score. Every tool ran on the frozen test set, and the run was redone once for every tool after an adapter fix; ", ' Method and limits: [AB-1 in METHOD.md](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md#agent-traffic-benchmark-ab-1).')
AB1_INTRO_PUBLISHED = "nullpii's rows are from the release build, which includes three rules found in end-to-end testing (below)."
AB1_INTRO_RUN = "nullpii's rows are a CPU re-measurement of nullpii {v} by the benchmark pipeline, a build with three rules found in end-to-end testing (below)."

R3_INTRO = ("R3 measures document anonymisation, a different job from agent traffic. It uses five datasets, frozen before any tool ran on them: REDACT, TonicAI's human-annotated Privacy-Bench, PIILO student essays, Greek and German clinical notes, and a synthetic coding-agent trace set built for this benchmark from a specification we wrote. Each has under 1% measured overlap with nullpii's training data and with the public training sets the other tools declare (three declared sources, among them rizzo-pii's Italian sets, were not compared). The score is per character and ignores labels. F2 counts recall twice as much as precision, because a missed character leaks. ", '')
R3_INTRO_PUBLISHED = 'nullpii\'s rows are from the release build, with the three rules described under AB-1; they changed only documents that hold a UUID, an IP address, a loopback host or the word "Claude".'
R3_INTRO_RUN = "nullpii's rows are a CPU re-measurement of nullpii {v} by the benchmark pipeline, a build with the three rules described under AB-1."

AB1_RESULTS_INTRO = ("Every tool ran on the frozen sets; the tables use the run redone after the adapter fix, scored with the corrected rule. Rows are sorted by leak rate, then by keep rate. Intervals are paired bootstrap 95% intervals of nullpii minus the tool, in percentage points: a negative leak difference or a positive keep difference favours nullpii. In the main tables, bold marks nullpii's name and the best leak rate, keep rate and docs-with-a-leak value of the rows shown. The aggregates are in [`published-bench/ab1/`](https://github.com/lBroth/nullpii/blob/main/packages/eval/published-bench/ab1). ", '')
AB1_RESULTS_INTRO_PUBLISHED = "nullpii's rows are from the release build, which includes the three rules described at the end of these results."
AB1_RESULTS_INTRO_RUN = "nullpii's rows are a CPU re-measurement of nullpii {v} by the benchmark pipeline (see the R3 results), a build with the three rules described at the end of these results."


def readme_ab1_intro(b: views.Bench) -> str:
    said = AB1_INTRO_PUBLISHED if b.names == views.PUBLISHED_NAMES else AB1_INTRO_RUN.format(v=b.version)
    return AB1_INTRO[0] + said + AB1_INTRO[1]


def readme_r3_intro(b: views.Bench) -> str:
    said = R3_INTRO_PUBLISHED if b.names == views.PUBLISHED_NAMES else R3_INTRO_RUN.format(v=b.version)
    return R3_INTRO[0] + said + R3_INTRO[1]


def method_ab1_intro(b: views.Bench) -> str:
    said = AB1_RESULTS_INTRO_PUBLISHED if b.names == views.PUBLISHED_NAMES else AB1_RESULTS_INTRO_RUN.format(v=b.version)
    return AB1_RESULTS_INTRO[0] + said + AB1_RESULTS_INTRO[1]


# METHOD -------------------------------------------------------------------------

# Timed by hand on nullpii 0.5, whatever version the other rows measured.
LATENCY_GLANCE = ("| Latency of nullpii 0.5 (timed by hand) on GPU (RTX 4070 Ti), 30,000 characters | 463 ms; every"
                  " category masked 489 ms |\n"
                  "| Latency of nullpii 0.5 (timed by hand) on CPU (Core i7-13700KF), 30,000 characters | 6,984 ms |")


def glance(b: views.Bench) -> str:
    a, b1, b2 = (ab1.standing(b, k) for k in (ab1.A, ab1.B1, ab1.B2))
    return "\n".join([
        f"| What | Result for nullpii {b.version} |",
        "|---|---|",
        f"| Agent traffic (AB-1 A): lets through / keeps readable | {pct(a.me['leak_rate'])} / {pct(a.me['keep_rate'])}"
        f" ({ab1.fewer_aside(a)}) |",
        f"| Agent traffic on CredData (B1) / GitHub issues (B2): lets through | {pct(b1.me['leak_rate'])} /"
        f" {pct(b2.me['leak_rate'])}{ab1.uuid_glance(b)} |",
        f"| Documents (R3), macro char-F2 over five held-out sets | {r3.glance_documents(b)} |",
        f"| Scored with the PIIMB leaderboard's method | {r3.glance_piimb(b)} |",
        LATENCY_GLANCE,
    ])


def method_coverage_intro(b: views.Bench) -> str:
    return f"{ab1.coverage_counts(b)} (the release build's pack no longer has the UUID recognizer)."


def method_rules(b: views.Bench) -> str:
    return (f"On A they leave the leak rate where it was and raise the keep rate: UUIDs kept readable"
            f" {ab1.kept_kind(b, ab1.UUID_KIND)}, reserved addresses (`example.com` and `.test` addresses, `127.0.0.1`,"
            f" `0.0.0.0`, `::1`, documentation IPs) {ab1.kept_kind(b, ab1.RESERVED_KIND)}."
            + ab1.uuid_method(b))


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
        "bench-intro": readme_intro,
        "summary": readme_summary,
        "ab1-intro": readme_ab1_intro,
        "r3-intro": readme_r3_intro,
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
        "ab1-results-intro": method_ab1_intro,
        "ab1-a": ab1.method_table_a,
        "ab1-b1": ab1.method_table(ab1.B1),
        "ab1-b2": ab1.method_table(ab1.B2),
        "ab1-coverage-items": method_coverage_intro,
        "ab1-coverage": ab1.coverage_table,
        "ab1-rules": method_rules,
        "results-measured": method_measured,
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
