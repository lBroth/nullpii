import { describe, expect, it } from 'vitest';
import { runRecognizers } from '../src/recognizers.js';
import type { PiiSpan, Recognizer } from '../src/types/index.js';

const awsKey: Recognizer = {
  id: 'aws-access-key',
  pattern: /\bAKIA[0-9A-Z]{16}\b/g,
  label: 'secret',
  confidence: 0.99,
};

const luhnCard: Recognizer = {
  id: 'credit-card',
  pattern: /\b\d{16}\b/g,
  label: 'account_number',
  confidence: 0.95,
  validate: (m) => luhn(m),
};

function luhn(num: string): boolean {
  let sum = 0;
  let alt = false;
  for (let i = num.length - 1; i >= 0; i--) {
    let n = Number(num[i]);
    if (alt) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
    alt = !alt;
  }
  return sum % 10 === 0;
}

describe('runRecognizers', () => {
  it('finds matches and tags them with the recognizer label', () => {
    const text = 'leak: AKIAIOSFODNN7EXAMPLE rotate now';
    const spans = runRecognizers(text, [awsKey], []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('secret');
    expect(spans[0]?.text).toBe('AKIAIOSFODNN7EXAMPLE');
  });

  it('high-confidence recognizers (≥0.9) emit even when overlapping ML output', () => {
    // ML mislabels (e.g., narrative adapter classifies an AWS key as
    // `account_number`); the regex's `secret` label at 0.99 must still
    // be emitted so cross-label dedupe in `nullpii.ts` can pick the
    // correct label.
    const text = 'AKIAIOSFODNN7EXAMPLE';
    const existing: PiiSpan[] = [
      { label: 'account_number', start: 0, end: 20, score: 0.6, text: 'AKIAIOSFODNN7EXAMPLE' },
    ];
    const spans = runRecognizers(text, [awsKey], existing);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('secret');
  });

  it('low-confidence recognizers still defer to ML on overlap', () => {
    const text = 'foo bar baz';
    const lowConf: Recognizer = {
      id: 'noise',
      pattern: /bar/g,
      label: 'private_person',
      confidence: 0.5,
    };
    const existing: PiiSpan[] = [
      { label: 'private_person', start: 4, end: 7, score: 0.8, text: 'bar' },
    ];
    expect(runRecognizers(text, [lowConf], existing)).toHaveLength(0);
  });

  it('honours validate() — Luhn rejects an invalid 16-digit string', () => {
    const text = 'card 1234567812345678 charged';
    expect(luhn('1234567812345678')).toBe(false);
    expect(runRecognizers(text, [luhnCard], [])).toHaveLength(0);
  });

  it('honours validate() — Luhn accepts a valid 16-digit string', () => {
    const text = 'card 4242424242424242 charged';
    expect(luhn('4242424242424242')).toBe(true);
    const spans = runRecognizers(text, [luhnCard], []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('account_number');
  });

  it('finds multiple non-overlapping matches in one pass', () => {
    const text = 'AKIAIOSFODNN7EXAMPLE and AKIAIOSFODNN7EXAMPLB rotate';
    const spans = runRecognizers(text, [awsKey], []);
    expect(spans).toHaveLength(2);
  });

  it('auto-adds the global flag if missing', () => {
    const reco: Recognizer = { id: 'x', pattern: /foo/, label: 'secret', confidence: 0.5 };
    const spans = runRecognizers('foo foo foo', [reco], []);
    expect(spans).toHaveLength(3);
  });

  // Validator-passing matches emit a score above plausible ML softmax
  // (~0.99998 for GLiNER) so cross-label IoU dedupe in nullpii.ts picks
  // the recognizer's label, not an ML mislabel (e.g. spaced IBAN tagged
  // `private_address`).
  it('boosts emitted score above ML softmax for validator-passing matches', () => {
    const validatedReco: Recognizer = {
      id: 'validated',
      pattern: /\b1234\b/g,
      label: 'account_number',
      confidence: 0.95,
      validate: () => true,
    };
    const spans = runRecognizers('seq 1234 end', [validatedReco], []);
    expect(spans).toHaveLength(1);
    const s = spans[0];
    expect(s?.score).toBeGreaterThan(0.9999);
    expect(s?.score).toBeGreaterThan(validatedReco.confidence);
  });

  it('leaves emitted score at recognizer.confidence when no validator set', () => {
    const unvalidatedReco: Recognizer = {
      id: 'plain',
      pattern: /\b1234\b/g,
      label: 'account_number',
      confidence: 0.95,
    };
    const spans = runRecognizers('seq 1234 end', [unvalidatedReco], []);
    expect(spans[0]?.score).toBe(0.95);
  });

  // Fast-path (indexOf prefix scan) must emit the same span set as the
  // pure-regex slow path across DEFAULT_RECOGNIZERS.
  it('fast-path and slow-path produce identical spans across DEFAULT_RECOGNIZERS', async () => {
    const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
    // Curated corpus exercising both anchored prefixes and structural
    // patterns; mix in negatives + noise to flush boundary handling.
    const corpus = [
      'leak: AKIAIOSFODNN7EXAMPLE rotate now',
      'token: ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890',
      `sk-ant-api03-${'a'.repeat(93)}AA in note`,
      'STRIPE=sk_live_aBcDeFgHiJkLmNoPqRsTuVwX trailing',
      'google api AIzaSyA0123456789ABCDEFGHIJklmnoPQRSTUV0',
      'slack xoxb-1234567890-abcdefghijklmn',
      'gitlab glpat-abcdefghij1234567890',
      'npm token npm_abcdefghijklmnopqrstuvwxyz0123456789',
      'huggingface hf_abcdefghijklmnopqrstuvwxyz01234567ZZ',
      'IBAN GB29 NWBK 6016 1331 9268 19 ok',
      'visa 4242 4242 4242 4242 charged',
      'IPv4 8.8.8.8 reachable',
      'private 10.0.0.1 (RFC1918) and 224.0.0.1 (multicast)',
      'email john@acme.io and 12345 67890 noise',
      'no PII here just words and numbers 99999999',
      // boundary stress: prefix appears mid-word (should NOT trigger)
      'mid-word XAKIAIOSFODNN7EXAMPLE',
      // adjacent placeholders
      'AKIAIOSFODNN7EXAMPLE and AKIAIOSFODNN7EXAMPLB rotate',
    ].join('\n\n');

    // Slow-path reference: run each recognizer independently.
    const referenceSpans: PiiSpan[] = [];
    for (const r of DEFAULT_RECOGNIZERS) {
      referenceSpans.push(...runRecognizers(corpus, [r], []));
    }

    // Fast + slow combined (current implementation):
    const actualSpans = runRecognizers(corpus, DEFAULT_RECOGNIZERS, []);

    // Sort by (start, end, label) for stable comparison.
    const sort = (arr: PiiSpan[]) =>
      [...arr].sort(
        (a, b) =>
          a.start - b.start || a.end - b.end || a.label.localeCompare(b.label) || a.score - b.score,
      );
    expect(sort(actualSpans)).toEqual(sort(referenceSpans));
  });

  // F-28 regression. MAC addresses used to ride on the `private_ip` label
  // even though they identify hardware, not network endpoints. The
  // dedicated `private_mac` label keeps grouping accurate for consumers
  // that bucket spans by label.
  it('emits the core:mac recognizer span with the private_mac label', async () => {
    const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
    const mac = DEFAULT_RECOGNIZERS.find((r) => r.id === 'core:mac');
    expect(mac).toBeDefined();
    expect(mac?.label).toBe('private_mac');
    const spans = runRecognizers('mac 01:23:45:67:89:ab end', mac ? [mac] : [], []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('private_mac');
  });

  describe('credential recognizers (cloud / payments / chat)', () => {
    it('catches an AWS secret access key only when canonically hinted', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((r) => r.id === 'core:aws-secret-key-hinted');
      expect(r).toBeDefined();
      const key = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY';
      const hinted = `config: aws_secret_access_key=${key} done`;
      const unhinted = `random base64 ${key} no anchor`;
      expect(runRecognizers(hinted, r ? [r] : [], []).length).toBeGreaterThanOrEqual(1);
      expect(runRecognizers(unhinted, r ? [r] : [], []).length).toBe(0);
    });

    it('catches an Azure storage AccountKey fragment', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((r) => r.id === 'core:azure-connection-string');
      expect(r).toBeDefined();
      const conn =
        'DefaultEndpointsProtocol=https;AccountName=foo;AccountKey=' +
        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN12==;EndpointSuffix=core.windows.net';
      const spans = runRecognizers(conn, r ? [r] : [], []);
      expect(spans).toHaveLength(1);
      expect(spans[0]?.label).toBe('secret');
    });

    it('catches a Stripe live secret key, ignores a test key', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((r) => r.id === 'core:stripe-live-key');
      expect(r).toBeDefined();
      const live = 'sk_live_aBcDeFgHiJkLmNoPqRsTuVwXyZ';
      const test = 'sk_test_aBcDeFgHiJkLmNoPqRsTuVwXyZ';
      expect(runRecognizers(`KEY=${live} ok`, r ? [r] : [], [])).toHaveLength(1);
      expect(runRecognizers(`KEY=${test} ok`, r ? [r] : [], [])).toHaveLength(0);
    });

    it('catches a Slack token (xoxa / xoxb / xoxp / xoxr / xoxs)', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((r) => r.id === 'core:slack-token');
      expect(r).toBeDefined();
      const corpus = 'bot xoxb-1234567890-abcdefghijklmn user xoxp-1234567890-abcdef';
      const spans = runRecognizers(corpus, r ? [r] : [], []);
      expect(spans.length).toBeGreaterThanOrEqual(2);
    });
  });

  describe('passport recognizers (context-anchored, v0.3)', () => {
    it('US passport REQUIRES context — bare letter+8-digits does not match', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const ids = DEFAULT_RECOGNIZERS.map((x) => x.id);
      expect(ids).not.toContain('core:passport-us');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:passport-us-context');
      expect(r).toBeDefined();
      // Bare letter+8-digit collides with id_card / license numbers.
      expect(runRecognizers('order A12345678 shipped', r ? [r] : [], [])).toHaveLength(0);
      const ok = runRecognizers('passport: A12345678 issued 2024', r ? [r] : [], []);
      expect(ok).toHaveLength(1);
      expect(ok[0]?.label).toBe('private_passport');
    });

    it('UK passport REQUIRES context — 9 bare digits do not match', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:passport-uk-context');
      expect(r).toBeDefined();
      expect(runRecognizers('order 123456789 received', r ? [r] : [], [])).toHaveLength(0);
      const ok = runRecognizers('passport no. 123456789', r ? [r] : [], []);
      expect(ok).toHaveLength(1);
      expect(ok[0]?.label).toBe('private_passport');
    });

    it('Italian passport — context-anchored only (uncontexted variant removed)', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const idsByLabel = DEFAULT_RECOGNIZERS.filter((x) => x.label === 'private_passport').map(
        (x) => x.id,
      );
      expect(idsByLabel).not.toContain('core:passport-it');
      expect(idsByLabel).toContain('core:passport-it-context');
      expect(idsByLabel).not.toContain('core:passport-de');
      expect(idsByLabel).toContain('core:passport-de-context');
      expect(idsByLabel).not.toContain('core:passport-es');
      expect(idsByLabel).toContain('core:passport-es-context');
    });

    it('generic passport fallback catches multilingual context (passnummer / passeport / pasaporte)', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:passport-generic-context');
      expect(r).toBeDefined();
      for (const corpus of [
        'passnummer: XY7654321',
        'passeport n°: 12AB34567',
        'pasaporte: ABC123456',
      ]) {
        const spans = runRecognizers(corpus, r ? [r] : [], []);
        expect(spans.length).toBeGreaterThanOrEqual(1);
        expect(spans[0]?.label).toBe('private_passport');
      }
    });
  });

  describe('driver licence recognizers (all context-anchored)', () => {
    it('California DL pattern matches under DL: / driver license: anchor', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:driver-license-ca-context');
      expect(r).toBeDefined();
      const ok = runRecognizers('DL: D1234567 expires 2027', r ? [r] : [], []);
      expect(ok).toHaveLength(1);
      expect(ok[0]?.label).toBe('private_driver_license');
      expect(runRecognizers('order D1234567 shipped', r ? [r] : [], [])).toHaveLength(0);
    });

    it('Italian patente — anchored on patente keyword', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:driver-license-it-context');
      expect(r).toBeDefined();
      const ok = runRecognizers('patente di guida: U1234567X', r ? [r] : [], []);
      expect(ok.length).toBeGreaterThanOrEqual(1);
      expect(ok[0]?.label).toBe('private_driver_license');
    });

    it('generic DL fallback covers EU keywords (führerschein / permis / rijbewijs)', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:driver-license-generic-context');
      expect(r).toBeDefined();
      for (const corpus of [
        'führerschein: B123456789',
        'permis de conduire: 13AB12345',
        'rijbewijs: 5512345678',
      ]) {
        const spans = runRecognizers(corpus, r ? [r] : [], []);
        expect(spans.length).toBeGreaterThanOrEqual(1);
        expect(spans[0]?.label).toBe('private_driver_license');
      }
    });
  });

  describe('vehicle id recognizers (VIN ISO 3779 + plates)', () => {
    it('VIN validator drops invalid check digit', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:vin');
      expect(r).toBeDefined();
      // Valid VIN (computed check digit) vs intentionally broken.
      expect(runRecognizers('vehicle 1HGCM82633A004352 owner', r ? [r] : [], [])).toHaveLength(1);
      expect(runRecognizers('vehicle 1HGCM82633A004353 owner', r ? [r] : [], [])).toHaveLength(0);
    });

    it('Italian plate matches 2L+3D+2L format', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:plate-it');
      expect(r).toBeDefined();
      const spans = runRecognizers('targa AB 123 CD italiana', r ? [r] : [], []);
      expect(spans.length).toBeGreaterThanOrEqual(1);
      expect(spans[0]?.label).toBe('private_vehicle_id');
    });

    it('US plate REQUIRES context anchor', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:plate-us-context');
      expect(r).toBeDefined();
      expect(runRecognizers('item ABC1234 in stock', r ? [r] : [], [])).toHaveLength(0);
      const ok = runRecognizers('license plate: ABC1234 reg.', r ? [r] : [], []);
      expect(ok).toHaveLength(1);
      expect(ok[0]?.label).toBe('private_vehicle_id');
    });
  });

  describe('geolocation recognizers', () => {
    it('lat/lon decimal pair matches within bounds, rejects out-of-range', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:geo-latlon-decimal');
      expect(r).toBeDefined();
      const ok = runRecognizers('met at 41.9028, 12.4964 yesterday', r ? [r] : [], []);
      expect(ok).toHaveLength(1);
      expect(ok[0]?.label).toBe('private_geolocation');
      // Out of range — validator rejects.
      expect(
        runRecognizers('values 200.1234, 300.5678 spreadsheet', r ? [r] : [], []),
      ).toHaveLength(0);
      // (0, 0) sentinel rejected to avoid placeholders.
      expect(runRecognizers('default 0.0, 0.0 fallback', r ? [r] : [], [])).toHaveLength(0);
    });

    it('DMS notation with hemisphere letter matches', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:geo-dms');
      expect(r).toBeDefined();
      const spans = runRecognizers('hike at 41°54\'09"N landmark', r ? [r] : [], []);
      expect(spans.length).toBeGreaterThanOrEqual(1);
      expect(spans[0]?.label).toBe('private_geolocation');
    });

    it('context-anchored single decimal matches lat: / lon: / gps:', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:geo-context');
      expect(r).toBeDefined();
      const ok = runRecognizers('latitude: 41.9028 logged', r ? [r] : [], []);
      expect(ok.length).toBeGreaterThanOrEqual(1);
      expect(ok[0]?.label).toBe('private_geolocation');
    });
  });

  describe('healthcare / device id recognizers (context-anchored)', () => {
    it('NPI REQUIRES anchor — bare 10-digit Luhn does not fire', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      // Old uncontexted core:npi-us removed; only context variant remains.
      const ids = DEFAULT_RECOGNIZERS.map((x) => x.id);
      expect(ids).not.toContain('core:npi-us');
      expect(ids).toContain('core:npi-us-context');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:npi-us-context');
      // 1234567897 = Luhn-valid 10-digit (passes the validator).
      expect(runRecognizers('called 1234567897 today', r ? [r] : [], [])).toHaveLength(0);
      const ok = runRecognizers('NPI: 1234567897 verified', r ? [r] : [], []);
      expect(ok).toHaveLength(1);
      expect(ok[0]?.label).toBe('account_number');
    });

    it('IMEI context-anchored — bare 15-digit Luhn does not fire', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const ids = DEFAULT_RECOGNIZERS.map((x) => x.id);
      expect(ids).not.toContain('core:imei');
      expect(ids).toContain('core:imei-context');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:imei-context');
      // 490154203237518 is the canonical Luhn-valid IMEI test number.
      expect(runRecognizers('txn 490154203237518 OK', r ? [r] : [], [])).toHaveLength(0);
      const ok = runRecognizers('IMEI: 490154203237518 cleared', r ? [r] : [], []);
      expect(ok).toHaveLength(1);
      expect(ok[0]?.label).toBe('account_number');
    });

    it('MBI matches structured 11-char pattern', async () => {
      const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
      const r = DEFAULT_RECOGNIZERS.find((x) => x.id === 'core:mbi-us');
      expect(r).toBeDefined();
      // Structure: D-L-D-LD-D-L-D-L-L-D-D (per CMS MBI spec).
      const ok = runRecognizers('MBI 1A2C3D4EF56 on file', r ? [r] : [], []);
      expect(ok).toHaveLength(1);
      expect(ok[0]?.label).toBe('account_number');
    });
  });
});
