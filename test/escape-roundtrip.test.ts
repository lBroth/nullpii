import { describe, expect, it } from 'vitest';
import {
  PLACEHOLDER_OPEN_ESCAPED,
  escapePlaceholders as escapeText,
  unescapePlaceholders as unescapeText,
} from '../src/placeholder-escape.js';

describe('placeholder escape round-trip', () => {
  it('round-trips plain text unchanged', () => {
    const t = 'Hello world, no placeholders here.';
    expect(unescapeText(escapeText(t))).toBe(t);
  });

  it('round-trips text with literal `{{` (the placeholder marker)', () => {
    // Even if a user happens to type the placeholder marker `{{` in
    // their input (e.g. a Mustache template, JSX expression,
    // Vue/Handlebars binding), escape→unescape must round-trip exactly.
    const t = 'pseudo-placeholder {{NOT_PII}} in user text';
    expect(unescapeText(escapeText(t))).toBe(t);
  });

  it('round-trips Mustache-style spans without colliding with PII placeholders', () => {
    // User-authored Mustache variables that don't match the
    // `{{PII_<TYPE>_<N>}}` pattern must survive escape→unescape
    // unchanged.
    const t = 'Hello {{user.first_name}} from {{org.country}}';
    expect(unescapeText(escapeText(t))).toBe(t);
  });

  it('documented limitation: literal PUA sentinel in user input collapses to `{{`', () => {
    // KNOWN TRADE-OFF — not a bug. Any sentinel-based escape collides
    // with itself when the sentinel appears in user input. PUA chars
    // (U+E000-U+F8FF) are unallocated and effectively never appear in
    // natural LLM-prompt text; accepted as the price of the round-trip.
    const t = `prefix${PLACEHOLDER_OPEN_ESCAPED}suffix`;
    expect(unescapeText(escapeText(t))).toBe('prefix{{suffix');
  });

  it('round-trips multiple `{{` runs', () => {
    const t = '{{a{{b{{c}}d}}e}}';
    expect(unescapeText(escapeText(t))).toBe(t);
  });

  it('round-trips empty string', () => {
    expect(unescapeText(escapeText(''))).toBe('');
  });

  it('round-trips Unicode + emoji', () => {
    const t = 'Cyrillic а emoji 🚀 multilingual テスト';
    expect(unescapeText(escapeText(t))).toBe(t);
  });
});
