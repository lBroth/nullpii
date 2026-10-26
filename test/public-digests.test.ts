// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { dropSpansInsidePublicDigests } from '../src/public-digests.js';

const SRI =
  'sha512-ixgk3mI8ApAeS6S6bfPfO0ehvq7cqmAr7mVBnMV7jaypURFpGvlrStuEUeSA5Mqzuno8lCWSy+3Yw8DSq0K3kA==';
const text = `"integrity": "${SRI}",\nAWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`;
const sriStart = text.indexOf(SRI);
const span = (start: number, end: number) => ({ label: 'secret', start, end });

describe('dropSpansInsidePublicDigests', () => {
  it('drops spans that sit inside an integrity digest', () => {
    const inside = span(sriStart + 7, sriStart + 30);
    expect(dropSpansInsidePublicDigests([inside], text)).toEqual([]);
  });

  it('keeps a span that extends past the digest', () => {
    const straddling = span(sriStart + 7, sriStart + SRI.length + 3);
    expect(dropSpansInsidePublicDigests([straddling], text)).toEqual([straddling]);
  });

  it('keeps free-standing base64, which can be a real secret', () => {
    const keyStart = text.indexOf('wJalr');
    const key = span(keyStart, keyStart + 40);
    expect(dropSpansInsidePublicDigests([key], text)).toEqual([key]);
  });

  it('requires the hash-algorithm prefix', () => {
    const bare = 'ixgk3mI8ApAeS6S6bfPfO0ehvq7cqmAr7mVBnMV7jaypURFpGvlrStuE';
    expect(dropSpansInsidePublicDigests([span(0, 20)], bare)).toHaveLength(1);
  });
});
