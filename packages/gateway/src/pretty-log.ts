// SPDX-License-Identifier: Apache-2.0

/**
 * Pretty terminal summary of one Anthropic request roundtrip. Emits a
 * single colored line to stdout summarising what was captured on the
 * way out (sanitize) and what was restored on the way back (restore).
 *
 * Pino keeps emitting structured JSON; this helper is purely additive
 * UX for humans watching the gateway in dev. ANSI codes are skipped
 * when stdout is not a TTY (logs redirected to file, CI pipelines).
 */

import { ANSI, useColor } from './ansi.js';

/** Short human-readable form for each canonical PII label. */
const LABEL_ALIASES: Readonly<Record<string, string>> = {
  private_person: 'person',
  private_email: 'email',
  private_phone: 'phone',
  private_address: 'address',
  private_date: 'date',
  private_url: 'url',
  private_ip: 'ip',
  private_mac: 'mac',
  private_passport: 'passport',
  private_driver_license: 'license',
  private_vehicle_id: 'vehicle',
  private_geolocation: 'geo',
  account_number: 'account',
  secret: 'secret',
};

/** Color hint per category. Secrets / financial = red; identity =
 * magenta; contact = cyan; network = blue; everything else green. */
const LABEL_COLORS: Readonly<Record<string, string>> = {
  private_person: ANSI.magenta,
  private_email: ANSI.cyan,
  private_phone: ANSI.cyan,
  private_address: ANSI.green,
  private_date: ANSI.green,
  private_url: ANSI.blue,
  private_ip: ANSI.blue,
  private_mac: ANSI.blue,
  private_passport: ANSI.yellow,
  private_driver_license: ANSI.yellow,
  private_vehicle_id: ANSI.yellow,
  private_geolocation: ANSI.green,
  account_number: ANSI.red,
  secret: ANSI.brightRed,
};

export interface RequestSummary {
  /** 'JSON' for non-streaming, 'SSE' for streaming. */
  readonly mode: 'JSON' | 'SSE';
  /** Sanitize phase: PII spans replaced before the request hit the upstream. */
  readonly captured: number;
  readonly capturedByLabel: Readonly<Record<string, number>>;
  /** Restore phase: placeholders the upstream echoed back that we replaced. */
  readonly restored: number;
  readonly restoredByLabel: Readonly<Record<string, number | undefined>>;
  /** Drift indicators — values > 0 are noisy and warrant a yellow flag. */
  readonly unknownPlaceholders: number;
  readonly foreignPlaceholders: number;
  /** Optional Fastify reqId to correlate against the JSON log line. */
  readonly reqId?: string;
}

function formatLabelBag(
  bag: Readonly<Record<string, number | undefined>>,
  colored: boolean,
): string {
  const entries = Object.entries(bag).filter(([, n]) => (n ?? 0) > 0);
  if (entries.length === 0) return colored ? `${ANSI.dim}none${ANSI.reset}` : 'none';
  return entries
    .map(([label, n]) => {
      const short = LABEL_ALIASES[label] ?? label;
      if (!colored) return `${short}×${n}`;
      const color = LABEL_COLORS[label] ?? ANSI.green;
      return `${color}${short}${ANSI.reset}×${n}`;
    })
    .join(' ');
}

/**
 * Write a one-line colored summary to stdout. Safe to call on every
 * request — cheap string concat, no I/O beyond stdout.
 */
export function printRequestSummary(s: RequestSummary): void {
  const colored = useColor();
  const c = colored ? ANSI : null;
  const reset = c?.reset ?? '';
  const tag = c !== null ? `${c.dim}${s.mode.padEnd(4)}${reset}` : `${s.mode.padEnd(4)} `;
  const arrow = c !== null ? `${c.cyan}→${reset}` : '→';
  const back = c !== null ? `${c.cyan}←${reset}` : '←';
  const id = s.reqId !== undefined ? ` ${c?.dim ?? ''}[${s.reqId}]${reset}` : '';
  const capLabel =
    s.captured === 0
      ? c !== null
        ? `${c.dim}clean${reset}`
        : 'clean'
      : `${c?.bold ?? ''}${s.captured} captured${reset}  ${formatLabelBag(s.capturedByLabel, colored)}`;
  const restLabel =
    s.restored === 0
      ? c !== null
        ? `${c.dim}—${reset}`
        : '—'
      : `${c?.bold ?? ''}${s.restored} restored${reset}  ${formatLabelBag(s.restoredByLabel, colored)}`;
  const drift = s.unknownPlaceholders + s.foreignPlaceholders;
  const driftStr =
    drift > 0
      ? `  ${c?.yellow ?? ''}⚠ ${drift} unrestored (unknown=${s.unknownPlaceholders} foreign=${s.foreignPlaceholders})${reset}`
      : '';
  process.stdout.write(`${tag}${id}  ${arrow} ${capLabel}  ${back} ${restLabel}${driftStr}\n`);
}
