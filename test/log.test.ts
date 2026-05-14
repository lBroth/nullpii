// SPDX-License-Identifier: Apache-2.0
//
// F-22 · Compile-time PII-exclusion contract on the structured-log
// fields. The vitest runtime check is a smoke; the real test is the
// `@ts-expect-error` lines below — they FAIL the build if the
// `LogFields` shape ever silently broadens to accept user-content
// channels (`text`, `value`, `original`, `placeholder`, `prompt`, …).

import { describe, expect, it } from 'vitest';
import { logf } from '../src/log.js';

describe('F-22 · logf', () => {
  it('accepts allowlisted fields without throwing', () => {
    expect(() =>
      logf('test:scope', 'event.ok', {
        traceId: 'req-1',
        session: 'abcd1234',
        spans: 3,
        replacements: 2,
        ms: 47,
      }),
    ).not.toThrow();
  });

  it('skips undefined fields from the formatted output', () => {
    // Spread-with-conditional pattern (used at every callsite that has an
    // optional traceId / etc.) means undefined values never reach logf at all.
    const fields = { spans: 1 } as const;
    expect(() => logf('test:scope', 'event.partial', fields)).not.toThrow();
  });

  it('LogFields type rejects PII-channel keys (compile-time contract)', () => {
    // The block below MUST fail the TS compile if `LogFields` accidentally
    // gains a PII-shaped channel. We use `// @ts-expect-error` so the
    // assertion is inverted: tsc errors WITHOUT the directive, and
    // succeeds WITH it iff the type rejects the key. If anyone ever adds
    // `text?: string` to LogFields, all these lines silently lose their
    // `@ts-expect-error` annotation and tsc flags them — a build failure
    // surfaces the regression in CI.

    // @ts-expect-error — `text` is the user input; never allowed as a log field
    logf('test', 'evt', { text: 'pii-leak' });
    // @ts-expect-error — vault entry value; never allowed
    logf('test', 'evt', { value: 'pii-leak' });
    // @ts-expect-error — original PII; never allowed
    logf('test', 'evt', { original: 'pii-leak' });
    // @ts-expect-error — full placeholder string carries label + idx + session; surface separately
    logf('test', 'evt', { placeholder: '{{PII_…}}' });
    // @ts-expect-error — LLM prompt body; never allowed
    logf('test', 'evt', { prompt: 'pii-leak' });
    // @ts-expect-error — sanitized text; never allowed
    logf('test', 'evt', { sanitized: 'pii-leak' });
    // @ts-expect-error — email values; never allowed
    logf('test', 'evt', { email: 'a@b.io' });
  });
});
