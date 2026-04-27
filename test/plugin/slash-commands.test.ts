// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import { PluginState } from '../../packages/claude-code-plugin/src/plugin.js';

describe('PluginState slash commands', () => {
  it('returns help on bare /nullpii', () => {
    const s = new PluginState({});
    const out = s.handleSlashCommand({
      command: 'nullpii',
      args: [],
      conversationId: 'c1',
    });
    expect(out).toContain('status');
    expect(out).toContain('audit');
    expect(out).toContain('reset');
  });

  it('/nullpii status shows no-redactions before any prompt', () => {
    const s = new PluginState({});
    expect(
      s.handleSlashCommand({ command: 'nullpii', args: ['status'], conversationId: 'c' }),
    ).toBe('no redactions yet');
  });

  it('unknown root command returns undefined', () => {
    const s = new PluginState({});
    expect(s.handleSlashCommand({ command: 'foo', args: [] })).toBeUndefined();
  });

  it('skip patterns are honored — text returned unchanged with no spans', async () => {
    const s = new PluginState({ skip: ['^/git\\b'] });
    const out = await s.sanitizeForConversation('/git status now', 'c');
    expect(out.sanitized).toBe('/git status now');
    expect(out.spans).toHaveLength(0);
  });
});
