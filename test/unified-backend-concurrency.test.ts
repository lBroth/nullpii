// SPDX-License-Identifier: Apache-2.0
//
// F-05 regression test. `OrtUnifiedBackend` previously pooled the
// `text_lengths` and `span_mask` scratch buffers across `infer()` calls.
// In a sequential, single-instance usage that's fine — but two concurrent
// `infer()` calls on the same backend (e.g. one `NullPii` shared across
// HTTP handlers) interleave between the buffer write and the
// `session.run()` await, so the second caller overwrites the first's
// tensor data before ORT consumes it. Outputs are silently wrong, no
// exception raised.
//
// This test instruments a mocked `onnxruntime-node` session whose `run()`
// snapshots the input tensor data at TWO points: synchronously on entry,
// and after one microtask yield. With pooled buffers the post-yield
// snapshot diverges from the synchronous one when a second caller writes
// the shared pool between those points. With per-call allocations every
// snapshot matches its caller's input.

import { describe, expect, it, vi } from 'vitest';

interface FeedSnapshot {
  readonly enterTextLength: bigint;
  readonly enterSpanMaskHash: number;
  readonly afterYieldTextLength: bigint;
  readonly afterYieldSpanMaskHash: number;
}

const { snapshots, maskHash } = vi.hoisted(() => {
  const snapshots: FeedSnapshot[] = [];
  const maskHash = (buf: Uint8Array): number => {
    let h = 0;
    for (let i = 0; i < buf.length; i++) h = (h * 31 + (buf[i] ?? 0)) | 0;
    return h;
  };
  return { snapshots, maskHash };
});

// Stub ORT loader — production calls `loadOrt()` which dynamically imports
// `onnxruntime-node`. We inject this loader via the backend's `ortLoader`
// option so the real native binding never runs.
class StubTensor {
  constructor(
    public readonly type: string,
    public readonly data: BigInt64Array | Uint8Array | Float32Array,
    public readonly dims: readonly number[],
  ) {}
}

const stubSession = {
  outputNames: ['logits'],
  async run(feeds: Record<string, StubTensor>): Promise<Record<string, StubTensor>> {
    const textLengths = feeds.text_lengths?.data as BigInt64Array;
    const spanMask = feeds.span_mask?.data as Uint8Array;
    const enterTextLength = textLengths[0] ?? 0n;
    const enterSpanMaskHash = maskHash(spanMask);
    // Yield so the second caller has a chance to enter `infer()` and
    // write to the same shared buffers before this one reads them again.
    await new Promise((r) => setImmediate(r));
    const afterYieldTextLength = textLengths[0] ?? 0n;
    const afterYieldSpanMaskHash = maskHash(spanMask);
    snapshots.push({
      enterTextLength,
      enterSpanMaskHash,
      afterYieldTextLength,
      afterYieldSpanMaskHash,
    });
    return {
      logits: new StubTensor('float32', new Float32Array(1), [1, 1, 1, 1]),
    };
  },
  async release(): Promise<void> {},
};

const stubOrt = {
  Tensor: StubTensor,
  InferenceSession: {
    async create(): Promise<typeof stubSession> {
      return stubSession;
    },
  },
} as unknown as typeof import('onnxruntime-node');

vi.mock('../src/paths.js', async () => {
  const actual = await vi.importActual<typeof import('../src/paths.js')>('../src/paths.js');
  return { ...actual, fileExists: async () => true };
});

const { OrtUnifiedBackend } = await import('../src/backend/unified-backend.js');

function inputs(textLength: number, maskByte: number) {
  const numSpans = 4;
  return {
    inputIds: BigInt64Array.from([0n, 0n]),
    attentionMask: BigInt64Array.from([1n, 1n]),
    wordsMask: BigInt64Array.from([0n, 1n]),
    textLength,
    spanIdx: BigInt64Array.from([0n, 0n, 0n, 1n, 1n, 1n, 0n, 0n]),
    spanMask: BigInt64Array.from(Array.from({ length: numSpans }, () => BigInt(maskByte))),
    numSpans,
  };
}

describe('F-05 · OrtUnifiedBackend concurrency', () => {
  it('two concurrent infer() calls on the same backend see their own tensor data, not the pool', async () => {
    snapshots.length = 0;
    const backend = new OrtUnifiedBackend('/fake', { ortLoader: async () => stubOrt });
    // Distinct textLength and spanMask values per caller. With pooled
    // scratch buffers, caller B's writes clobber caller A's tensor data
    // before A's `session.run` reads it post-yield.
    const callA = backend.infer(inputs(7, 1));
    const callB = backend.infer(inputs(42, 0));
    await Promise.all([callA, callB]);
    expect(snapshots).toHaveLength(2);

    // Each snapshot's post-yield read MUST equal its pre-yield read.
    // Pool sharing causes divergence; per-call allocation guarantees equality.
    for (const s of snapshots) {
      expect(s.afterYieldTextLength).toBe(s.enterTextLength);
      expect(s.afterYieldSpanMaskHash).toBe(s.enterSpanMaskHash);
    }

    // And the two callers' tensor data must be distinct (7 vs 42).
    const lengthsSeen = new Set(snapshots.map((s) => s.enterTextLength));
    expect(lengthsSeen.has(7n)).toBe(true);
    expect(lengthsSeen.has(42n)).toBe(true);
  });
});
