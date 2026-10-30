# SPDX-License-Identifier: Apache-2.0
"""Write every published number from a set of scoring outputs: the files
of `published-bench/`, every marked region of the tracked docs
(`docs.BLOCKS`), and the README's figures with their alternative texts.

`render` takes a run's `out` (`score`'s), a `reference` directory (the
published outputs in the published run's row names) or
`published-bench/` itself. It first lays the outputs out in
`published-bench/` (the files a run writes, and `OUTPUTS.json`, which
says in whose row names they are and lists them), then renders the docs
and figures from `published-bench/`, so the docs say what it holds.

`check` writes nothing: it lists each file of `published-bench/`, each
marked region and each figure that differs from what the outputs give.
`render --run packages/eval/published-bench --check` proves the docs say
what `published-bench/` holds, with no frozen input. A claim the outputs
no longer support is reworded by its block, so it shows up as a
difference, or refused (`prose.RenderError`) when the block has no
wording for it."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline import blocks_ab1, blocks_r3, compare, docs, settings, views
from pipeline.prose import RenderError

sys.path.insert(0, str(settings.SCRIPTS))

import readme_figures  # noqa: E402

PUBLISHED_BENCH = settings.PUBLISHED
MARKER = re.compile(r"<!-- ([a-z0-9-]+):(begin|end) -->")


class DocError(Exception):
    """A doc's markers are not one well-formed region per rendered block."""


@dataclass(frozen=True)
class Difference:
    where: str
    why: str

    def __str__(self) -> str:
        return f"{self.where}: {self.why}"


def load(source: Path) -> views.Bench:
    return views.load(source)


# published-bench ---------------------------------------------------------------

def output_files(b: views.Bench) -> list[str]:
    """The outputs a set holds, as `published-bench/` keeps them."""
    return [rel for rel in compare.expected_files() if rel in b.o.files]


def published_files(source: Path, b: views.Bench) -> dict[str, bytes]:
    """`published-bench/`'s files from `source`, byte for byte, and the
    marker that says in whose row names they are."""
    files = {rel: (source / rel).read_bytes() for rel in output_files(b)}
    marker: dict = {"names": b.names, "files": sorted(files), views.VERSION_KEY: b.version}
    reference = source / views.REFERENCE_MARKER
    if reference.is_file():
        marker["reference_of"] = json.loads(reference.read_text(encoding="utf-8"))["reference_of"]
    elif (source / views.OUTPUTS_MARKER).is_file():
        previous = json.loads((source / views.OUTPUTS_MARKER).read_text(encoding="utf-8"))
        if "reference_of" in previous:
            marker["reference_of"] = previous["reference_of"]
    files[views.OUTPUTS_MARKER] = (json.dumps(marker, indent=1, sort_keys=True) + "\n").encode("utf-8")
    return files


def _listed(published: Path) -> set[str]:
    marker = published / views.OUTPUTS_MARKER
    if not marker.is_file():
        return set()
    return set(json.loads(marker.read_text(encoding="utf-8"))["files"]) | {views.OUTPUTS_MARKER}


def published_differences(files: dict[str, bytes], published: Path) -> list[Difference]:
    out = []
    for rel, content in files.items():
        target = published / rel
        if not target.is_file():
            out.append(Difference(f"published-bench/{rel}", "missing"))
        elif target.read_bytes() != content:
            out.append(Difference(f"published-bench/{rel}", "differs"))
    out += [Difference(f"published-bench/{rel}", "no longer an output") for rel in sorted(_listed(published) - set(files))]
    return out


def write_published(files: dict[str, bytes], published: Path) -> None:
    """Write the files, and remove those a previous render listed that are
    no output now; nothing else in `published` is touched."""
    stale = _listed(published) - set(files)
    for rel, content in files.items():
        target = published / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        target.write_bytes(content)
    for rel in stale:
        (published / rel).unlink(missing_ok=True)


# Marked regions -------------------------------------------------------------------

def regions(text: str, path: Path) -> list[str]:
    """The names of the regions in `text`, in order; each opened once and
    closed before the next opens."""
    found, open_name = [], None
    for m in MARKER.finditer(text):
        name, side = m.groups()
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if text[line_start:line_end if line_end != -1 else None] != m.group(0):
            raise DocError(f"{path}: the {name} marker is not on a line of its own")
        if side == "begin":
            if open_name is not None:
                raise DocError(f"{path}: {name} opens inside {open_name}")
            open_name = name
        else:
            if open_name != name:
                raise DocError(f"{path}: {name} closes, but {open_name} is open")
            found.append(name)
            open_name = None
    if open_name is not None:
        raise DocError(f"{path}: {open_name} never closes")
    if len(found) != len(set(found)):
        raise DocError(f"{path}: a region is marked twice")
    return found


def fill(text: str, path: Path, bodies: dict[str, str]) -> str:
    """`text` with each region's body replaced by `bodies[name]`. Every
    region must have a body (or be a hand-kept one), and every body a
    region."""
    names = regions(text, path)
    unknown = [n for n in names if n not in bodies and n not in docs.KEPT]
    missing = [n for n in bodies if n not in names]
    if unknown or missing:
        raise DocError(f"{path}: regions without a renderer: {unknown}; renderers without a region: {missing}")
    for name, body in bodies.items():
        pattern = re.compile(rf"(<!-- {name}:begin -->\n).*?(<!-- {name}:end -->)", re.S)
        text = pattern.sub(lambda m, body=body: m.group(1) + body + "\n" + m.group(2), text, count=1)
    return text


def rendered_docs(b: views.Bench, root: Path) -> dict[str, str]:
    """Each doc of `docs.BLOCKS` (by its path from `root`), rendered."""
    out = {}
    for rel, blocks in docs.BLOCKS.items():
        bodies = {name: block(b) for name, block in blocks.items()}
        out[rel] = fill((root / rel).read_text(encoding="utf-8"), Path(rel), bodies)
    return out


def region_differences(root: Path, rel: str, new: str) -> list[Difference]:
    old = (root / rel).read_text(encoding="utf-8")
    if old == new:
        return []
    names = regions(old, Path(rel))
    changed = [n for n in names if _body(old, n) != _body(new, n)]
    return [Difference(f"{rel} <!-- {n} -->", "differs") for n in changed] or [Difference(rel, "differs outside its regions")]


def _body(text: str, name: str) -> str:
    m = re.search(rf"<!-- {name}:begin -->\n(.*?)<!-- {name}:end -->", text, re.S)
    return m.group(1) if m else ""


# Figures --------------------------------------------------------------------------

def figures(b: views.Bench, readme: str | None = None) -> dict[str, str]:
    """The README's figures, from the outputs (the latency chart from the
    README's hand-kept latency block)."""
    readme = readme if readme is not None else (views.ROOT / docs.README).read_text(encoding="utf-8")
    return {
        "ab1-agent-traffic.svg": readme_figures.ab1_chart(
            b.ab1(blocks_ab1.A), blocks_ab1.chart_labels(b), b.ab1_baseline(blocks_ab1.A)),
        "r3-documents.svg": readme_figures.r3_chart(blocks_r3.chart_rows(b), blocks_r3.chart_floor(b)),
        "latency-gpu.svg": readme_figures.latency_chart(readme_figures.latency_rows(readme)),
        "how-it-works.svg": readme_figures.how_it_works(),
    }


# The step ---------------------------------------------------------------------------

def _rendered(b: views.Bench, root: Path) -> dict[str, str]:
    """Every rendered doc and figure, by its path from `root`."""
    new_docs = rendered_docs(b, root)
    svgs = {f"{docs.FIGURES}/{name}": content for name, content in figures(b, new_docs[docs.README]).items()}
    return {**new_docs, **svgs}


def check(source: Path, published: Path = PUBLISHED_BENCH, root: Path = views.ROOT) -> list[Difference]:
    """What would change if `source` were rendered; nothing is written."""
    b = load(source)
    diffs = published_differences(published_files(source, b), published)
    for rel, text in _rendered(b, root).items():
        path = root / rel
        if rel.endswith(".md"):
            diffs += region_differences(root, rel, text)
        elif not path.is_file() or path.read_text(encoding="utf-8") != text:
            diffs.append(Difference(rel, "differs"))
    return diffs


def render(source: Path, published: Path = PUBLISHED_BENCH, root: Path = views.ROOT) -> list[Difference]:
    """Lay `source` out in `published`, then render the docs and figures
    from `published`. Returns what changed."""
    same = source.resolve() == published.resolve()
    if not same and published.resolve() in source.resolve().parents:
        raise RenderError(f"--run {source} is inside {published}: give a run's out, a reference or {published} itself")
    changed = check(source, published, root)
    # From published-bench itself, every output is read before it is
    # written back, and only the marker can change.
    write_published(published_files(source, load(source)), published)
    for rel, text in _rendered(load(published), root).items():
        path = root / rel
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    return changed
