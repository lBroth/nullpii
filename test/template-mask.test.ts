// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { dropSpansInsideTemplates, findTemplateRanges } from '../src/template-mask.js';
import type { PiiSpan } from '../src/types/index.js';

function mkSpan(start: number, end: number, text: string): PiiSpan {
  return { label: 'private_person', start, end, text, score: 0.9 };
}

describe('findTemplateRanges', () => {
  it('detects Mustache / Handlebars `{{...}}`', () => {
    const text = 'hello {{name}} world';
    expect(findTemplateRanges(text)).toEqual([{ start: 6, end: 14 }]);
  });

  it('detects JS template literal `${...}`', () => {
    const text = 'hi ${user.name}!';
    expect(findTemplateRanges(text)).toEqual([{ start: 3, end: 15 }]);
  });

  it('detects ERB / EJS `<%...%>`', () => {
    const text = '<%= user.email %>';
    expect(findTemplateRanges(text)).toEqual([{ start: 0, end: 17 }]);
  });

  it('detects Jinja2 / Twig `{%...%}`', () => {
    const text = '{% if x %}body{% endif %}';
    expect(findTemplateRanges(text)).toEqual([
      { start: 0, end: 10 },
      { start: 14, end: 25 },
    ]);
  });

  it('handles mixed templates and merges overlaps', () => {
    const text = '{% if x %}{{name}}{% endif %}';
    const ranges = findTemplateRanges(text);
    expect(ranges).toEqual([
      { start: 0, end: 10 },
      { start: 10, end: 18 },
      { start: 18, end: 29 },
    ]);
  });

  it('non-greedy match — separate `{{a}}` and `{{b}}` produce two ranges', () => {
    const text = '{{a}} between {{b}}';
    expect(findTemplateRanges(text)).toEqual([
      { start: 0, end: 5 },
      { start: 14, end: 19 },
    ]);
  });

  it('returns empty for text without template syntax', () => {
    expect(findTemplateRanges('plain text only')).toEqual([]);
  });
});

describe('dropSpansInsideTemplates', () => {
  // Reference text: 'hello {{user_name}} send to alice@acme.io'
  // Template range = [6, 19); email = [28, 41).
  const templateSpan = mkSpan(8, 17, 'user_name');
  const emailSpan: PiiSpan = {
    label: 'private_email',
    start: 28,
    end: 41,
    text: 'alice@acme.io',
    score: 0.95,
  };

  it('drops spans fully inside a template range', () => {
    const out = dropSpansInsideTemplates([templateSpan, emailSpan], [{ start: 6, end: 19 }]);
    expect(out).toEqual([emailSpan]);
  });

  it('drops spans partially overlapping a template boundary', () => {
    // Span that crosses `}}` corrupts brackets after vault substitution.
    const crossing = mkSpan(15, 22, 'name}} s');
    const out = dropSpansInsideTemplates([crossing, emailSpan], [{ start: 6, end: 19 }]);
    expect(out).toEqual([emailSpan]);
  });

  it('keeps spans entirely outside template ranges', () => {
    const out = dropSpansInsideTemplates([emailSpan], [{ start: 6, end: 19 }]);
    expect(out).toEqual([emailSpan]);
  });

  it('no ranges → passthrough', () => {
    const out = dropSpansInsideTemplates([emailSpan, templateSpan], []);
    expect(out).toEqual([emailSpan, templateSpan]);
  });
});
