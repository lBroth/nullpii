// SPDX-License-Identifier: Apache-2.0
import { NullPii, type PiiSpan } from 'nullpii';
import { AuditLog } from './audit.js';
import { type PluginSettings, readPluginSettings, toNullPiiConfig } from './config.js';

/**
 * Hook arguments are typed loosely because the Claude Code plugin host
 * passes a generic context object. Use these as the public contract.
 */
export interface PrePromptContext {
  readonly text: string;
  readonly conversationId?: string;
  readonly setPromptText?: (text: string) => void;
  readonly setMetadata?: (key: string, value: unknown) => void;
}

export interface PostResponseContext {
  readonly text: string;
  readonly conversationId?: string;
  readonly metadata?: Record<string, unknown>;
  readonly setResponseText?: (text: string) => void;
}

export interface SlashCommandContext {
  readonly command: string;
  readonly args: ReadonlyArray<string>;
  readonly conversationId?: string;
  readonly print?: (text: string) => void;
}

/** A NullPii engine + per-conversation session id store + audit log. */
export class PluginState {
  private engine: NullPii | null = null;
  private readonly sessionByConv = new Map<string, string>();
  private readonly skipPatterns: ReadonlyArray<RegExp>;
  readonly audit = new AuditLog();

  constructor(private readonly settings: PluginSettings) {
    this.skipPatterns = (settings.skip ?? []).map((p) => new RegExp(p));
  }

  private getEngine(): NullPii {
    if (this.engine === null) {
      this.engine = new NullPii(toNullPiiConfig(this.settings));
    }
    return this.engine;
  }

  /** Returns true if `text` matches a configured skip pattern. */
  shouldSkip(text: string): boolean {
    return this.skipPatterns.some((re) => re.test(text));
  }

  async sanitizeForConversation(
    text: string,
    conversationId: string | undefined,
  ): Promise<{ readonly sanitized: string; readonly spans: readonly PiiSpan[] }> {
    if (this.shouldSkip(text)) return { sanitized: text, spans: [] };
    const engine = this.getEngine();
    const existing =
      conversationId !== undefined ? this.sessionByConv.get(conversationId) : undefined;
    const r = await engine.sanitize(text, existing);
    if (conversationId !== undefined) this.sessionByConv.set(conversationId, r.sessionId);
    if (conversationId !== undefined) {
      this.audit.record(conversationId, 'pre-prompt', r.spans, text.length);
    }
    return { sanitized: r.sanitized, spans: r.spans };
  }

  restoreForConversation(text: string, conversationId: string | undefined): string {
    const engine = this.engine;
    if (engine === null || conversationId === undefined) return text;
    const sessionId = this.sessionByConv.get(conversationId);
    if (sessionId === undefined) return text;
    return engine.restore(text, sessionId).restored;
  }

  endConversation(conversationId: string): void {
    const sessionId = this.sessionByConv.get(conversationId);
    if (sessionId === undefined) return;
    this.engine?.destroySession(sessionId);
    this.sessionByConv.delete(conversationId);
  }

  /** Status string suitable for the Claude Code status bar. */
  statusFor(conversationId: string): string {
    return this.audit.summary(conversationId);
  }

  /** Dispatch one slash command. Returns text to print, or undefined for unknown. */
  handleSlashCommand(ctx: SlashCommandContext): string | undefined {
    const conv = ctx.conversationId ?? '(no conversation)';
    switch (ctx.command) {
      case 'nullpii': {
        const sub = ctx.args[0];
        if (sub === 'status') return this.statusFor(conv);
        if (sub === 'audit') return JSON.stringify(this.audit.forConversation(conv), null, 2);
        if (sub === 'reset') {
          this.endConversation(conv);
          return `vault reset for ${conv}`;
        }
        return 'commands: status | audit | reset';
      }
      default:
        return undefined;
    }
  }
}

/**
 * Plugin entry point. Returns hook callbacks suitable for `register`-ing
 * with the Claude Code plugin host.
 *
 * Usage in `.claude/settings.json`:
 * ```json
 * { "plugins": ["@nullpii/claude-code"], "nullpii": { "backend": "auto" } }
 * ```
 */
export function activate(): {
  readonly prePrompt: (ctx: PrePromptContext) => Promise<void>;
  readonly postResponse: (ctx: PostResponseContext) => Promise<void>;
  readonly onConversationEnd: (id: string) => void;
  readonly slashCommand: (ctx: SlashCommandContext) => string | undefined;
  readonly statusBar: (conversationId: string) => string;
  readonly state: PluginState;
} {
  const state = new PluginState(readPluginSettings());

  return {
    async prePrompt(ctx) {
      const out = await state.sanitizeForConversation(ctx.text, ctx.conversationId);
      ctx.setPromptText?.(out.sanitized);
      ctx.setMetadata?.('nullpii.spans', out.spans.length);
    },
    async postResponse(ctx) {
      const restored = state.restoreForConversation(ctx.text, ctx.conversationId);
      ctx.setResponseText?.(restored);
    },
    onConversationEnd(id) {
      state.endConversation(id);
    },
    slashCommand(ctx) {
      const out = state.handleSlashCommand(ctx);
      if (out !== undefined) ctx.print?.(out);
      return out;
    },
    statusBar(conversationId) {
      return state.statusFor(conversationId);
    },
    state,
  };
}
