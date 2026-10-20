// SPDX-License-Identifier: Apache-2.0
//
// What the Anthropic and OpenAI routes share: the 502 sent when the
// upstream cannot be reached, the client-disconnect wiring and
// backpressure of a streamed reply, and the per-request log line and
// console summary (counts only, never values).

import type { ServerResponse } from 'node:http';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { printRequestSummary } from '../pretty-log.js';
import type { RestoredResponse, SanitizedRequest } from '../sanitizer.js';

/** Status of a reply the gateway itself sends when the upstream call
 * failed or returned something it cannot relay. */
export const UPSTREAM_FAILURE_STATUS = 502;

/** Error `type` of those replies, in both routes' error envelopes. */
export const UPSTREAM_ERROR_TYPE = 'nullpii_upstream_error';

const SSE_CONTENT_TYPE = 'text/event-stream';

/** Restore counts a round trip logs: a `RestoredResponse` or the counters
 * of a streamed relay, which use the same names. */
export type RestoreCounts = Pick<
  RestoredResponse,
  | 'replacements'
  | 'replacementsByLabel'
  | 'unknownPlaceholders'
  | 'foreignPlaceholders'
  | 'unsafeShellPlaceholders'
  | 'heldForToolPlaceholders'
>;

/** Whether an upstream status is a success (2xx). */
export function isSuccess(status: number): boolean {
  return status >= 200 && status < 300;
}

/** The message of a thrown value, for logs and error replies. */
export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Aborts the upstream call when the client disconnects. `release()`
 * removes the listener once the reply no longer needs it. */
export interface ClientWatch {
  readonly abort: AbortController;
  release(): void;
}

/**
 * Wire a client disconnect to an `AbortController`, so a streamed upstream
 * call stops generating (and billing) tokens nobody reads. The signal is
 * `reply.raw` closing: on Node 16+ `req.raw` emits 'close' as soon as the
 * request body has been read, before the handler runs, so a listener
 * there never fires.
 */
export function watchClientClose(reply: FastifyReply): ClientWatch {
  const abort = new AbortController();
  const onClose = (): void => abort.abort();
  reply.raw.once('close', onClose);
  return { abort, release: () => reply.raw.off('close', onClose) };
}

/** Start a streamed 200 reply with the upstream's content type and take
 * over the socket, so Fastify does not buffer the stream. */
export function openSseReply(reply: FastifyReply, contentType: string | null): void {
  reply.raw.statusCode = 200;
  reply.raw.setHeader('content-type', contentType ?? SSE_CONTENT_TYPE);
  reply.raw.setHeader('cache-control', 'no-cache');
  reply.raw.setHeader('connection', 'keep-alive');
  reply.hijack();
}

/**
 * Write one frame to the client, honouring backpressure: when the socket
 * buffer is full, wait for 'drain' before the relay reads more from the
 * upstream, so a slow client never makes the gateway hold a whole reply
 * in memory. Rejects once the client has gone, which ends the relay and
 * cancels the upstream call.
 */
export async function writeFrame(raw: ServerResponse, frame: string): Promise<void> {
  if (raw.destroyed || raw.writableEnded) throw new Error('client closed the connection');
  if (raw.write(frame)) return;
  await new Promise<void>((resolve, reject) => {
    const onDrain = (): void => {
      cleanup();
      resolve();
    };
    const onClose = (): void => {
      cleanup();
      reject(new Error('client closed the connection'));
    };
    const cleanup = (): void => {
      raw.off('drain', onDrain);
      raw.off('close', onClose);
    };
    raw.once('drain', onDrain);
    raw.once('close', onClose);
  });
}

/** One finished round trip, as logged. */
export interface RoundTrip {
  readonly req: FastifyRequest;
  readonly reqId: string | undefined;
  readonly sanitized: SanitizedRequest<unknown>;
  readonly mode: 'JSON' | 'SSE';
  /** Pino message of the log line (`anthropic.messages.restored`, …). */
  readonly event: string;
  readonly counts: RestoreCounts;
}

/**
 * Log a round trip and print its console summary. Counts and labels only:
 * `counts` may be a whole `RestoredResponse`, whose `body` holds the real
 * values, so its fields are picked one by one and never spread.
 */
export function logRoundTrip(trip: RoundTrip): void {
  const { sanitized, counts } = trip;
  trip.req.log.info(
    {
      captured: sanitized.captured,
      capturedByLabel: sanitized.capturedByLabel,
      unscanned: sanitized.unscanned,
      modelUnscannedWords: sanitized.modelUnscannedWords,
      replacements: counts.replacements,
      replacementsByLabel: counts.replacementsByLabel,
      unknownPlaceholders: counts.unknownPlaceholders,
      foreignPlaceholders: counts.foreignPlaceholders,
      unsafeShellPlaceholders: counts.unsafeShellPlaceholders,
      heldForToolPlaceholders: counts.heldForToolPlaceholders,
    },
    trip.event,
  );
  const summary = {
    mode: trip.mode,
    captured: sanitized.captured,
    capturedByLabel: sanitized.capturedByLabel,
    unscanned: sanitized.unscanned,
    modelUnscannedWords: sanitized.modelUnscannedWords,
    restored: counts.replacements,
    restoredByLabel: counts.replacementsByLabel,
    unknownPlaceholders: counts.unknownPlaceholders,
    foreignPlaceholders: counts.foreignPlaceholders,
    unsafeShell: counts.unsafeShellPlaceholders,
    heldForTool: counts.heldForToolPlaceholders,
  };
  printRequestSummary(trip.reqId !== undefined ? { ...summary, reqId: trip.reqId } : summary);
}
