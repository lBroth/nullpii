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

/** Headers we MUST forward (auth + protocol version). Anything else
 * the client sent is dropped — keeping the upstream surface minimal
 * reduces the chance of leaking gateway-internal headers (`host`,
 * `content-length`) into the request. */
const FORWARD_HEADERS = ['x-api-key', 'authorization', 'anthropic-version', 'anthropic-beta'];

export function buildUpstreamHeaders(
  reqHeaders: Record<string, string | string[] | undefined>,
): Record<string, string> {
  const out: Record<string, string> = { 'content-type': 'application/json' };
  for (const name of FORWARD_HEADERS) {
    const v = reqHeaders[name];
    if (typeof v === 'string') out[name] = v;
    else if (Array.isArray(v) && v.length > 0 && typeof v[0] === 'string') out[name] = v[0];
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
