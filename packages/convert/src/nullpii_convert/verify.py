# SPDX-License-Identifier: Apache-2.0
"""Verify integrity of fetched model artifacts.

- Re-hashes every file and compares against the manifest.
- If `model.sig` is present, attempts sigstore verification (best-effort, only
  when the optional `sigstore` package is available — surfaces a warning if not).
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from .checksums import sha256_of, write_sidecar
from .config import MANIFEST_PATH, MODEL_DIR

log = logging.getLogger(__name__)

SIG_FILENAME = "model.sig"


def write_sidecars(model_dir: Path = MODEL_DIR) -> int:
    """Write a `*.sha256` sidecar next to every artifact. Returns count written."""
    if not model_dir.is_dir():
        raise FileNotFoundError(f"write_sidecars: {model_dir} not found")
    n = 0
    for f in model_dir.rglob("*"):
        if f.is_file() and not f.name.endswith(".sha256"):
            write_sidecar(f)
            n += 1
    log.info("wrote %d sidecars under %s", n, model_dir)
    return n


def verify_manifest(model_dir: Path = MODEL_DIR, manifest_path: Path = MANIFEST_PATH) -> bool:
    """Recompute SHA256 for every file in the manifest and compare. Returns True
    if all match. Logs a row per mismatch."""
    if not manifest_path.is_file():
        log.error("manifest not found: %s — run pipeline manifest first", manifest_path)
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ok = True
    for entry in manifest["files"]:
        full = model_dir / entry["path"]
        if not full.is_file():
            log.error("missing file: %s", full)
            ok = False
            continue
        actual = sha256_of(full)
        if actual != entry["sha256"]:
            log.error(
                "sha mismatch: %s expected=%s actual=%s",
                entry["path"], entry["sha256"][:12], actual[:12],
            )
            ok = False
    if ok:
        log.info("verified %d files against manifest", len(manifest["files"]))
    return ok


def verify_signature(model_dir: Path = MODEL_DIR) -> bool | None:
    """Best-effort sigstore verification of `model.sig`.

    Returns:
        True  — verification passed
        False — verification failed
        None  — no signature present, or no verifier installed (skipped)
    """
    sig = model_dir / SIG_FILENAME
    if not sig.is_file():
        log.info("no %s present — skipping signature check", SIG_FILENAME)
        return None
    if shutil.which("sigstore") is None:
        log.warning("sigstore CLI not found — cannot verify %s", sig)
        return None
    log.info("verifying signature with sigstore CLI")
    res = subprocess.run(
        ["sigstore", "verify", "identity", "--cert-identity-regexp", ".*",
         "--cert-oidc-issuer-regexp", ".*", str(sig)],
        capture_output=True, text=True, check=False,
    )
    if res.returncode == 0:
        log.info("signature verified")
        return True
    log.error("signature verification failed: %s", res.stderr.strip())
    return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    write_sidecars()
    if not verify_manifest():
        return 1
    sig_ok = verify_signature()
    if sig_ok is False:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
