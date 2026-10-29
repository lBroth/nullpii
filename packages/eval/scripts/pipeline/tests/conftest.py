# SPDX-License-Identifier: Apache-2.0
"""Puts `scripts/` on the path, as `bench_pipeline.py` does, so the tests
import the pipeline as the entry point runs it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
