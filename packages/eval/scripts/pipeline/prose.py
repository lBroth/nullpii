# SPDX-License-Identifier: Apache-2.0
"""How the rendered docs write numbers and words, and the rule for claims.

A claim (a rank, a "fewer", an "only", a sign of an interval) is never
written by hand: a block states it from the data, in the words the data
supports. A wording a block has no form for (a tie it cannot name, a
claim it would have to invent) is refused with `RenderError`, never
written anyway."""
from __future__ import annotations

from collections.abc import Sequence

MINUS = "−"
ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
            "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
            "eighteenth", "nineteenth", "twentieth")
NUMBER_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
ORDINAL_SUFFIXES = {1: "st", 2: "nd", 3: "rd"}
TEENS = range(11, 14)
SUFFIX_MODULO = 10
HUNDRED = 100


class RenderError(Exception):
    """A doc cannot be rendered from these outputs: a claim the data does
    not support in any wording the block has, or outputs that lack what
    the block reads."""


def refuse(claim: str, why: str) -> RenderError:
    return RenderError(f"refused: {claim}: {why}")


def ordinal(n: int) -> str:
    if n < 1:
        raise ValueError(f"no ordinal for {n}")
    if n <= len(ORDINALS):
        return ORDINALS[n - 1]
    suffix = "th" if n % HUNDRED in TEENS else ORDINAL_SUFFIXES.get(n % SUFFIX_MODULO, "th")
    return f"{n}{suffix}"


def number(n: int) -> str:
    """A count in words up to ten, as the docs write them."""
    return NUMBER_WORDS[n] if 0 <= n < len(NUMBER_WORDS) else f"{n:,}"


def tools(n: int) -> str:
    """`n` tools, in figures: "1 tool", "14 tools"."""
    return f"{n} tool" if n == 1 else f"{n} tools"


def verb(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def pct(x: float, decimals: int = 1) -> str:
    return f"{HUNDRED * x:.{decimals}f}%"


def f3(x: float) -> str:
    return f"{x:.3f}"


def signed(x: float, decimals: int = 3) -> str:
    return f"{x:+.{decimals}f}".replace("-", MINUS)


def interval(ci: Sequence[float], decimals: int = 3) -> str:
    return "[" + ", ".join(signed(v, decimals) for v in ci) + "]"


def points(ci: Sequence[float]) -> str:
    """An AB-1 interval in percentage points, as the tables print it."""
    return interval([HUNDRED * v for v in ci], 1)


def listing(items: Sequence[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""
    if not items:
        raise ValueError("an empty listing")
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]
