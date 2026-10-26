// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { dropAssistantNameSpans } from '../src/product-names.js';

/** The model's span over the first occurrence of `value` in `text`. */
function spanOver(text: string, value: string, label = 'private_person') {
  const start = text.indexOf(value);
  return { label, start, end: start + value.length, score: 0.9 };
}

describe('dropAssistantNameSpans', () => {
  it('drops "Claude" alone, in the places Claude Code writes it', () => {
    const cases: Array<[string, string]> = [
      ['questions about Claude Code (the CLI tool)', 'Claude'],
      ['Initialize a new CLAUDE.md file', 'CLAUDE'],
      ['modify ~/.claude/keybindings.json', 'claude'],
      ['requires claude.ai account access', 'claude'],
      ['the harness executes these, not Claude, so', 'Claude,'],
    ];
    for (const [text, value] of cases) {
      expect(dropAssistantNameSpans([spanOver(text, value)], text), text).toEqual([]);
    }
  });

  it('keeps a full name, other words and other labels', () => {
    const cases: Array<[string, string, string]> = [
      ['Claude Dupont signed the lease', 'Claude Dupont', 'private_person'],
      ['Claudette Rossi called', 'Claudette', 'private_person'],
      ['token claude', 'claude', 'secret'],
    ];
    for (const [text, value, label] of cases) {
      expect(dropAssistantNameSpans([spanOver(text, value, label)], text), text).toHaveLength(1);
    }
  });
});
