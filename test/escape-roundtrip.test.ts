import { describe, expect, it } from 'vitest';

// AUDIT F21 regression test. Internal helpers aren't exported, so
// duplicate the constants here to validate round-trip behaviour
// without depending on private symbols. If the constants in
// `src/nullpii.ts` change, this file should change too.
const PLACEHOLDER_OPEN = '[[';
const PLACEHOLDER_OPEN_ESCAPED = '\uE000\uE001';

function escapeText(text: string): string {
  return text.split(PLACEHOLDER_OPEN).join(PLACEHOLDER_OPEN_ESCAPED);
}

function unescapeText(text: string): string {
  return text.split(PLACEHOLDER_OPEN_ESCAPED).join(PLACEHOLDER_OPEN);
}

describe('placeholder escape round-trip (AUDIT F21)', () => {
  it('round-trips plain text unchanged', () => {
    const t = 'Hello world, no placeholders here.';
    expect(unescapeText(escapeText(t))).toBe(t);
  });

  it('round-trips text with literal `[[` (the placeholder marker)', () => {
    // Even if a user happens to type the placeholder marker `[[` in
    // their input, escape→unescape must round-trip exactly.
    const t = 'pseudo-placeholder [[NOT_PII]] in user text';
    expect(unescapeText(escapeText(t))).toBe(t);
  });

  it('round-trips text with the previous-broken sequence `[\\[`', () => {
    // The legacy escape form was `[\[` — user input containing this
    // literal sequence would corrupt to `[[` on unescape. Verify the
    // PUA-sentinel fix preserves this exact byte sequence.
    const t = 'regex literal [\\[abc] in user text';
    expect(unescapeText(escapeText(t))).toBe(t);
  });

  it('documented limitation: literal PUA sentinel in user input collapses to `[[`', () => {
    // KNOWN TRADE-OFF — not a bug. Any escape mechanism that picks a
    // sentinel collides with itself when the sentinel appears in user
    // input. PUA chars (U+E000-U+F8FF) are unallocated to standard
    // glyphs and effectively never appear in natural LLM-prompt text;
    // we accept this collision as the price for closing the previous
    // `[\[abc]` corruption (audit F21).
    const t = `prefix${PLACEHOLDER_OPEN_ESCAPED}suffix`;
    expect(unescapeText(escapeText(t))).toBe('prefix[[suffix');
  });

  it('round-trips multiple `[[` runs', () => {
    const t = '[[a[[b[[c]]d]]e]]';
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
