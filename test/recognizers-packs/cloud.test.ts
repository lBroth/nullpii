import { describe, expect, it } from 'vitest';
import {
  AWS_ACCESS_KEY,
  CLOUD_KEYS,
  GITHUB_PAT,
  STRIPE_LIVE_KEY,
} from '../../packages/recognizers-cloud/src/index.js';
import { runRecognizers } from '../../src/recognizers.js';

describe('@nullpii/recognizers-cloud', () => {
  it('AWS_ACCESS_KEY catches AKIA + ASIA prefixes', () => {
    const text = 'leak: AKIAIOSFODNN7EXAMPLE and ASIAIOSFODNN7EXAMPLE';
    const spans = runRecognizers(text, [AWS_ACCESS_KEY], []);
    expect(spans).toHaveLength(2);
    expect(spans.every((s) => s.label === 'secret')).toBe(true);
  });

  it('GITHUB_PAT catches ghp_ tokens', () => {
    const text = 'token: ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890';
    const spans = runRecognizers(text, [GITHUB_PAT], []);
    expect(spans).toHaveLength(1);
  });

  it('STRIPE_LIVE_KEY catches sk_live_ keys', () => {
    const text = 'STRIPE=sk_live_aBcDeFgHiJkLmNoPqRsTuVwX';
    const spans = runRecognizers(text, [STRIPE_LIVE_KEY], []);
    expect(spans).toHaveLength(1);
  });

  it('CLOUD_KEYS bundle covers all individual recognizers', () => {
    const text =
      'AKIAIOSFODNN7EXAMPLE ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890 sk_live_aBcDeFgHiJkLmNoPqRsTuVwX';
    const spans = runRecognizers(text, [...CLOUD_KEYS], []);
    expect(spans.length).toBeGreaterThanOrEqual(3);
  });
});
