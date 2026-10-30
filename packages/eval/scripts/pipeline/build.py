# SPDX-License-Identifier: Apache-2.0
"""What a capture measured: the nullpii version and the model it pins (of
the tree the pipeline runs in, the tree `--dist` must be built from), and
the CPU it ran on (ONNX Runtime's CPU kernels can differ by instruction
set). Recorded in each part, put together by `score` in MEASURED.json,
and kept by `render` in published-bench's OUTPUTS.json."""
from __future__ import annotations

import json
import platform
import re
import subprocess
from pathlib import Path

DEFAULTS = "src/defaults.ts"
PACKAGE_JSON = "package.json"
CPUINFO = Path("/proc/cpuinfo")
UNKNOWN_CPU = "unknown CPU"
REVISION = re.compile(r"^export const DEFAULT_MODEL_REVISION = '([0-9a-f]{40})';$", re.MULTILINE)
REPO = re.compile(r"^export const DEFAULT_MODEL_REPO = '([^']+)';$", re.MULTILINE)
HASHES = re.compile(r"^export const DEFAULT_MODEL_SHA256[^=]*= \{\n(.*?)\n\};$", re.MULTILINE | re.DOTALL)
HASH_ENTRY = re.compile(r"^\s*'([^']+)': '([0-9a-f]{64})',$")


class BuildError(Exception):
    """The tree does not say which nullpii and model it is."""


def nullpii_version(root: Path) -> str:
    """The package version of the tree at `root`, in full."""
    return json.loads((root / PACKAGE_JSON).read_text(encoding="utf-8"))["version"]


def pinned_model(root: Path) -> tuple[str, str, dict[str, str]]:
    """The repository, revision and per-file SHA-256 the library pins."""
    text = (root / DEFAULTS).read_text(encoding="utf-8")
    repo, revision, hashes = REPO.search(text), REVISION.search(text), HASHES.search(text)
    if repo is None or revision is None or hashes is None:
        raise BuildError(f"{DEFAULTS}: no DEFAULT_MODEL_REPO, 40-hex DEFAULT_MODEL_REVISION or DEFAULT_MODEL_SHA256")
    entries = {}
    for line in hashes.group(1).splitlines():
        m = HASH_ENTRY.match(line)
        if m is None:
            raise BuildError(f"{DEFAULTS}: a DEFAULT_MODEL_SHA256 line that is not 'file': 'sha256',")
        entries[m.group(1)] = m.group(2)
    return repo.group(1), revision.group(1), entries


def model_ref(root: Path) -> str:
    repo, revision, _ = pinned_model(root)
    return f"{repo}@{revision}"


def cpu_model() -> str:
    """The CPU's model name, as the system reports it."""
    if CPUINFO.is_file():
        for line in CPUINFO.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    if platform.system() == "Darwin":
        done = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], stdout=subprocess.PIPE, text=True, check=False)
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    return platform.processor() or UNKNOWN_CPU


def measured(root: Path) -> dict[str, str]:
    """What a capture in the tree at `root` measures, and on what."""
    return {"nullpii": nullpii_version(root), "model": model_ref(root), "cpu": cpu_model()}
