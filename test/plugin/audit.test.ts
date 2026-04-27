// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import { AuditLog } from '../../packages/claude-code-plugin/src/audit.js';
import type { PiiSpan } from '../../src/types/index.js';

function span(label: PiiSpan['label'], start: number, end: number): PiiSpan {
  return { label, start, end, score: 0.99, text: 'X' };
}

describe('AuditLog', () => {
  it('records counts per category, not raw text', () => {
    const log = new AuditLog();
    const spans = [
      span('private_person', 0, 4),
      span('private_email', 10, 20),
      span('private_email', 30, 40),
    ];
    log.record('conv-1', 'pre-prompt', spans, 100);
    const rows = log.forConversation('conv-1');
    expect(rows).toHaveLength(1);
    const r = rows[0];
    expect(r?.totalSpans).toBe(3);
    expect(r?.counts.private_email).toBe(2);
    expect(r?.counts.private_person).toBe(1);
    expect(r?.counts.secret).toBe(0);
  });

  it('summary returns no-redactions string before any record', () => {
    const log = new AuditLog();
    expect(log.summary('empty')).toBe('no redactions yet');
  });

  it('summary aggregates totals across turns', () => {
    const log = new AuditLog();
    log.record('c', 'pre-prompt', [span('private_person', 0, 4)], 50);
    log.record('c', 'pre-prompt', [span('private_email', 0, 10)], 50);
    expect(log.summary('c')).toContain('2 spans across 2 turns');
  });

  it('forConversation isolates by id', () => {
    const log = new AuditLog();
    log.record('a', 'pre-prompt', [], 10);
    log.record('b', 'pre-prompt', [], 10);
    expect(log.forConversation('a')).toHaveLength(1);
    expect(log.forConversation('b')).toHaveLength(1);
    expect(log.all()).toHaveLength(2);
  });
});
