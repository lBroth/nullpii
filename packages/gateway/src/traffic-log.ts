// SPDX-License-Identifier: Apache-2.0

/**
 * Wire-format traffic dump, for debugging: writes the request body as
 * forwarded, its upstream-bound headers (auth masked) and the raw
 * upstream response to stdout, BEFORE the gateway restores placeholders.
 *
 * This is the one place the gateway knowingly writes content that can
 * hold personal data. What nullpii masked stays a placeholder, but
 * everything else is printed as it was sent or written: values the
 * detector missed, fields the gateway does not scan (images, documents,
 * `mcp_servers` and its credentials) and the model's output. SECURITY.md
 * states this exception to the "logs carry counts only" rule.
 *
 * Enabled via `NULLPII_LOG_TRAFFIC=wire`. No-op otherwise.
 */

import { ANSI, useColor } from './ansi.js';

function header(arrow: string, color: string, label: string, reqId: string | undefined): string {
  const c = useColor();
  const tint = c ? color : '';
  const reset = c ? ANSI.reset : '';
  const dim = c ? ANSI.dim : '';
  const id = reqId !== undefined ? ` ${dim}[${reqId}]${reset}` : '';
  return `${tint}${arrow} ${label}${reset}${id}`;
}

/** Max bytes dumped per log line. A non-streaming response capped at
 * `bodyLimitBytes` (default 10 MB) would otherwise paint the whole
 * payload across the terminal. 64 KB is enough to see message shape
 * + first tool_use block + first content chunk. */
const MAX_DUMP_BYTES = 64 * 1024;

/** Upstream named in the dump labels when a route does not pass one. */
const DEFAULT_TARGET = 'anthropic';

function truncate(s: string): string {
  if (s.length <= MAX_DUMP_BYTES) return s;
  return `${s.slice(0, MAX_DUMP_BYTES)}\n…[truncated ${s.length - MAX_DUMP_BYTES}b]`;
}

function pretty(body: unknown): string {
  try {
    return truncate(JSON.stringify(body, null, 2));
  } catch {
    return truncate(String(body));
  }
}

/** Dump the outbound (sanitized) request body — what the upstream
 * (`target`) will actually see: placeholders where nullpii masked a
 * value, everything else as forwarded. */
export function logOutboundRequest(body: unknown, reqId?: string, target = DEFAULT_TARGET): void {
  process.stdout.write(`\n${header('→', ANSI.cyan, `REQ  (sanitized → ${target})`, reqId)}\n`);
  process.stdout.write(`${pretty(body)}\n`);
}

/** Dump the upstream-bound HTTP headers (allowlist-filtered). Auth
 * tokens (`x-api-key`, `authorization`) are masked — we log the
 * presence + last 6 chars only so it's easy to confirm "yes a token
 * was forwarded" without leaking the credential. */
export function logOutboundHeaders(
  headers: Record<string, string>,
  reqId?: string,
  target = DEFAULT_TARGET,
): void {
  const c = useColor();
  const dim = c ? ANSI.dim : '';
  const reset = c ? ANSI.reset : '';
  const SENSITIVE = new Set(['authorization', 'x-api-key']);
  const masked: Record<string, string> = {};
  for (const [k, v] of Object.entries(headers)) {
    masked[k] = SENSITIVE.has(k.toLowerCase()) ? `<masked, …${v.slice(-6)}, len=${v.length}>` : v;
  }
  process.stdout.write(
    `${dim}HDR  (gateway → ${target})${reset} ${header('→', ANSI.cyan, '', reqId)}\n`,
  );
  process.stdout.write(`${pretty(masked)}\n`);
}

/** Dump the inbound non-stream response body BEFORE restore: the
 * placeholders the upstream echoed stay masked, the rest is what it
 * wrote. */
export function logInboundResponse(text: string, reqId?: string, target = DEFAULT_TARGET): void {
  process.stdout.write(`\n${header('←', ANSI.magenta, `RES  (${target} → restore)`, reqId)}\n`);
  process.stdout.write(`${truncate(text)}\n`);
}

/** Dump a raw SSE chunk as it arrives from upstream, pre-restore.
 * Called for every chunk so the user can watch the stream flow byte
 * by byte (placeholders still masked). */
export function logInboundSseChunk(chunk: string, reqId?: string): void {
  const c = useColor();
  const dim = c ? ANSI.dim : '';
  const reset = c ? ANSI.reset : '';
  const tag = c ? `${ANSI.magenta}← SSE${reset}` : '← SSE';
  const id = reqId !== undefined ? ` ${dim}[${reqId}]${reset}` : '';
  process.stdout.write(`${tag}${id} ${dim}${chunk.length}b${reset}\n${truncate(chunk)}`);
}
