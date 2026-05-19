// SPDX-License-Identifier: Apache-2.0

/**
 * Wire-format traffic dump. Writes sanitized request bodies + raw
 * upstream responses to stdout, BEFORE the gateway restores
 * placeholders. By construction these bodies carry placeholder tokens
 * only — never real PII — so this respects the "never log PII"
 * project rule.
 *
 * Enabled via `NULLPII_LOG_TRAFFIC=wire`. No-op otherwise.
 */

const ANSI = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  cyan: '\x1b[36m',
  magenta: '\x1b[35m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
};

function useColor(): boolean {
  return process.stdout.isTTY ?? false;
}

function header(arrow: string, color: string, label: string, reqId: string | undefined): string {
  const c = useColor();
  const tint = c ? color : '';
  const reset = c ? ANSI.reset : '';
  const dim = c ? ANSI.dim : '';
  const id = reqId !== undefined ? ` ${dim}[${reqId}]${reset}` : '';
  return `${tint}${arrow} ${label}${reset}${id}`;
}

function pretty(body: unknown): string {
  try {
    return JSON.stringify(body, null, 2);
  } catch {
    return String(body);
  }
}

/** Dump the outbound (sanitized) request body — what Anthropic will
 * actually see. Body fields contain placeholders, never real PII. */
export function logOutboundRequest(body: unknown, reqId?: string): void {
  process.stdout.write(`\n${header('→', ANSI.cyan, 'REQ  (sanitized → anthropic)', reqId)}\n`);
  process.stdout.write(`${pretty(body)}\n`);
}

/** Dump the inbound non-stream response body BEFORE restore. The body
 * carries placeholders the upstream echoed back — restore happens
 * after this dump. */
export function logInboundResponse(text: string, reqId?: string): void {
  process.stdout.write(`\n${header('←', ANSI.magenta, 'RES  (anthropic → restore)', reqId)}\n`);
  process.stdout.write(`${text}\n`);
}

/** Dump a raw SSE chunk as it arrives from upstream, pre-restore.
 * Called for every chunk so the user can watch the stream flow byte
 * by byte (still placeholder-bearing). */
export function logInboundSseChunk(chunk: string, reqId?: string): void {
  const c = useColor();
  const dim = c ? ANSI.dim : '';
  const reset = c ? ANSI.reset : '';
  const tag = c ? `${ANSI.magenta}← SSE${reset}` : '← SSE';
  const id = reqId !== undefined ? ` ${dim}[${reqId}]${reset}` : '';
  process.stdout.write(`${tag}${id} ${dim}${chunk.length}b${reset}\n${chunk}`);
}
