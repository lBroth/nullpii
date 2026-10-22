// SPDX-License-Identifier: Apache-2.0
//
// The default model is pinned: a SHA-256 for every file the runtime can
// fetch, wired into `DEFAULT_MODEL`. The commit is checked by the release
// workflow, which refuses a tag until DEFAULT_MODEL_REVISION names one.

import { describe, expect, it } from 'vitest';
import { DEFAULT_MODEL_SHA256, MODEL_FILES } from '../src/defaults.js';
import { DEFAULT_MODEL, SHARED_FILES } from '../src/model-manager.js';

const SHA256 = /^[0-9a-f]{64}$/;
const FETCHED = [...Object.values(MODEL_FILES), ...SHARED_FILES];

describe('default model pin', () => {
  it('carries the pinned hashes', () => {
    expect(DEFAULT_MODEL.sha256).toBe(DEFAULT_MODEL_SHA256);
  });

  it.each(FETCHED)('pins the SHA-256 of %s', (file) => {
    expect(DEFAULT_MODEL.sha256?.[file]).toMatch(SHA256);
  });

  it('pins nothing it does not fetch', () => {
    expect(Object.keys(DEFAULT_MODEL_SHA256).sort()).toEqual([...FETCHED].sort());
  });
});
