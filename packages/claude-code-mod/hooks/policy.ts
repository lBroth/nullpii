// SPDX-License-Identifier: Apache-2.0
//
// Pure helpers for the nullpii mod: which tool arguments get real values
// back, and how the counts are shown. No mods API calls live here, so
// `claude plugin validate` reads every `$` call from register.ts.

/**
 * Arguments that get their real values back before a tool runs, per tool.
 * Only tools that act on this machine are listed. A tool that sends its
 * input elsewhere (WebFetch, WebSearch, MCP tools) keeps the placeholders,
 * so a masked value never leaves the machine through a tool call.
 */
export const RESTORE_FIELDS: Readonly<Record<string, readonly string[]>> = {
  Bash: ['command'],
  Read: ['file_path'],
  Edit: ['file_path', 'old_string', 'new_string'],
  Write: ['file_path', 'content'],
  NotebookEdit: ['notebook_path', 'new_source'],
  Grep: ['pattern', 'path', 'glob'],
  Glob: ['pattern', 'path'],
};

const LABEL_PREFIX = 'private_';

export interface Counts {
  masked: number;
  restored: number;
  byLabel: Record<string, number>;
}

export function emptyCounts(): Counts {
  return { masked: 0, restored: 0, byLabel: {} };
}

/** Add one sidecar sanitize response to the session's counts. */
export function addMasked(
  counts: Counts,
  captured: number,
  byLabel: Readonly<Record<string, number>>,
): void {
  counts.masked += captured;
  for (const [label, n] of Object.entries(byLabel)) {
    counts.byLabel[label] = (counts.byLabel[label] ?? 0) + n;
  }
}

function shortLabel(label: string): string {
  return label.startsWith(LABEL_PREFIX) ? label.slice(LABEL_PREFIX.length) : label;
}

/** Labels by count, largest first: `person 5 · email 3`. */
export function formatLabels(byLabel: Readonly<Record<string, number>>, limit: number): string {
  return Object.entries(byLabel)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([label, n]) => `${shortLabel(label)} ${n}`)
    .join(' · ');
}

/** The one line shown above the prompt. */
export function formatBand(counts: Counts, problem: string | undefined): string {
  if (problem !== undefined) return `nullpii · blocking: ${problem}`;
  if (counts.masked === 0) return 'nullpii · on · nothing masked yet';
  const labels = formatLabels(counts.byLabel, 4);
  return `nullpii · ${counts.masked} masked (${labels}) · ${counts.restored} restored to local tools`;
}

/** The `/pii` command's reply. */
export function formatReport(counts: Counts, problem: string | undefined): string {
  const lines = [
    problem === undefined ? 'Status: on' : `Status: blocking (${problem})`,
    `Masked before Claude read them: ${counts.masked}`,
    `Real values put back into local tool calls: ${counts.restored}`,
  ];
  const labels = formatLabels(counts.byLabel, Number.POSITIVE_INFINITY);
  if (labels !== '') lines.push(`By type: ${labels}`);
  return lines.join('\n');
}
