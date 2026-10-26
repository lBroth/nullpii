// SPDX-License-Identifier: Apache-2.0
//
// The start-up tracker the status route answers with: one view per step
// of the engine's warmup, and which step was running when it failed.

import { describe, expect, it } from 'vitest';
import { StartupTracker } from '../src/startup.js';

describe('startup tracker', () => {
  it('starts at downloading: the first ensure fetches or verifies files', () => {
    expect(new StartupTracker().current).toEqual({ phase: 'downloading' });
  });

  it('tracks bytes per file, and the whole size only when the hub names it', () => {
    const startup = new StartupTracker();
    startup.report({ phase: 'downloading', file: 'tokenizer.json', received: 12 });
    expect(startup.current).toEqual({ phase: 'downloading', file: 'tokenizer.json', received: 12 });
    startup.report({ phase: 'downloading', file: 'model.onnx', received: 640, total: 1160 });
    expect(startup.current).toEqual({
      phase: 'downloading',
      file: 'model.onnx',
      received: 640,
      total: 1160,
    });
    startup.report({ phase: 'loading' });
    expect(startup.current).toEqual({ phase: 'loading' });
    startup.report({ phase: 'ready' });
    expect(startup.current).toEqual({ phase: 'ready' });
  });

  it('names the step a failed warmup was in', () => {
    const startup = new StartupTracker();
    startup.report({ phase: 'downloading', file: 'model.onnx', received: 640, total: 1160 });
    startup.failed();
    expect(startup.current).toEqual({ phase: 'failed', while: 'downloading' });
    const loading = new StartupTracker();
    loading.report({ phase: 'loading' });
    loading.failed();
    expect(loading.current).toEqual({ phase: 'failed', while: 'loading' });
  });
});
