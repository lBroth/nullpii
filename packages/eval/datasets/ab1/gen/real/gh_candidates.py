# SPDX-License-Identifier: Apache-2.0
"""Phase A, AB-1: candidate repositories holding real it/de/fr/es GitHub issues.

Source: github/multilingual-repositories (CC0-1.0), commit 3d63dbdb61f69663486309a1f8805a1c8eb4a353,
`cache/gh-multilingual/data/repository_classifications/part-*.parquet` (80,657,333 rows) and
`cache/gh-multilingual/data/repository_metadata/part-*.parquet` (40,817,528 rows). The dataset
holds no issue text: it names repositories, `gen/real/gh_fetch.py` fetches the text later.

    python gen/real/gh_candidates.py [--classifications GLOB] [--metadata GLOB] [--out DIR] [--keep N]

A repository is kept for a language when
  1. at least two of the three classifiers (fasttext, gcld3, linguapy) classify its *issues*
     (`source == "issue"`) as that language with confidence >= 0.9, and
  2. no classifier gives any other language for its issues with confidence >= 0.5.
     (The dataset only ships rows above 0.5 confidence, so rule 2 drops every repository whose
     issue evidence mentions a second language at all. A repository that would qualify for two
     languages therefore drops out of both: the rule is deterministic, no tie-break is needed.)
  3. its metadata gives an SPDX licence in LICENCES, at least MIN_ISSUES = 5 issues and at least
     MIN_STARS = 3 stars.

Survivors are ranked by the builder's seeded priority `derive_seed("pool", "<repository_id>")`
(ascending, as in the carrier pool) and the best `--keep` (400) per language are written, one
repository id per line, to `cache/real/gh_candidates_<lang>.txt` (lang = it, de, fr, es; the
dataset's own codes are upper case IT, DE, FR, ES).

Prints counts only.
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import ROOT, derive_seed  # noqa: E402

LANGS = {"IT": "it", "DE": "de", "FR": "fr", "ES": "es"}
HIGH, LOW = 0.9, 0.5
LICENCES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "CC0-1.0", "Unlicense",
            "MPL-2.0", "CC-BY-4.0"}
MIN_ISSUES = 5
MIN_STARS = 3
KEEP_PER_LANG = 400

DEFAULT_CLASS = str(ROOT / "cache" / "gh-multilingual" / "data" / "repository_classifications" / "part-*.parquet")
DEFAULT_META = str(ROOT / "cache" / "gh-multilingual" / "data" / "repository_metadata" / "part-*.parquet")
DEFAULT_OUT = ROOT / "cache" / "real"


def read_issue_evidence(pattern: str) -> pd.DataFrame:
    """(repository_id, classifier, lang_code) -> best confidence, from the issue classifications."""
    parts = []
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"no classification files for {pattern}")
    seen = 0
    for path in files:
        table = pq.read_table(path, columns=["repository_id", "lang_code", "confidence", "source", "classifier"])
        table = table.filter(pc.equal(table.column("source"), "issue"))
        seen += table.num_rows
        parts.append(table.to_pandas())
    df = pd.concat(parts, ignore_index=True)
    del parts
    df["lang_code"] = df["lang_code"].astype("category")
    df["classifier"] = df["classifier"].astype("category")
    print(f"issue classification rows read: {seen}")
    g = (df.groupby(["repository_id", "lang_code", "classifier"], observed=True, as_index=False)["confidence"]
         .max())
    del df
    return g


def agree(df: pd.DataFrame) -> pd.DataFrame:
    """Repositories whose issue language two classifiers agree on at >= 0.9, with no other language >= 0.5."""
    df = df.assign(hi=(df["confidence"] >= HIGH).astype("int8"), lo=(df["confidence"] >= LOW).astype("int8"))
    per = df.groupby(["repository_id", "lang_code"], observed=True, as_index=False)[["hi", "lo"]].sum()
    two = per[per["hi"] >= 2]
    two = two[two["lang_code"].astype(str).isin(LANGS)]
    other = per[per["lo"] > 0][["repository_id", "lang_code"]]
    mixed = other.merge(two[["repository_id", "lang_code"]], on="repository_id", suffixes=("", "_t"))
    bad = set(mixed.loc[mixed["lang_code"].astype(str) != mixed["lang_code_t"].astype(str), "repository_id"])
    out = two[~two["repository_id"].isin(bad)].copy()
    out["lang"] = out["lang_code"].astype(str).map(LANGS)
    print(f"repositories with issue classifications: {df['repository_id'].nunique()}")
    print(f"repositories with 2-of-3 agreement at >= {HIGH}: {len(two)}")
    print(f"dropped for a second language at >= {LOW}: {len(two) - len(out)}")
    return out[["repository_id", "lang"]]


def read_metadata(pattern: str, ids: set[int]) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"no metadata files for {pattern}")
    parts = []
    wanted = pa.array(sorted(ids), type=pa.int64())
    for path in files:
        table = pq.read_table(path, columns=["repository_id", "spdx_license", "num_issues", "num_stars"])
        mask = pc.is_in(table.column("repository_id"), value_set=wanted)
        table = table.filter(mask)
        if table.num_rows:
            parts.append(table.to_pandas())
    print(f"metadata rows for candidate repositories: {sum(len(p) for p in parts)}")
    if not parts:
        return pd.DataFrame(columns=["repository_id", "spdx_license", "num_issues", "num_stars"])
    return pd.concat(parts, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classifications", default=DEFAULT_CLASS)
    ap.add_argument("--metadata", default=DEFAULT_META)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--keep", type=int, default=KEEP_PER_LANG)
    args = ap.parse_args()

    cand = agree(read_issue_evidence(args.classifications))
    meta = read_metadata(args.metadata, set(cand["repository_id"]))
    joined = cand.merge(meta, on="repository_id", how="left")
    print(f"candidates with metadata: {joined['spdx_license'].notna().sum()}")
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"{'lang':>4} {'agree':>7} {'licence':>8} {'issues':>7} {'stars':>6} {'kept':>5}")
    for code, lang in LANGS.items():
        rows = joined[joined["lang"] == lang]
        lic = rows[rows["spdx_license"].isin(LICENCES)]
        iss = lic[lic["num_issues"] >= MIN_ISSUES]
        sta = iss[iss["num_stars"] >= MIN_STARS]
        ranked = sorted(sta["repository_id"].tolist(), key=lambda rid: (derive_seed("pool", str(rid)), rid))
        kept = ranked[:args.keep]
        path = outdir / f"gh_candidates_{lang}.txt"
        with path.open("w", encoding="utf-8") as fh:
            for rid in kept:
                fh.write(f"{rid}\n")
        print(f"{lang:>4} {int((cand['lang'] == lang).sum()):>7} {len(lic):>8} {len(iss):>7} "
              f"{len(sta):>6} {len(kept):>5}")


if __name__ == "__main__":
    main()
