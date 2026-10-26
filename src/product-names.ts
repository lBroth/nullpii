// SPDX-License-Identifier: Apache-2.0

/**
 * "Claude", the assistant's name, labelled `private_person`.
 *
 * In a Claude Code session the word is everywhere in text the agent
 * reads: "Claude Code", "the Claude Agent SDK", `CLAUDE.md`, `~/.claude/`,
 * `claude.ai`. The model labels it a person. In one hands-on session, 44
 * of the 50 person placeholders in Claude Code's own context were this
 * word, so the agent read its instructions with holes in them, and a
 * shell command naming `~/.claude/…` held a placeholder and was refused.
 * The AB-1 annotation spec lists product names as text to keep.
 *
 * Deliberately narrow: only a span whose text is the word alone, in any
 * case, is dropped. "Claude Dupont" stays masked as a full name. A
 * colleague called Claude, written by first name only, reaches the model
 * readable: the cost of this rule.
 */

/** The word alone, with the stray punctuation span boundaries carry. */
const ASSISTANT_NAME = /^\W*claude\W*$/i;

const PERSON_LABEL = 'private_person';

/**
 * Drop model `private_person` spans whose text is "Claude" alone. Spans
 * of every other label, and longer person spans, pass through untouched.
 *
 * @param spans - decoded model spans
 * @param text - the text the span offsets index into
 */
export function dropAssistantNameSpans<T extends { label: string; start: number; end: number }>(
  spans: T[],
  text: string,
): T[] {
  return spans.filter(
    (s) => s.label !== PERSON_LABEL || !ASSISTANT_NAME.test(text.slice(s.start, s.end)),
  );
}
