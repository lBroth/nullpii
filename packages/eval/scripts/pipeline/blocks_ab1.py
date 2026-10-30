# SPDX-License-Identifier: Apache-2.0
"""The rendered blocks about AB-1: its tables (`ab1/render_ab1.py`), and
every sentence that states a number or a claim about it.

Each claim is about nullpii's row the intervals are against (the agent
default), among each other tool's README row (tuned, `+agent`), as
`compare.ab1_ranks` ranks it. The split of CredData's leaks into UUIDs
and other secrets is in no output (`compare.NOT_COMPARED`): it is the
published run's own analysis, so it is printed for the published outputs
only, never next to another run's numbers."""
from __future__ import annotations

import sys
from dataclasses import dataclass

from pipeline import compare, settings, views
from pipeline.prose import listing, number, pct, refuse, verb

sys.path.insert(0, str(settings.SCRIPTS / "ab1"))

import render_ab1  # noqa: E402

A, B1, B2 = "ab1-a", "ab1-b1", "ab1-b2"
# The prose names a tool as the tables do, but for this one.
PROSE_NAMES = {"openai-privacy-filter": "openai's privacy-filter"}
# Each category as the prose names it, and in short after the first time.
CATEGORIES = {
    "person": ("person names", "names"), "url": ("URLs", "URLs"), "account": ("account numbers", "accounts"),
    "address": ("addresses", "addresses"), "ip": ("IP addresses", "IPs"), "mac": ("MAC addresses", "MACs"),
    "secret": ("secrets", "secrets"), "email": ("emails", "emails"), "phone": ("phone numbers", "phones"),
    "card": ("card numbers", "cards"), "iban": ("IBANs", "IBANs"), "national_id": ("national ids", "national ids"),
    "passport": ("passports", "passports"), "driver_license": ("driver's licences", "licences"),
}
WEAKEST = 2
HALF = 0.5
POINTS = 100
# Kinds of items to keep the three end-to-end rules are about.
UUID_KIND, RESERVED_KIND = "uuid", "reserved_address"


def prose_name(key: str) -> str:
    tool = render_ab1.split(key)[0]
    return PROSE_NAMES.get(tool, render_ab1.NAMES[tool])


def table_name(key: str) -> str:
    return render_ab1.NAMES[render_ab1.split(key)[0]]


@dataclass(frozen=True)
class Standing:
    """nullpii's row on one AB-1 set, and every other tool's README row."""

    me: dict
    others: dict[str, dict]
    leak_ci: dict[str, list[float]]
    keep_ci: dict[str, list[float]]

    def _strictly(self, field: str, lower: bool) -> list[str]:
        mine = self.me[field]
        ties = [k for k, r in self.others.items() if r[field] == mine]
        if ties:
            raise refuse(f"a {field} tied with nullpii's", f"{', '.join(ties)}: no wording for a tie")
        found = [k for k, r in self.others.items() if (r[field] < mine if lower else r[field] > mine)]
        return sorted(found, key=lambda k: (self.others[k][field], k), reverse=not lower)

    def fewer(self) -> list[str]:
        """The tools that let fewer items through, fewest first."""
        return self._strictly("leak_rate", lower=True)

    def more(self) -> list[str]:
        return self._strictly("leak_rate", lower=False)

    def keep_as_much(self) -> list[str]:
        """The tools that keep at least as much readable, most first."""
        mine = self.me["keep_rate"]
        found = [k for k, r in self.others.items() if r["keep_rate"] >= mine]
        return sorted(found, key=lambda k: (-self.others[k]["keep_rate"], k))


def standing(b: views.Bench, key: str) -> Standing:
    rows = b.ab1(key)
    others = b.ab1_others(key)
    return Standing(
        rows[b.ab1_baseline(key)], others,
        {k: r["ci"]["baseline_minus_tool_leak"] for k, r in others.items()},
        {k: r["ci"]["baseline_minus_tool_keep"] for k, r in others.items()},
    )


def _labels(b: views.Bench, key: str, chart: bool = False) -> dict[str, str]:
    label = b.chart_label if chart else b.label
    return {k: label(name) for k, name in b.ab1_nullpii(key).items()}


# Tables ---------------------------------------------------------------------

def readme_table(b: views.Bench) -> str:
    return render_ab1.main_table(b.ab1(A), readme=True, nullpii=_labels(b, A), baseline=b.ab1_baseline(A))


def method_table_a(b: views.Bench) -> str:
    nullpii, baseline = _labels(b, A), b.ab1_baseline(A)
    return (render_ab1.main_table(b.ab1(A), readme=False, nullpii=nullpii, baseline=baseline) + "\n\n"
            + render_ab1.secondary(b.ab1(A), nullpii=nullpii, baseline=baseline))


def method_table(key: str):
    def block(b: views.Bench) -> str:
        return render_ab1.main_table(b.ab1(key), readme=False, nullpii=_labels(b, key), baseline=b.ab1_baseline(key))
    return block


def coverage_table(b: views.Bench) -> str:
    reports = {k.removeprefix("ab1-"): b.ab1(k) for k in settings.AB1_GOLD}
    cov = {k.removeprefix("ab1-"): b.ab1_coverage(k) for k in settings.AB1_GOLD}
    return render_ab1.coverage(reports, cov, nullpii=_labels(b, A))


def chart_labels(b: views.Bench) -> dict[str, str]:
    return _labels(b, A, chart=True)


# Sentences ------------------------------------------------------------------

def rates(s: Standing) -> str:
    return (f"it lets {pct(s.me['leak_rate'])} of the values that must be hidden through, and keeps "
            f"{pct(s.me['keep_rate'])} of the values that must stay readable")


def fewer_sentence(s: Standing) -> str:
    """Which tools let fewer through, and what they keep readable."""
    fewer = s.fewer()
    if not fewer:
        return "No other tool lets fewer through."
    if len(fewer) == 1:
        t = s.others[fewer[0]]
        return f"Only {table_name(fewer[0])} lets fewer through ({pct(t['leak_rate'])}), and it keeps {pct(t['keep_rate'])} readable."
    return f"{number(len(fewer)).capitalize()} other tools let fewer through: " + listing(
        [f"{table_name(k)} ({pct(s.others[k]['leak_rate'])})" for k in fewer]) + "."


def fewer_aside(s: Standing) -> str:
    fewer = s.fewer()
    if not fewer:
        return "no other tool lets fewer through"
    if len(fewer) == 1:
        t = s.others[fewer[0]]
        return f"only {table_name(fewer[0])} lets fewer through, {pct(t['leak_rate'])}, keeping {pct(t['keep_rate'])}"
    return f"{number(len(fewer))} other tools let fewer through"


def _gap_phrase(ci: list[float]) -> str:
    claim = compare._claim(ci, ahead_when_positive=False)
    if claim == compare.CLOSE:
        return "the gap is within the margin of error"
    if claim == compare.BEHIND:
        return "the gap is significant"
    raise refuse("a tool that lets fewer through", "its leak interval says nullpii lets significantly fewer through")


def _keep_phrase(row: dict) -> str:
    if row["keep_rate"] < HALF:
        return "it masks more than half of what the agent needs to read"
    return f"it keeps {pct(row['keep_rate'])} of what the agent needs to read"


def _keep_sign(ci: list[float]) -> str:
    claim = compare._claim(ci, ahead_when_positive=True)
    if claim == compare.CLOSE:
        return "too close to call"
    if claim == compare.BEHIND:
        return "significantly more"
    raise refuse("a tool that keeps as much readable", "its keep interval says nullpii keeps significantly more")


def _points(s: Standing, keys: list[str]) -> list[int]:
    return [round(POINTS * (s.others[k]["leak_rate"] - s.me["leak_rate"])) for k in keys]


def lead_bullet(s: Standing) -> str:
    fewer, more = s.fewer(), s.more()
    if not fewer:
        head = "- **No other tool lets fewer through.**"
    elif len(fewer) == 1:
        t = s.others[fewer[0]]
        head = (f"- **Only {table_name(fewer[0])} lets fewer through** ({pct(t['leak_rate'])}; "
                f"{_gap_phrase(s.leak_ci[fewer[0]])}), and {_keep_phrase(t)}.")
    else:
        head = f"- **{number(len(fewer)).capitalize()} other tools let fewer through:** " + listing(
            [f"{table_name(k)} ({pct(s.others[k]['leak_rate'])}; {_gap_phrase(s.leak_ci[k])})" for k in fewer]) + "."
    parts = [head]
    if more:
        gaps = _points(s, more)
        lo, hi = min(gaps), max(gaps)
        if len(more) == 1:
            parts.append(f"The other tool lets {lo} points more through.")
        else:
            parts.append(f"Every other tool lets {lo} to {hi} points more through.")
    keepers = s.keep_as_much()
    if not keepers:
        parts.append("No other tool keeps as much readable.")
    elif len(keepers) == 1:
        k = keepers[0]
        parts.append(f"Only {table_name(k)} keeps as much readable ({pct(s.others[k]['keep_rate'])}, "
                     f"{_keep_sign(s.keep_ci[k])}), and it lets {pct(s.others[k]['leak_rate'])} through.")
    else:
        parts.append(f"{number(len(keepers)).capitalize()} other tools keep as much readable: " + listing(
            [f"{table_name(k)} ({pct(s.others[k]['keep_rate'])}, {_keep_sign(s.keep_ci[k])})" for k in keepers]) + ".")
    return " ".join(parts)


@dataclass(frozen=True)
class Weak:
    """A category among nullpii's two weakest: its name, its leak rate and
    how many other tools let fewer of its items through, of how many."""

    category: str
    rate: float
    fewer: int
    of: int


def weakest(b: views.Bench) -> list[Weak]:
    """nullpii's two categories with the highest leak rate on A, the one
    with more items first, as `compare.ab1_ranks` counts the tools."""
    s = standing(b, A)
    by = s.me[compare.AB1_RANKED_BREAKDOWN]
    ordered = sorted(by, key=lambda c: -by[c][0])
    if len(ordered) > WEAKEST and by[ordered[WEAKEST - 1]][0] == by[ordered[WEAKEST]][0]:
        raise refuse("nullpii's weakest categories", "a tie for the last place named")
    found = []
    for c in sorted(ordered[:WEAKEST], key=lambda c: -by[c][1]):
        if c not in CATEGORIES:
            raise refuse("nullpii's weakest categories", f"no prose name for {c}")
        rates = [r[compare.AB1_RANKED_BREAKDOWN][c][0] for r in s.others.values() if c in r[compare.AB1_RANKED_BREAKDOWN]]
        found.append(Weak(c, by[c][0], sum(1 for r in rates if r < by[c][0]), len(rates)))
    return found


def _rate0(x: float) -> str:
    return pct(x, 0)


def _fewer_count(w: Weak) -> str:
    if w.fewer == 0:
        return f"none of the {w.of} other tools lets fewer through"
    return f"{w.fewer} of the {w.of} other tools {verb(w.fewer, 'lets', 'let')} fewer through"


def weakest_bullet(b: views.Bench) -> str:
    first, second = weakest(b)
    long1, short1 = CATEGORIES[first.category]
    long2, short2 = CATEGORIES[second.category]
    again = (("none does" if second.fewer == 0 else f"{second.fewer} {verb(second.fewer, 'does', 'do')}") if second.of == first.of
             else _fewer_count(second))
    return (f"- **Weakest categories:** {long1} ({_rate0(first.rate)} let through) and {long2} ({_rate0(second.rate)})."
            f" On {short1}, {_fewer_count(first)}; on {short2}, {again}.")


def _leads_on_secrets(b: views.Bench) -> bool:
    return not standing(b, B1).fewer() and not standing(b, B2).fewer()


# The published run's own split of CredData's leaks (no output holds it).
UUID_SPLIT = ("More than half of nullpii's leaks there (268 of 490) are UUIDs: CredData counts 294 UUIDs as credentials,"
              " mostly after keys that name ids (`id`, `uid`, `_postman_id`) or after no key, while nullpii, and AB-1's"
              " own specification, treat a UUID as an id to keep readable. Without them nullpii lets 13.0% through (an"
              " analysis made after the scores were read).")
UUID_ASIDE = ", most of it UUIDs that CredData counts as credentials and nullpii keeps readable as ids (13.0% without them)"
UUID_GLANCE = " (B1: 13.0% without the items CredData labels `UUID`)"


def uuid_split(b: views.Bench, text: str) -> str:
    """The published run's analysis, for its own outputs only."""
    return text if b.names == views.PUBLISHED_NAMES else ""


def _b1_clause(s: Standing) -> str:
    fewer = s.fewer()
    if not fewer:
        return f"On CredData it lets {pct(s.me['leak_rate'])} through, and no other tool lets fewer through."
    head = (f"On CredData it lets {pct(s.me['leak_rate'])} through, and {len(fewer)} of the {len(s.others)} other tools"
            f" {verb(len(fewer), 'lets', 'let')} fewer through")
    both = [k for k in fewer if s.others[k]["keep_rate"] > s.me["keep_rate"]]
    if not both:
        return head + "; none of them keeps as much readable."
    if len(both) == 1:
        t = s.others[both[0]]
        return (head + f"; {prose_name(both[0])} lets {pct(t['leak_rate'])} through and keeps more readable"
                f" ({pct(t['keep_rate'])} against {pct(s.me['keep_rate'])}).")
    return head + f"; {len(both)} of them also keep more readable: " + listing(
        [f"{prose_name(k)} ({pct(s.others[k]['leak_rate'])}, {pct(s.others[k]['keep_rate'])})" for k in both]) + "."


def _keep_against(s: Standing, key: str) -> str:
    mine, theirs = s.me["keep_rate"], s.others[key]["keep_rate"]
    if mine > theirs:
        return f"nullpii keeps more readable ({pct(mine)} against {pct(theirs)})"
    if mine < theirs:
        return f"it keeps more readable too ({pct(theirs)} against {pct(mine)})"
    raise refuse("a keep rate tied with nullpii's", "no wording for a tie")


def _b2_clause(s: Standing) -> str:
    fewer = s.fewer()
    if not fewer:
        return f"On secrets in GitHub issues, no other tool lets fewer through ({pct(s.me['leak_rate'])})."
    if len(fewer) == 1:
        t = s.others[fewer[0]]
        return (f"On secrets in GitHub issues, {prose_name(fewer[0])} lets fewer through ({pct(t['leak_rate'])} against"
                f" {pct(s.me['leak_rate'])}), and {_keep_against(s, fewer[0])}.")
    return (f"On secrets in GitHub issues, {len(fewer)} of the {len(s.others)} other tools let fewer through than"
            f" nullpii's {pct(s.me['leak_rate'])}.")


def _secrets_head(b: views.Bench) -> str:
    return "On secrets alone, no other tool lets fewer through" if _leads_on_secrets(b) else "On secrets alone, nullpii does not lead"


def secrets_bullet(b: views.Bench) -> str:
    split = uuid_split(b, UUID_SPLIT)
    parts = [f"- **{_secrets_head(b)}.**", _b1_clause(standing(b, B1)), *([split] if split else []),
             _b2_clause(standing(b, B2))]
    return " ".join(parts)


def readme_bullets(b: views.Bench) -> str:
    return "\n".join([lead_bullet(standing(b, A)), weakest_bullet(b), secrets_bullet(b)])


def card_weak_bullet(b: views.Bench) -> str:
    first, second = weakest(b)
    s1, s2 = standing(b, B1), standing(b, B2)
    fewer2 = s2.fewer()
    if not fewer2:
        issues = f"no other tool lets fewer GitHub-issue secrets through ({pct(s2.me['leak_rate'])})"
    elif len(fewer2) == 1:
        issues = (f"{prose_name(fewer2[0])} lets fewer GitHub-issue secrets through ({pct(s2.others[fewer2[0]]['leak_rate'])}"
                  f" against {pct(s2.me['leak_rate'])})")
    else:
        issues = f"{len(fewer2)} other tools let fewer GitHub-issue secrets through than its {pct(s2.me['leak_rate'])}"
    return (f"- **Weak spots:** {CATEGORIES[first.category][0]} ({_rate0(first.rate)} let through; {_fewer_count(first)})"
            f" and {CATEGORIES[second.category][0]} ({_rate0(second.rate)}). {_secrets_head(b)}: {issues}, and on CredData"
            f" nullpii lets {pct(s1.me['leak_rate'])} through{uuid_split(b, UUID_ASIDE)}.")


def card_traffic_bullet(b: views.Bench) -> str:
    s = standing(b, A)
    docs = s.me["docs"]
    return f"- **Coding-agent traffic (AB-1, {docs:,} documents):** nullpii {rates(s).removeprefix('it ')}. {fewer_sentence(s)}"


def roundtrip_sentence(b: views.Bench) -> str:
    rt = b.file(compare.ROUNDTRIP_FILE)
    if rt["roundtrip_failures"]:
        return (f"nullpii's round trip, run with the same build: of {rt['docs']:,} documents, {rt['masked']:,} of them with"
                f" something masked, {rt['roundtrip_failures']:,} did not come back as their exact original text after"
                " masking and restoring.")
    return (f"nullpii's round trip, run with the same build: all {rt['docs']:,} documents, {rt['masked']:,} of them with"
            " something masked, came back as their exact original text after masking and restoring.")


def coverage_counts(b: views.Bench) -> str:
    parts = []
    for key in settings.AB1_GOLD:
        c = b.ab1_coverage(key)
        name = key.removeprefix("ab1-").upper()
        parts.append(f"{name} {c['covered']:,} covered of {c['secrets']:,}" if not parts
                     else f"{name} {c['covered']:,} of {c['secrets']:,}")
    return "Items: " + ", ".join(parts)


def kept_kind(b: views.Bench, kind: str) -> str:
    s = standing(b, A)
    return pct(s.me["keep_by_kind"][kind][0])
