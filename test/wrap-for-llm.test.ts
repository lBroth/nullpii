import { describe, expect, it } from 'vitest';
import type { SanitizeResult } from '../src/types/index.js';
import { LLM_PRESERVATION_HINT, wrapForLLM } from '../src/wrap-for-llm.js';

const fakeResult: SanitizeResult = {
  sessionId: 'sess-abc',
  sanitized: 'Email {{PII_PRIVATE_PERSON_0}} at {{PII_PRIVATE_EMAIL_0}}',
  spans: [],
};

describe('wrapForLLM', () => {
  it('prefixes the preservation hint when called with a string', () => {
    const out = wrapForLLM('Hello {{PII_PRIVATE_PERSON_0}}');
    expect(out.startsWith(LLM_PRESERVATION_HINT)).toBe(true);
    expect(out.endsWith('Hello {{PII_PRIVATE_PERSON_0}}')).toBe(true);
  });

  it('accepts a SanitizeResult and uses its `.sanitized` body', () => {
    const out = wrapForLLM(fakeResult);
    expect(out).toContain(fakeResult.sanitized);
    expect(out).toContain(LLM_PRESERVATION_HINT);
  });

  it('inserts the optional task instruction between hint and body', () => {
    const out = wrapForLLM(fakeResult, 'Translate to Italian');
    const hintIdx = out.indexOf(LLM_PRESERVATION_HINT);
    const taskIdx = out.indexOf('Translate to Italian');
    const bodyIdx = out.indexOf(fakeResult.sanitized);
    expect(hintIdx).toBeGreaterThanOrEqual(0);
    expect(taskIdx).toBeGreaterThan(hintIdx);
    expect(bodyIdx).toBeGreaterThan(taskIdx);
  });

  it('omits the task block when task is empty / whitespace', () => {
    const empty = wrapForLLM(fakeResult, '   ');
    const noArg = wrapForLLM(fakeResult);
    expect(empty).toBe(noArg);
  });

  it('hint mentions the Mustache placeholder pattern', () => {
    expect(LLM_PRESERVATION_HINT).toContain('{{PII_<TYPE>_<N>}}');
    expect(LLM_PRESERVATION_HINT.toLowerCase()).toContain('preserve');
  });
});
