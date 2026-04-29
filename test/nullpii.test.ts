import { describe, expect, it } from 'vitest';
import { ModelNotInitializedError } from '../src/errors.js';
import { NullPii } from '../src/nullpii.js';
import { HAS_TEST_ARTIFACTS, TEST_MODEL_DIR } from './_env.js';

const ARTIFACT_MODEL_DIR = TEST_MODEL_DIR;
const itIfArtifacts = HAS_TEST_ARTIFACTS ? it : it.skip;

describe('NullPii lifecycle', () => {
  it('rejects sanitize after dispose with ModelNotInitializedError', async () => {
    const n = new NullPii({ modelDir: ARTIFACT_MODEL_DIR, backend: 'cpu', variant: 'int4' });
    await n.dispose();
    await expect(n.sanitize('hi')).rejects.toBeInstanceOf(ModelNotInitializedError);
  });
});

describe('NullPii end-to-end (gated on artifacts/model)', () => {
  itIfArtifacts(
    'sanitize → restore is byte-for-byte idempotent',
    async () => {
      const n = new NullPii({ modelDir: ARTIFACT_MODEL_DIR, backend: 'cpu', variant: 'int4' });
      const text = 'Hi, my name is John Smith and my email is john@example.com.';
      const out = await n.sanitize(text);
      expect(out.sanitized).not.toBe(text);
      expect(out.spans.length).toBeGreaterThan(0);
      const back = n.restore(out.sanitized, out.sessionId);
      expect(back.restored).toBe(text);
      await n.dispose();
    },
    180_000,
  );

  itIfArtifacts(
    'sanitize on PII-free text returns text unchanged',
    async () => {
      const n = new NullPii({ modelDir: ARTIFACT_MODEL_DIR, backend: 'cpu', variant: 'int4' });
      const text = 'The quick brown fox jumps over the lazy dog.';
      const out = await n.sanitize(text);
      expect(out.sanitized).toBe(text);
      expect(out.spans).toHaveLength(0);
      await n.dispose();
    },
    180_000,
  );

  itIfArtifacts(
    'init() is idempotent (concurrent calls share one promise)',
    async () => {
      const n = new NullPii({ modelDir: ARTIFACT_MODEL_DIR, backend: 'cpu', variant: 'int4' });
      const a = n.init();
      const b = n.init();
      // both promises resolve together — same underlying init
      await Promise.all([a, b]);
      const out = await n.sanitize('Email: a@b.com');
      expect(out).toBeDefined();
      await n.dispose();
    },
    180_000,
  );
});
