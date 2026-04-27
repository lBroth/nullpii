// SPDX-License-Identifier: Apache-2.0
import type { PiiCategory, PiiSpan } from 'nullpii';

/** One row in the audit log. Counts only — never original PII values. */
export interface AuditEntry {
  readonly conversationId: string;
  readonly turn: number;
  readonly timestamp: number;
  readonly direction: 'pre-prompt' | 'post-response';
  readonly counts: Readonly<Record<PiiCategory, number>>;
  readonly totalSpans: number;
  readonly textLength: number;
}

/**
 * Append-only in-memory audit log of redaction events.
 *
 * Stores **counts only**, never the original PII text or placeholders.
 * Safe to display in a status bar / inspector.
 */
export class AuditLog {
  private readonly rows: AuditEntry[] = [];
  private turn = new Map<string, number>();

  record(
    conversationId: string,
    direction: AuditEntry['direction'],
    spans: readonly PiiSpan[],
    textLength: number,
  ): AuditEntry {
    const t = (this.turn.get(conversationId) ?? 0) + 1;
    this.turn.set(conversationId, t);
    const entry: AuditEntry = {
      conversationId,
      turn: t,
      timestamp: Date.now(),
      direction,
      counts: countByCategory(spans),
      totalSpans: spans.length,
      textLength,
    };
    this.rows.push(entry);
    return entry;
  }

  /** Read-only view of the entire log. */
  all(): readonly AuditEntry[] {
    return this.rows;
  }

  /** Read-only view filtered to one conversation. */
  forConversation(id: string): readonly AuditEntry[] {
    return this.rows.filter((r) => r.conversationId === id);
  }

  /** Compact one-line summary suitable for a status bar. */
  summary(conversationId: string): string {
    const rows = this.forConversation(conversationId);
    if (rows.length === 0) return 'no redactions yet';
    const total = rows.reduce((acc, r) => acc + r.totalSpans, 0);
    const turns = rows.length;
    return `🛡 ${total} span${total === 1 ? '' : 's'} across ${turns} turn${turns === 1 ? '' : 's'}`;
  }
}

function countByCategory(spans: readonly PiiSpan[]): Readonly<Record<PiiCategory, number>> {
  const counts: Record<PiiCategory, number> = {
    account_number: 0,
    private_address: 0,
    private_date: 0,
    private_email: 0,
    private_person: 0,
    private_phone: 0,
    private_url: 0,
    secret: 0,
  };
  for (const s of spans) counts[s.label] += 1;
  return counts;
}
