# SPDX-License-Identifier: Apache-2.0
"""Download the two carrier datasets at the pinned revisions into cache/hf/ (not part of the frozen set)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from huggingface_hub import hf_hub_download  # noqa: E402

from common import FB_DATASET, FB_REVISION, HF_CACHE, SWE_DATASET, SWE_REVISION  # noqa: E402

FILES = [
    (FB_DATASET, FB_REVISION, ["README.md", "data/train-00000-of-00001.parquet"]),
    (SWE_DATASET, SWE_REVISION, ["README.md", "LICENSE", "trajectories.parquet"]),
]


def main() -> None:
    for repo, rev, files in FILES:
        for f in files:
            print(hf_hub_download(repo, f, repo_type="dataset", revision=rev, cache_dir=str(HF_CACHE)))


if __name__ == "__main__":
    main()
