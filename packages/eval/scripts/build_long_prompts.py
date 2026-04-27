#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build `long-prompts-en-baseline.jsonl` from the existing `en-baseline.jsonl`.

Strategy: prepend each sample with realistic dev filler (CI logs, stack
traces, dependency dumps) that pushes the PII spans past the 512-token
chunk boundary. Adjusts span offsets accordingly.

Reproducible (seeded). PII positions then exercise the chunked-inference
code path; pre-chunking builds will silently truncate them.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"
SOURCE = DATASETS_DIR / "en-baseline.jsonl"
OUT = DATASETS_DIR / "long-prompts-en-baseline.jsonl"

# Realistic dev-flavored filler blocks. Each ~250-350 chars. Stack traces,
# CI logs, dependency dumps — what a real Claude Code prompt looks like.
FILLER_BLOCKS = [
    """[ci] step 1/12 fetching dependencies
> npm install --no-audit --no-fund
added 482 packages in 18s
> tsc --noEmit -p tsconfig.json
no errors emitted; build artifact size 2.4MB
> eslint . --max-warnings 0
no warnings
[ci] step 2/12 running unit tests
suite parser passed in 412ms (118 tests)
suite encoder passed in 78ms (24 tests)
suite runtime passed in 1.2s (302 tests)
[ci] step 3/12 building docker image
sha256:9a4b1c… layer cached
""",
    """Stack trace from production logs:
  at PaymentService.charge (services/payment.ts:118)
  at OrderHandler.confirm (handlers/order.ts:42)
  at Router.dispatch (router/dispatch.ts:88)
  at Server.handle (server/main.ts:201)
The retry queue flushed 412 events in the last 30 minutes; backoff held
under 200ms p99. Circuit breaker remained closed throughout the window.
Database read replicas reported sub-millisecond replication lag with no
write contention. Memory headroom held above 38% on every pod.
""",
    """Dependency audit output:
  axios@1.7.4 (no advisories)
  zod@3.23.8 (no advisories)
  fastify@4.28.1 (no advisories)
  @prisma/client@5.18.0 (no advisories)
  pg@8.13.0 (no advisories)
  ioredis@5.4.1 (no advisories)
  bullmq@5.12.0 (no advisories)
0 vulnerabilities reported. Lock file integrity verified against the
pinned manifest. License audit: every transitive dep is MIT/Apache/BSD.
""",
    """Architecture context for the change:
The ingestion pipeline reads from Kafka, normalizes through a Rust
worker pool, then commits to Postgres via batched writes. Throughput
holds at 12k events/sec sustained, with burst capacity to ~38k for up
to 4 minutes before lag accumulates. Backpressure flows through the
worker pool back to a partition-aware consumer that pauses individual
partitions rather than the whole subscription, keeping lag isolated.
""",
    """Migration plan:
- Phase 1: shadow write to the new schema while reading from the old.
- Phase 2: dual read with compare; alert on any divergence > 0.01%.
- Phase 3: flip read traffic to the new schema, keep dual writes 7 days.
- Phase 4: drop old schema after verification.
Rollback at any phase is < 5 minutes. We've rehearsed this on staging
twice. Capacity headroom is sufficient for the dual-write window.
""",
    """Performance benchmark (rps × p99 latency):
   500 rps → 12ms
  1000 rps → 18ms
  2500 rps → 27ms
  5000 rps → 41ms
  7500 rps → 58ms
 10000 rps → 89ms
The knee is around 7.5k rps; beyond that lock contention on the write
path dominates. We can flatten the curve by sharding the queue table or
moving the hot index to a covering index. Both are reversible.
""",
]


def assemble_filler(rng: random.Random) -> str:
    """Pick 6-8 filler blocks at random and join them — ~2 KB total, enough
    to push downstream content past the 512-token mark."""
    blocks = rng.sample(FILLER_BLOCKS, k=min(6, len(FILLER_BLOCKS)))
    extra = rng.choice(FILLER_BLOCKS)
    return "\n".join([*blocks, extra]) + "\n\n"


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"missing source dataset: {SOURCE}")
    rng = random.Random(20260427)
    out_rows: list[dict] = []
    with SOURCE.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            filler = assemble_filler(rng)
            shift = len(filler)
            new_text = filler + row["text"]
            new_spans = [
                {"label": s["label"], "start": s["start"] + shift, "end": s["end"] + shift}
                for s in row["spans"]
            ]
            out_rows.append({"text": new_text, "spans": new_spans})
    with OUT.open("w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(out_rows)} long samples → {OUT.name}")
    avg_chars = sum(len(r["text"]) for r in out_rows) / max(1, len(out_rows))
    print(f"average length: {avg_chars:.0f} chars")


if __name__ == "__main__":
    main()
