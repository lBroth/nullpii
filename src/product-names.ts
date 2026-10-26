// SPDX-License-Identifier: Apache-2.0

/**
 * "Claude", the assistant and its products, labelled `private_person`.
 *
 * In a Claude Code session the name is everywhere in text the agent
 * reads: "Claude Code", "the Claude Agent SDK", "Co-Authored-By: Claude
 * Opus 5.5", `CLAUDE.md`, `~/.claude/`, `claude.ai`. The model labels it
 * a person. In one hands-on session, 44 of the 50 person placeholders in
 * Claude Code's own context were this name, so the agent read its
 * instructions with holes in them, and a shell command naming
 * `~/.claude/…` held a placeholder and was refused. The AB-1 annotation
 * spec lists product names as text to keep.
 *
 * Deliberately narrow: a span is dropped only when its text is "Claude"
 * alone, or "Claude" and one of a closed list of product words (Code,
 * Desktop, API, Agent SDK, and the model names, with an optional
 * version), in any case. "Claude Dupont" stays masked as a full name. A
 * colleague called Claude, written by first name only, reaches the model
 * readable: the cost of this rule.
 */

/** The name alone or as a product, with the stray punctuation span
 * boundaries carry. */
const ASSISTANT_NAME =
  /^\W*claude(?:[ -](?:code|desktop|api|agent(?: sdk)?|opus|sonnet|haiku|fable)(?:[ -]\d+(?:\.\d+)*)?)?\W*$/i;

const PERSON_LABEL = 'private_person';

/**
 * Drop model `private_person` spans whose text is "Claude" alone or one of
 * its product names. Spans of every other label, and other person spans,
 * pass through untouched.
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
