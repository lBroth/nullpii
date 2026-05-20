// SPDX-License-Identifier: Apache-2.0

/**
 * Tiny wrapper around `fetch` for the upstream call. Surfaces both the
 * raw `Response` (so the route handler can mirror status + headers) and
 * the parsed body. Exposed as an injectable `Fetch` so tests can swap
 * it for a mock.
 */
export type Fetch = (input: string, init: RequestInit) => Promise<Response>;

export interface UpstreamCall {
  readonly status: number;
  readonly headers: Headers;
  readonly text: string;
}

/** Headers we MUST forward. Anything else the client sent is dropped
 * — keeping the upstream surface minimal reduces the chance of
 * leaking gateway-internal headers (`host`, `content-length`) into
 * the request. */
const FORWARD_HEADERS = [
  // Auth — `x-api-key` for console API keys, `authorization` for OAuth
  // bearer tokens (Claude Code subscription / Pro / Max login flow).
  // Either passes through verbatim so the client picks its own auth
  // mode without the gateway caring.
  'x-api-key',
  'authorization',
  // Anthropic API version + beta opt-ins.
  'anthropic-version',
  'anthropic-beta',
  // Client identifiers used by Anthropic to route rate limits, debug
  // telemetry, and feature-gate flags. Forwarding keeps Claude Code /
  // SDK clients indistinguishable from a direct upstream call.
  'user-agent',
  'x-app',
];
/** Header-name prefixes whose entire family is forwarded. The
 * Anthropic SDK adds `x-stainless-*` telemetry fields as it evolves;
 * match by prefix so the allowlist doesn't drift behind new SDK
 * releases. Same safety profile as `FORWARD_HEADERS`. */
const FORWARD_HEADER_PREFIXES = ['x-stainless-'];

export function buildUpstreamHeaders(
  reqHeaders: Record<string, string | string[] | undefined>,
): Record<string, string> {
  const out: Record<string, string> = { 'content-type': 'application/json' };
  const exact = new Set(FORWARD_HEADERS);
  for (const [name, v] of Object.entries(reqHeaders)) {
    const lower = name.toLowerCase();
    const matchesExact = exact.has(lower);
    const matchesPrefix = FORWARD_HEADER_PREFIXES.some((p) => lower.startsWith(p));
    if (!matchesExact && !matchesPrefix) continue;
    if (typeof v === 'string') out[lower] = v;
    else if (Array.isArray(v) && v.length > 0 && typeof v[0] === 'string') out[lower] = v[0];
  }
  return out;
}

export async function forwardToAnthropic(
  fetchImpl: Fetch,
  upstreamBaseUrl: string,
  path: string,
  body: unknown,
  headers: Record<string, string>,
): Promise<UpstreamCall> {
  const res = await fetchImpl(`${upstreamBaseUrl}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  const text = await res.text();
  return { status: res.status, headers: res.headers, text };
}
